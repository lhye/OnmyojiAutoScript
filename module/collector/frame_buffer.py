from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Frame:
    ts: float
    image: np.ndarray


class FrameBuffer:
    """滚动帧缓冲：保存最近的截图帧，供"点击前画面"回溯"""

    def __init__(self, maxlen: int = 32):
        self._frames: deque[Frame] = deque(maxlen=maxlen)

    def push(self, ts: float, image: np.ndarray):
        self._frames.append(Frame(ts=ts, image=image))

    def latest(self) -> Frame:
        return self._frames[-1] if self._frames else None

    def nearest_before(self, ts: float) -> Frame:
        """返回 ts 之前（含）最近的一帧；若都晚于 ts，返回最早的一帧"""
        if not self._frames:
            return None
        result = None
        for frame in self._frames:
            if frame.ts <= ts:
                result = frame
            else:
                break
        return result if result is not None else self._frames[0]

    @staticmethod
    def diff(image_a: np.ndarray, image_b: np.ndarray) -> float:
        """灰度化后逐像素差值的均值，作为画面变化程度的度量"""
        if image_a is None or image_b is None:
            return 0.0
        gray_a = cv2.cvtColor(image_a, cv2.COLOR_RGB2GRAY)
        gray_b = cv2.cvtColor(image_b, cv2.COLOR_RGB2GRAY)
        return float(cv2.absdiff(gray_a, gray_b).mean())
