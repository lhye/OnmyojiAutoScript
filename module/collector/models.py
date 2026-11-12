import time
from dataclasses import dataclass, field


def _make_event_id(ts_press: float) -> str:
    local = time.localtime(ts_press)
    return time.strftime('%Y%m%d_%H%M%S', local) + f'_{int(ts_press * 1000) % 1000:03d}'


@dataclass
class TouchEvent:
    """一次完整触摸（按下 -> 抬起）的公共字段"""
    ts_press: float          # 按下时间戳（本地 epoch 秒）
    ts_release: float = 0.0  # 抬起时间戳
    panel: str = ''          # 触摸设备路径，如 /dev/input/event4

    @property
    def kind(self) -> str:
        raise NotImplementedError

    @property
    def event_id(self) -> str:
        return _make_event_id(self.ts_press)

    def to_dict(self) -> dict:
        raise NotImplementedError


@dataclass
class ClickEvent(TouchEvent):
    """一次点击（按下与抬起位置基本一致）"""
    x_raw: int = -1          # 触摸面板原始坐标
    y_raw: int = -1
    x: float = -1.0          # 换算到 1280x720 的逻辑坐标
    y: float = -1.0

    @property
    def kind(self) -> str:
        return 'click'

    def to_dict(self) -> dict:
        return {
            'event_id': self.event_id,
            'kind': self.kind,
            'ts_press': self.ts_press,
            'ts_release': self.ts_release,
            'panel': self.panel,
            'x_raw': self.x_raw,
            'y_raw': self.y_raw,
            'x': self.x,
            'y': self.y,
        }


@dataclass
class SwipeEvent(TouchEvent):
    """一次滑动（按下与抬起位置有明显位移）"""
    start_x_raw: int = -1
    start_y_raw: int = -1
    end_x_raw: int = -1
    end_y_raw: int = -1
    start_x: float = -1.0
    start_y: float = -1.0
    end_x: float = -1.0
    end_y: float = -1.0
    path: list = field(default_factory=list)  # 轨迹采样 [[x, y], ...]（1280x720 逻辑坐标）

    @property
    def kind(self) -> str:
        return 'swipe'

    @property
    def duration(self) -> float:
        return round(max(0.0, self.ts_release - self.ts_press), 3)

    @property
    def distance(self) -> float:
        dx, dy = self.end_x - self.start_x, self.end_y - self.start_y
        return round((dx * dx + dy * dy) ** 0.5, 1)

    def to_dict(self) -> dict:
        return {
            'event_id': self.event_id,
            'kind': self.kind,
            'ts_press': self.ts_press,
            'ts_release': self.ts_release,
            'duration': self.duration,
            'panel': self.panel,
            'start_x_raw': self.start_x_raw,
            'start_y_raw': self.start_y_raw,
            'end_x_raw': self.end_x_raw,
            'end_y_raw': self.end_y_raw,
            'start_x': self.start_x,
            'start_y': self.start_y,
            'end_x': self.end_x,
            'end_y': self.end_y,
            'distance': self.distance,
            'path': self.path,
        }


@dataclass
class SceneChangeEvent:
    """画面显著变化事件（帧差超阈值，节流上报）"""
    ts: float
    diff: float

    def to_dict(self) -> dict:
        return {'frame_ts': self.ts, 'diff': round(self.diff, 3)}


@dataclass
class PageChangeEvent:
    """页面切换事件（PageDetector 识别）"""
    ts: float
    page_before: str
    page_after: str

    def to_dict(self) -> dict:
        return {
            'page_before': self.page_before,
            'page_after': self.page_after,
        }
