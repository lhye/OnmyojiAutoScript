import threading

from module.atom.image import RuleImage
from module.logger import logger


class TaskLoop:
    """优先级任务循环框架：按 priority 从小到大（优先级从高到低）逐个匹配画面模式，
    首个命中的模式执行其 handler。与现有调度器完全独立。

    用法:
        loop = TaskLoop(capture.get_latest, stop_event)
        loop.register(name='collect_reward', priority=10, matcher=I_REWARD, handler=lambda img: ...)
        loop.register(name='log_page', priority=99, matcher=my_func, handler=log_func)
        loop.start()
    """

    MATCH_INTERVAL = 0.5

    def __init__(self, get_frame, stop_event: threading.Event, match_interval: float = MATCH_INTERVAL):
        self.get_frame = get_frame
        self.stop_event = stop_event
        self.match_interval = match_interval
        self._tasks = []
        self._thread = None

    def register(self, name: str, priority: int, matcher, handler):
        """
        Args:
            name: 任务名
            priority: 优先级，数值越小越先匹配
            matcher: RuleImage 或 callable(image) -> bool
            handler: callable(image)，匹配成功后执行
        """
        self._tasks.append({'name': name, 'priority': priority, 'matcher': matcher, 'handler': handler})
        self._tasks.sort(key=lambda t: t['priority'])

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.run, daemon=True, name='TaskLoop')
        self._thread.start()

    def run(self):
        logger.hr('Collector task loop', level=2)
        while not self.stop_event.is_set():
            frame = self.get_frame()
            if frame is None:
                self.stop_event.wait(self.match_interval)
                continue
            _, image = frame
            for task in self._tasks:
                if self._match(task['matcher'], image):
                    logger.info(f'Task matched: {task["name"]}')
                    try:
                        task['handler'](image)
                    except Exception as e:
                        logger.error(f'Task {task["name"]} handler error: {e}')
                    break
            self.stop_event.wait(self.match_interval)

    @staticmethod
    def _match(matcher, image) -> bool:
        if isinstance(matcher, RuleImage):
            return matcher.match(image)
        return bool(matcher(image))
