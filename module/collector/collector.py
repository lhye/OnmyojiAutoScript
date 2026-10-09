import queue
import threading

from module.collector.capture import CaptureWorker
from module.collector.page_detect import PageDetector
from module.collector.storage import SessionStore
from module.collector.task_loop import TaskLoop
from module.collector.touch_listener import GeteventListener
from module.device.device import Device
from module.logger import logger


class CollectorService:
    """组装监听、采集、识别、任务循环各组件，统一启停

    线程模型：
        GeteventListener  getevent 流监听线程 -> click_queue
        CaptureWorker     唯一截图线程（滚动缓冲 / 帧差 / 页面识别 / 点击多帧采集）
        TaskLoop          优先级模式匹配循环（消费 get_latest）
    """

    def __init__(self, config, interval: float = 0.4, base: str = './log/collector',
                 enable_page_detect: bool = True):
        self.device = Device(config=config)
        self.device.disable_stuck_detection()
        self.device.screenshot_interval_set(interval)

        self.storage = SessionStore(base=base)
        self.stop_event = threading.Event()
        self.click_queue = queue.Queue()

        self.listener = GeteventListener(self.device, self.click_queue, self.stop_event)
        self.page_detector = None
        if enable_page_detect:
            try:
                self.page_detector = PageDetector()
            except Exception as e:
                logger.warning(f'PageDetector init failed, page detection disabled: {e}')
        self.capture = CaptureWorker(
            self.device, self.storage, self.click_queue, self.stop_event,
            interval=interval, page_detector=self.page_detector)
        self.task_loop = TaskLoop(self.capture.get_latest, self.stop_event)

    def start(self):
        if getattr(self.device, 'is_over_http', False):
            raise RuntimeError('getevent 监听不支持 adb over http 设备，请改用 tcp serial')
        self.storage.open_session()
        self.listener.start()
        self.capture.start()
        self.task_loop.start()
        logger.info('Collector started, press Ctrl+C to stop')

    def stop(self):
        self.stop_event.set()
        self.listener.close()  # 解除 recv 阻塞
        for thread in (self.listener, self.capture, self.task_loop):
            thread.join(timeout=5)
        self.storage.close_session()
        logger.info('Collector stopped')

    def click(self, x, y):
        """向客户端注入点击，供 TaskLoop handler 使用"""
        self.device.click(x, y)
