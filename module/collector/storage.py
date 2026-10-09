import json
import time
from pathlib import Path

import cv2
import numpy as np

from module.collector.models import ClickEvent
from module.logger import logger


class SessionStore:
    """采集数据落盘：
    ./log/collector/<session_ts>/
        events.jsonl            事件流（click / scene_change / page_change）
        clicks/<event_id>/      每次点击的截图与元数据
    """

    def __init__(self, base: str = './log/collector'):
        self.base = Path(base)
        self.session_dir: Path = None
        self._events_file = None

    def open_session(self):
        session = time.strftime('%Y%m%d_%H%M%S')
        self.session_dir = self.base / session
        (self.session_dir / 'clicks').mkdir(parents=True, exist_ok=True)
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
        row = {'type': event_type, 'ts': time.time(), **data}
        self._events_file.write(json.dumps(row, ensure_ascii=False) + '\n')
        self._events_file.flush()

    @staticmethod
    def _save_image(image: np.ndarray, path: Path):
        # 截图为 RGB ndarray，opencv 以 BGR 落盘
        cv2.imwrite(str(path), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))

    def save_click(self, click: ClickEvent, before: tuple, after_frames: list, meta: dict) -> str:
        """
        Args:
            before: (ts, image) 点击前画面
            after_frames: [(ts, image), ...] 点击后多帧
            meta: 额外元数据（page_before / page_after / early_stop 等）

        Returns:
            str: event_id
        """
        click_dir = self.session_dir / 'clicks' / click.event_id
        click_dir.mkdir(parents=True, exist_ok=True)
        self._save_image(before[1], click_dir / 'before.png')
        after_ts = []
        for i, (ts, image) in enumerate(after_frames):
            self._save_image(image, click_dir / f'after_{i:02d}.png')
            after_ts.append(ts)
        record = {
            **click.to_dict(),
            'before_ts': before[0],
            'before_age_ms': round((click.ts_press - before[0]) * 1000, 1),
            'after_ts': after_ts,
            **meta,
        }
        with open(click_dir / 'meta.json', 'w', encoding='utf-8') as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        self.append_event('click', record)
        return click.event_id
