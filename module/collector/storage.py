import json
import time
from pathlib import Path

import cv2
import numpy as np

from module.collector.models import TouchEvent
from module.logger import logger

# 事件类型 -> 截图子目录
FOLDER_BY_KIND = {'click': 'clicks', 'swipe': 'swipes'}


class SessionStore:
    """采集数据落盘：
    ./log/collector/<session_ts>/
        events.jsonl            事件流（click / swipe / scene_change / page_change）
        clicks/<event_id>/      每次点击的截图与元数据
        swipes/<event_id>/      每次滑动的截图与元数据
    """

    def __init__(self, base: str = './log/collector'):
        self.base = Path(base)
        self.session_dir: Path = None
        self._events_file = None
        self._seq = 0

    def open_session(self):
        session = time.strftime('%Y%m%d_%H%M%S')
        self.session_dir = self.base / session
        for folder in FOLDER_BY_KIND.values():
            (self.session_dir / folder).mkdir(parents=True, exist_ok=True)
        self._events_file = open(self.session_dir / 'events.jsonl', 'a', encoding='utf-8')
        logger.info(f'Collector session: {self.session_dir}')

    def close_session(self):
        if self._events_file is not None:
            self._events_file.close()
            self._events_file = None

    def append_event(self, event_type: str, data: dict):
        """追加一行事件到 events.jsonl"""
        if self._events_file is None:
            return
        self._seq += 1
        row = {'type': event_type, 'seq': self._seq, 'ts': time.time(), **data}
        self._events_file.write(json.dumps(row, ensure_ascii=False) + '\n')
        self._events_file.flush()

    @staticmethod
    def _save_image(image: np.ndarray, path: Path):
        # 截图为 RGB ndarray，opencv 以 BGR 落盘
        cv2.imwrite(str(path), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))

    def save_touch(self, touch: TouchEvent, before: tuple, after_frames: list, meta: dict) -> str:
        """
        Args:
            touch: ClickEvent 或 SwipeEvent
            before: (ts, image) 动作前画面
            after_frames: [(ts, image), ...] 动作后多帧
            meta: 额外元数据（page_before / page_after / early_stop 等）

        Returns:
            str: event_id
        """
        folder = FOLDER_BY_KIND.get(touch.kind, 'clicks')
        touch_dir = self.session_dir / folder / touch.event_id
        touch_dir.mkdir(parents=True, exist_ok=True)
        self._save_image(before[1], touch_dir / 'before.png')
        after_ts = []
        for i, (ts, image) in enumerate(after_frames):
            self._save_image(image, touch_dir / f'after_{i:02d}.png')
            after_ts.append(ts)
        record = {
            **touch.to_dict(),
            'before_ts': before[0],
            'before_age_ms': round((touch.ts_press - before[0]) * 1000, 1),
            'after_ts': after_ts,
            **meta,
        }
        with open(touch_dir / 'meta.json', 'w', encoding='utf-8') as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        self.append_event(touch.kind, record)
        return touch.event_id
