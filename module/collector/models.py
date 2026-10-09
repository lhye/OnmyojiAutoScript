import time
from dataclasses import dataclass


@dataclass
class ClickEvent:
    """一次触摸按下事件（由 getevent 流捕获）"""
    ts_press: float          # 按下时间戳（本地 epoch 秒）
    ts_release: float = 0.0  # 释放时间戳，0 表示未捕获释放
    panel: str = ''          # 触摸设备路径，如 /dev/input/event4
    x_raw: int = -1          # 触摸面板原始坐标
    y_raw: int = -1
    x: float = -1.0          # 换算到 1280x720 的逻辑坐标
    y: float = -1.0

    @property
    def event_id(self) -> str:
        local = time.localtime(self.ts_press)
        return time.strftime('%Y%m%d_%H%M%S', local) + f'_{int(self.ts_press * 1000) % 1000:03d}'

    def to_dict(self) -> dict:
        return {
            'event_id': self.event_id,
            'ts_press': self.ts_press,
            'ts_release': self.ts_release,
            'panel': self.panel,
            'x_raw': self.x_raw,
            'y_raw': self.y_raw,
            'x': self.x,
            'y': self.y,
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
