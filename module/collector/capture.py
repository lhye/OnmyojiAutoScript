import queue
import threading
import time

from module.collector.frame_buffer import FrameBuffer
from module.collector.models import TouchEvent
from module.logger import logger


class CaptureWorker(threading.Thread):
    """唯一的截图调用点：滚动帧缓冲、画面变化检测、页面识别、动作后多帧采集

    device.screenshot() 存在共享状态（self.image 等），必须由本线程独占调用。
    """

    STABLE_THRESHOLD = 3.0        # 帧差均值低于该值视为画面稳定（动画结束）
    SCENE_THRESHOLD = 12.0        # 帧差均值高于该值视为画面显著变化
    SCENE_NOTIFY_INTERVAL = 10.0  # scene_change 事件节流（秒）
    AFTER_INTERVAL = 0.5          # 点击后补帧间隔（秒）
    MAX_AFTER_FRAMES = 4          # 点击后最多补帧数（另有立即 1 帧）
    PAGE_DETECT_EVERY = 5         # 每 N 帧做一次页面识别（单次识别可达数百毫秒）

    def __init__(self, device, storage, click_queue: queue.Queue, stop_event: threading.Event,
                 interval: float = 0.4, page_detector=None):
        super().__init__(daemon=True, name='CaptureWorker')
        self.device = device
        self.storage = storage
        self.click_queue = click_queue
        self.stop_event = stop_event
        self.interval = interval
        self.page_detector = page_detector
        self.buffer = FrameBuffer(maxlen=32)
        self._frame_lock = threading.Lock()
        self._latest = None           # (ts, image)
        self._prev_image = None
        self._last_scene_ts = 0.0
        self._last_page = None
        self._frame_count = 0

    # ---------------- 对外接口 ----------------

    def get_latest(self):
        """返回最新帧 (ts, image)，image 为只读引用"""
        with self._frame_lock:
            return self._latest

    # ---------------- 主循环 ----------------

    def run(self):
        logger.hr('Collector capture loop', level=2)
        while not self.stop_event.is_set():
            try:
                image = self.device.screenshot()
            except Exception as e:
                logger.warning(f'Collector screenshot failed: {e}')
                self.stop_event.wait(2.0)
                continue
            ts = time.time()
            self.buffer.push(ts, image)
            with self._frame_lock:
                self._latest = (ts, image)
            self._frame_count += 1
            if self._frame_count == 1:
                logger.info(f'Capture first frame: {image.shape}')
            elif self._frame_count % 25 == 0:
                logger.info(
                    f'Capture alive: frames={self._frame_count}, '
                    f'queue={self.click_queue.qsize()}, page={self._last_page}'
                )
            self._detect_scene(ts, image)
            # 先处理待采集动作，保证动作后补帧尽早开始
            self._process_touches()
            # 页面识别较慢（几十到几百毫秒），按间隔抽样执行
            if self._frame_count % self.PAGE_DETECT_EVERY == 0:
                self._detect_page(ts, image)
            # device.screenshot() 内部按 interval 节流，这里仅保证停止响应
            self.stop_event.wait(0.05)

    # ---------------- 画面变化 ----------------

    def _detect_scene(self, ts: float, image):
        if self._prev_image is not None:
            diff = FrameBuffer.diff(self._prev_image, image)
            if diff > self.SCENE_THRESHOLD and ts - self._last_scene_ts > self.SCENE_NOTIFY_INTERVAL:
                self._last_scene_ts = ts
                self.storage.append_event('scene_change', {'frame_ts': ts, 'diff': round(diff, 3)})
                logger.info(f'Scene change, diff={diff:.1f}')
        self._prev_image = image

    def _detect_page(self, ts: float, image):
        if self.page_detector is None:
            return
        try:
            page = self.page_detector.detect(image)
        except Exception as e:
            # 页面识别异常不能让采集线程退出
            if not getattr(self, '_page_error_logged', False):
                self._page_error_logged = True
                logger.warning(f'Page detect error, ignored: {e}')
            return
        if page is None:
            return
        if self._last_page is not None and page.name != self._last_page:
            self.storage.append_event('page_change', {
                'frame_ts': ts,
                'page_before': self._last_page,
                'page_after': page.name,
            })
            logger.info(f'Page: {self._last_page} -> {page.name}')
        self._last_page = page.name

    # ---------------- 点击 / 滑动采集 ----------------

    def _process_touches(self):
        while True:
            try:
                event = self.click_queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._capture_touch(event)
            except Exception as e:
                logger.error(f'Capture touch failed: {e}')

    def _capture_touch(self, event: TouchEvent):
        before = self.buffer.nearest_before(event.ts_press)
        if before is None:
            logger.warning(f'No before frame for {event.kind} {event.event_id}')
            return

        # 动作后多帧：立即 1 帧 + 间隔续拍，帧差稳定（动画结束）提前停止
        # 补帧同时写入滚动缓冲，避免连续操作时“动作前”画面越拖越旧
        after_frames = [(time.time(), self.device.screenshot())]
        self.buffer.push(*after_frames[0])
        early_stop = False
        for _ in range(self.MAX_AFTER_FRAMES):
            self.stop_event.wait(self.AFTER_INTERVAL)
            if self.stop_event.is_set():
                break
            image = self.device.screenshot()
            after_frames.append((time.time(), image))
            self.buffer.push(*after_frames[-1])
            if FrameBuffer.diff(after_frames[-1][1], after_frames[-2][1]) < self.STABLE_THRESHOLD:
                early_stop = True
                break

        # 动作前页面复用最近一次抽样识别的结果，避免每个动作多做一次全量识别
        page_before = self._last_page or 'unknown'
        page_after = page_before
        if self.page_detector is not None:
            pa = self.page_detector.detect(after_frames[-1][1])
            if pa is not None:
                page_after = pa.name

        event_id = self.storage.save_touch(
            event,
            before=(before.ts, before.image),
            after_frames=after_frames,
            meta={'page_before': page_before, 'page_after': page_after, 'early_stop': early_stop},
        )
        if event.kind == 'swipe':
            logger.info(
                f'Swipe captured {event_id}: ({event.start_x}, {event.start_y}) -> '
                f'({event.end_x}, {event.end_y}), {event.duration}s '
                f'{page_before} -> {page_after}, frames={len(after_frames)}'
            )
        else:
            logger.info(
                f'Click captured {event_id}: ({event.x}, {event.y}) '
                f'{page_before} -> {page_after}, frames={len(after_frames)}'
            )
