import queue
import re
import socket
import threading
import time

from module.collector.models import ClickEvent
from module.logger import logger

# getevent -lt 输出行示例：
# [  12345.678901] /dev/input/event4: EV_ABS       ABS_MT_POSITION_X    000002ab
# [  12345.678901] /dev/input/event4: EV_KEY       BTN_TOUCH            DOWN
LINE_RE = re.compile(
    r'^\[\s*(?P<ts>[\d.]+)\]\s+(?P<dev>\S+):\s+EV_(?P<etype>\w+)\s+(?P<code>\S+)\s+(?P<value>\S+)'
)

# getevent -lp 输出中触摸设备的坐标量程：
#   ABS_MT_POSITION_X    : value 0, min 0, max 32767, fuzz 0, flat 0, resolution 0
CAPACITY_RE = re.compile(r'ABS_MT_POSITION_(?P<axis>[XY])\s*:.*max\s+(\d+)')
SINGLE_CAPACITY_RE = re.compile(r'\sABS_(?P<axis>[XY])\s*:.*max\s+(\d+)')
DEVICE_RE = re.compile(r'add device \d+: (\S+)')


class GeteventListener(threading.Thread):
    """监听 Android 触摸输入事件流（adb shell getevent -lt），按下即产出 ClickEvent"""

    RECONNECT_BACKOFF = 3.0

    def __init__(self, device, event_queue: queue.Queue, stop_event: threading.Event, screen_size=(1280, 720)):
        super().__init__(daemon=True, name='GeteventListener')
        self.device = device
        self.event_queue = event_queue
        self.stop_event = stop_event
        self.screen_size = screen_size
        self.epoch = None        # 设备 uptime 与本地时间的换算基准
        self.panels = []         # 触摸设备路径列表
        self.max_x = None
        self.max_y = None
        self._x_raw = -1
        self._y_raw = -1
        self._tracking_id = -1    # ABS_MT_TRACKING_ID，-1 为无触摸
        self._btn_touch = False
        self._frame_press = False
        self._frame_release = False
        self._conn = None

    # ---------------- 标定 ----------------

    def calibrate(self):
        """换算时间基准，并从 getevent -lp 解析触摸设备与坐标量程"""
        try:
            uptime = float(str(self.device.adb_shell(['cat', '/proc/uptime'])).split()[0])
            self.epoch = time.time() - uptime
        except Exception as e:
            logger.warning(f'Collector uptime calibrate failed ({e}), fall back to local clock')
            self.epoch = time.time()

        raw = self.device.adb_command(['shell', 'getevent', '-lp'])
        text = raw.decode(errors='ignore') if isinstance(raw, bytes) else str(raw)
        panels, max_x, max_y = [], None, None
        single_x, single_y = None, None
        current_panel = None
        for line in text.splitlines():
            m = DEVICE_RE.match(line)
            if m:
                current_panel = m.group(1)
                continue
            m = CAPACITY_RE.search(line)
            if m and current_panel:
                if current_panel not in panels:
                    panels.append(current_panel)
                if m.group('axis') == 'X':
                    max_x = int(m.group(2))
                else:
                    max_y = int(m.group(2))
                continue
            # 单点触控设备的兜底（无多点的触摸面板）
            m = SINGLE_CAPACITY_RE.search(line)
            if m and current_panel:
                if m.group('axis') == 'X':
                    single_x = int(m.group(2))
                else:
                    single_y = int(m.group(2))
        if not panels and single_x is not None and current_panel:
            panels = [current_panel]
            max_x, max_y = single_x, single_y
        self.panels = panels
        self.max_x, self.max_y = max_x, max_y
        # 竖屏触摸面板（如 720x1280）配横屏屏幕（1280x720）：
        # 面板相对屏幕逆时针旋转 90°（MuMu 实测），需交换 XY 并翻转 Y
        self.swap_xy = bool(self.max_x and self.max_y and self.max_x < self.max_y)
        self.flip_y = self.swap_xy
        logger.attr('TouchPanels', ', '.join(panels) if panels else 'unknown (listen all)')
        logger.attr('PanelMaxXY', f'{max_x} x {max_y}' + (' (swap xy, flip y)' if self.swap_xy else ''))

    def _to_local_ts(self, uptime_ts: float) -> float:
        if self.epoch is not None:
            return self.epoch + uptime_ts
        return time.time()

    def _scale(self, x_raw: int, y_raw: int):
        if self.swap_xy:
            x_raw, y_raw = y_raw, x_raw
            x_max, y_max = self.max_y, self.max_x
        else:
            x_max, y_max = self.max_x, self.max_y
        x = round(x_raw / x_max * self.screen_size[0], 1) if x_max else float(x_raw)
        y = round(y_raw / y_max * self.screen_size[1], 1) if y_max else float(y_raw)
        if self.flip_y:
            y = round(self.screen_size[1] - y, 1)
        return x, y

    # ---------------- 事件流 ----------------

    def close(self):
        """关闭流式 socket，解除 recv 阻塞"""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.calibrate()
                self._listen()
            except Exception as e:
                if self.stop_event.is_set():
                    break
                logger.warning(f'Getevent stream error: {e}, reconnect in {self.RECONNECT_BACKOFF}s')
                self.close()
                self.stop_event.wait(self.RECONNECT_BACKOFF)
        self.close()

    def _listen(self):
        self._conn = self.device.adb_shell(['getevent', '-lt'], stream=True, recvall=False, timeout=None)
        sock = self._conn.conn
        # 周期性醒转以检查停止信号
        sock.settimeout(1.0)
        logger.info('Getevent stream listening')
        buf = b''
        while not self.stop_event.is_set():
            try:
                chunk = sock.recv(4096)
            except (socket.timeout, TimeoutError):
                continue
            if not chunk:
                raise ConnectionResetError('getevent stream closed')
            buf += chunk
            *lines, buf = buf.split(b'\n')
            for raw_line in lines:
                click = self._parse_line(raw_line.decode(errors='ignore'))
                if click is not None:
                    self.event_queue.put_nowait(click)

    def _parse_line(self, line: str) -> ClickEvent:
        """解析一行事件；在 SYN_REPORT 帧边界判定触摸按下/抬起，按下时返回 ClickEvent

        兼容两种协议：
        - MuMu 等模拟器：ABS_MT_TRACKING_ID >= 0 为按下，ffffffff(-1) 为抬起，无 BTN_TOUCH
        - 真机常见协议：BTN_TOUCH DOWN/UP
        坐标事件先于 SYN_REPORT 到达，因此统一在帧边界发射，确保 X/Y 已到齐。
        """
        m = LINE_RE.match(line)
        if not m:
            return None
        if self.panels and m['dev'] not in self.panels:
            return None
        etype, code, value = m['etype'], m['code'], m['value']

        if etype == 'ABS':
            if code == 'ABS_MT_POSITION_X':
                self._x_raw = int(value, 16)
            elif code == 'ABS_MT_POSITION_Y':
                self._y_raw = int(value, 16)
            elif code == 'ABS_MT_TRACKING_ID':
                tid = -1 if value == 'ffffffff' else int(value, 16)
                if tid >= 0 and self._tracking_id < 0:
                    self._frame_press = True
                elif tid < 0 and self._tracking_id >= 0:
                    self._frame_release = True
                self._tracking_id = tid
        elif etype == 'KEY' and code == 'BTN_TOUCH':
            down = value in ('DOWN', '00000001')
            if down and not self._btn_touch:
                self._frame_press = True
            elif not down and self._btn_touch:
                self._frame_release = True
            self._btn_touch = down
        elif etype == 'SYN' and code == 'SYN_REPORT':
            event = None
            if self._frame_press:
                ts = self._to_local_ts(float(m['ts']))
                x, y = self._scale(self._x_raw, self._y_raw)
                event = ClickEvent(ts_press=ts, panel=m['dev'], x_raw=self._x_raw, y_raw=self._y_raw, x=x, y=y)
            elif self._frame_release:
                self._x_raw, self._y_raw = -1, -1
            self._frame_press = False
            self._frame_release = False
            return event
        return None
