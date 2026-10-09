import queue
import threading
import time

from module.collector.frame_buffer import FrameBuffer
from module.collector.models import ClickEvent
from module.logger import logger


class CaptureWorker(threading.Thread):
    """唯一的截图调用点：滚动帧缓冲、画面变化检测、页面识别、点击后多帧采集

    device.screenshot() 存在共享状态（self.image 等），必须由本线程独占调用。
    """

    STABLE_THRESHOLD = 3.0        # 帧差均值低于该值视为画面稳定（动画结束）
    SCENE_THRESHOLD = 12.0        # 帧差均值高于该值视为画面显著变化
    SCENE_NOTIFY_INTERVAL = 10.0  # scene_change 事件节流（秒）
    AFTER_INTERVAL = 0.5          # 点击后补帧间隔（秒）
    MAX_AFTER_FRAMES = 4          # 点击后最多补帧数（另有立即 1 帧）

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
            self._detect_scene(ts, image)
            self._detect_page(ts, image)
            self._process_clicks()
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
        page = self.page_detector.detect(image)
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

    # ---------------- 点击采集 ----------------

    def _process_clicks(self):
        while True:
            try:
                click = self.click_queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._capture_click(click)
            except Exception as e:
                logger.error(f'Capture click failed: {e}')

    def _capture_click(self, click: ClickEvent):
        before = self.buffer.nearest_before(click.ts_press)
        if before is None:
            logger.warning(f'No before frame for click {click.event_id}')
            return

        # 点击后多帧：立即 1 帧 + 间隔续拍，帧差稳定（动画结束）提前停止
        after_frames = [(time.time(), self.device.screenshot())]
        early_stop = False
        for _ in range(self.MAX_AFTER_FRAMES):
            self.stop_event.wait(self.AFTER_INTERVAL)
            if self.stop_event.is_set():
                break
            image = self.device.screenshot()
            after_frames.append((time.time(), image))
            if FrameBuffer.diff(after_frames[-1][1], after_frames[-2][1]) < self.STABLE_THRESHOLD:
                early_stop = True
                break

        page_before = page_after = 'unknown'
        if self.page_detector is not None:
            pb = self.page_detector.detect(before.image)
            pa = self.page_detector.detect(after_frames[-1][1])
            page_before = pb.name if pb is not None else 'unknown'
            page_after = pa.name if pa is not None else 'unknown'

        event_id = self.storage.save_click(
            click,
            before=(before.ts, before.image),
            after_frames=after_frames,
            meta={'page_before': page_before, 'page_after': page_after, 'early_stop': early_stop},
        )
        logger.info(
            f'Click captured {event_id}: ({click.x}, {click.y}) '
            f'{page_before} -> {page_after}, frames={len(after_frames)}'
        )
