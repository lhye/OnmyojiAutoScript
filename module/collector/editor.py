"""采集序列标注编辑器

读取 ./log/collector/<session>/ 下的 events.jsonl，按时间顺序展示点击 / 滑动步骤，
为每一步填写语义说明，输出可供 AI 生成自动化脚本的 sequence.json / sequence.md。
"""

import json
import math
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction, QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

KIND_LABEL = {'click': '点击', 'swipe': '滑动'}
IMAGE_FOLDER = {'click': 'clicks', 'swipe': 'swipes'}


def swipe_direction(dx: float, dy: float) -> str:
    """把位移换算成 8 方向描述"""
    if abs(dx) >= 2 * abs(dy):
        return '右' if dx > 0 else '左'
    if abs(dy) >= 2 * abs(dx):
        return '下' if dy > 0 else '上'
    if dx > 0:
        return '右下' if dy > 0 else '右上'
    return '左下' if dy > 0 else '左上'


def load_session(path: Path) -> 'SessionData':
    return SessionData(path)


class SessionData:
    def __init__(self, path: Path):
        self.path = path
        self.steps: list[dict] = []
        self.annotations: dict[str, dict] = {}
        self._load_events()
        self._load_annotations()

    def _load_events(self):
        file = self.path / 'events.jsonl'
        if not file.exists():
            return
        steps = []
        with open(file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get('type') in KIND_LABEL:
                    row.setdefault('kind', row['type'])  # 兼容旧版本无 kind 字段的会话
                    steps.append(row)
        # 采集线程按动作完成顺序落盘，这里按按下时间还原真实操作顺序
        steps.sort(key=lambda r: (r.get('ts_press', r.get('ts', 0)), r.get('seq', 0)))
        self.steps = steps

    def _load_annotations(self):
        file = self.path / 'annotations.json'
        if not file.exists():
            return
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.annotations = data.get('items', {})
        except (json.JSONDecodeError, OSError):
            self.annotations = {}

    def semantic(self, event_id: str) -> str:
        return (self.annotations.get(event_id) or {}).get('semantic', '')

    def set_semantic(self, event_id: str, text: str):
        self.annotations.setdefault(event_id, {})['semantic'] = text
        self.annotations[event_id]['updated'] = time.time()

    def page(self, step: dict) -> str:
        """步骤页面：优先使用手动标注，其次采集时自动识别的动作前页面"""
        manual = (self.annotations.get(step['event_id']) or {}).get('page', '').strip()
        return manual or step.get('page_before', 'unknown')

    def set_page(self, event_id: str, text: str):
        text = text.strip()
        if text and text != 'unknown':
            self.annotations.setdefault(event_id, {})['page'] = text
        else:
            self.annotations.setdefault(event_id, {}).pop('page', None)
        self.annotations[event_id]['updated'] = time.time()

    def save_annotations(self):
        payload = {'version': 1, 'session': self.path.name, 'items': self.annotations}
        file = self.path / 'annotations.json'
        tmp = file.with_suffix('.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp.replace(file)

    def event_dir(self, step: dict) -> Path:
        return self.path / IMAGE_FOLDER.get(step['kind'], 'clicks') / step['event_id']

    def before_image(self, step: dict) -> Path:
        return self.event_dir(step) / 'before.png'

    def after_images(self, step: dict) -> list[Path]:
        return sorted(self.event_dir(step).glob('after_*.png'))

    def after_image(self, step: dict) -> Path:
        folder = self.event_dir(step)
        candidates = sorted(folder.glob('after_*.png'))
        return candidates[-1] if candidates else folder / 'before.png'


class PreviewWidget(QWidget):
    """显示动作前画面，叠加点击点 / 滑动轨迹，并实时显示鼠标所在位置的逻辑坐标"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self._pixmap: QPixmap | None = None
        self._step: dict | None = None
        self._placeholder = '暂无画面'
        self._hover: QPointF | None = None
        self._image_rect = (0.0, 0.0, 0.0, 0.0)
        self._img_w = 1280
        self._img_h = 720

    def set_preview(self, image_path: Path | None, step: dict | None):
        self._step = step
        self._pixmap = QPixmap(str(image_path)) if image_path and image_path.exists() else None
        if self._pixmap is not None and not self._pixmap.isNull():
            self._img_w, self._img_h = self._pixmap.width(), self._pixmap.height()
        self.update()

    def mouseMoveEvent(self, event):
        self._hover = event.position()
        self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(28, 30, 34))
        if self._pixmap is None or self._pixmap.isNull():
            painter.setPen(QColor(150, 150, 150))
            painter.drawText(self.rect(), Qt.AlignCenter, self._placeholder)
            return

        scaled = self._pixmap.size().scaled(self.size(), Qt.KeepAspectRatio)
        x = (self.width() - scaled.width()) / 2
        y = (self.height() - scaled.height()) / 2
        self._image_rect = (x, y, scaled.width(), scaled.height())
        painter.drawPixmap(int(x), int(y), scaled.width(), scaled.height(), self._pixmap)
        if self._step is not None:
            self._draw_marker(painter, x, y, scaled.width(), scaled.height())
        self._draw_hover(painter, x, y, scaled.width(), scaled.height())

    def _to_widget(self, x: float, y: float, ox, oy, w, h):
        return QPointF(ox + x / self._img_w * w, oy + y / self._img_h * h)

    def _draw_hover(self, painter: QPainter, ox, oy, w, h):
        """鼠标位置的十字线与 1280x720 逻辑坐标读数"""
        pos = self._hover
        if pos is None or w <= 0 or h <= 0:
            return
        if not (ox <= pos.x() <= ox + w and oy <= pos.y() <= oy + h):
            return
        lx = min(max((pos.x() - ox) / w * self._img_w, 0), self._img_w)
        ly = min(max((pos.y() - oy) / h * self._img_h, 0), self._img_h)
        painter.setPen(QPen(QColor(255, 235, 59, 180), 1, Qt.DashLine))
        painter.drawLine(QPointF(ox, pos.y()), QPointF(ox + w, pos.y()))
        painter.drawLine(QPointF(pos.x(), oy), QPointF(pos.x(), oy + h))

        text = f'x {lx:.0f}  y {ly:.0f}'
        painter.setFont(QFont('Microsoft YaHei', 10))
        metrics = QFontMetrics(painter.font())
        tw = metrics.horizontalAdvance(text)
        th = metrics.height()
        left = pos.x() + 12
        top = pos.y() + 12
        if left + tw + 12 > ox + w:
            left = pos.x() - tw - 22
        if top + th + 10 > oy + h:
            top = pos.y() - th - 20
        painter.fillRect(QRectF(left - 5, top - 3, tw + 10, th + 6), QColor(0, 0, 0, 170))
        painter.setPen(QColor(255, 235, 59))
        painter.drawText(QPointF(left, top + metrics.ascent()), text)

    def _draw_marker(self, painter: QPainter, ox, oy, w, h):
        step = self._step
        painter.setFont(QFont('Microsoft YaHei', 10))
        if step['kind'] == 'click':
            p = self._to_widget(step['x'], step['y'], ox, oy, w, h)
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.setBrush(QColor(255, 82, 82, 220))
            painter.drawEllipse(p, 11, 11)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(p, 18, 18)
            painter.drawLine(QPointF(p.x() - 26, p.y()), QPointF(p.x() - 14, p.y()))
            painter.drawLine(QPointF(p.x() + 14, p.y()), QPointF(p.x() + 26, p.y()))
            painter.drawLine(QPointF(p.x(), p.y() - 26), QPointF(p.x(), p.y() - 14))
            painter.drawLine(QPointF(p.x(), p.y() + 14), QPointF(p.x(), p.y() + 26))
            self._draw_text(painter, p, QPointF(p.x() + 24, p.y() - 18),
                            f"({step['x']:.0f}, {step['y']:.0f})")
        else:
            start = self._to_widget(step['start_x'], step['start_y'], ox, oy, w, h)
            end = self._to_widget(step['end_x'], step['end_y'], ox, oy, w, h)
            path = step.get('path') or []
            if len(path) > 2:
                painter.setPen(QPen(QColor(33, 150, 243, 150), 2, Qt.DashLine))
                points = [self._to_widget(px, py, ox, oy, w, h) for px, py in path]
                painter.drawPolyline(QPolygonF(points))
            painter.setPen(QPen(QColor(255, 87, 34), 4, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(start, end)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(76, 175, 80, 230))
            painter.drawEllipse(start, 9, 9)
            painter.setBrush(QColor(255, 87, 34, 230))
            painter.drawEllipse(end, 9, 9)
            self._draw_arrow_head(painter, start, end)
            dx, dy = step['end_x'] - step['start_x'], step['end_y'] - step['start_y']
            label = f"{swipe_direction(dx, dy)}  {step.get('duration', 0):.2f}s"
            self._draw_text(painter, end, QPointF(end.x() + 16, end.y() - 16), label)

    @staticmethod
    def _draw_arrow_head(painter: QPainter, start: QPointF, end: QPointF):
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        size = 16
        left = QPointF(end.x() - size * math.cos(angle - 0.4), end.y() - size * math.sin(angle - 0.4))
        right = QPointF(end.x() - size * math.cos(angle + 0.4), end.y() - size * math.sin(angle + 0.4))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 87, 34))
        painter.drawPolygon(QPolygonF([end, left, right]))

    @staticmethod
    def _draw_text(painter: QPainter, anchor: QPointF, pos: QPointF, text: str):
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(pos, text)


class EditorWindow(QMainWindow):
    def __init__(self, base: str = './log/collector', session: str | None = None):
        super().__init__()
        self.base = Path(base)
        self.session: SessionData | None = None
        self.current_index: int | None = None
        self._dirty = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._flush_annotations)

        self.setWindowTitle('OAS 采集序列标注编辑器')
        self.resize(1280, 800)
        self._build_ui()
        self.reload_sessions(select=session)

    # ---------------- UI ----------------

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('采集会话'))
        self.session_combo = QComboBox()
        self.session_combo.setMinimumWidth(260)
        self.session_combo.currentIndexChanged.connect(self._on_session_changed)
        toolbar.addWidget(self.session_combo)
        refresh_btn = QPushButton('刷新')
        refresh_btn.clicked.connect(lambda: self.reload_sessions())
        toolbar.addWidget(refresh_btn)

        toolbar.addSpacing(16)
        toolbar.addWidget(QLabel('筛选'))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(['全部', '未标注', '只看点击', '只看滑动'])
        self.filter_combo.currentIndexChanged.connect(self._rebuild_list)
        toolbar.addWidget(self.filter_combo)
        toolbar.addStretch(1)

        export_json_btn = QPushButton('导出 sequence.json')
        export_json_btn.clicked.connect(self.export_json)
        toolbar.addWidget(export_json_btn)
        export_md_btn = QPushButton('导出 sequence.md')
        export_md_btn.clicked.connect(self.export_markdown)
        toolbar.addWidget(export_md_btn)
        root.addLayout(toolbar)

        save_action = QAction('保存标注', self)
        save_action.setShortcut('Ctrl+S')
        save_action.triggered.connect(self._flush_annotations)
        self.addAction(save_action)

        splitter = QSplitter(Qt.Horizontal)

        self.step_list = QListWidget()
        self.step_list.setIconSize(QSize(128, 72))
        self.step_list.setUniformItemSizes(True)
        self.step_list.setStyleSheet('QListWidget::item { padding: 4px; }')
        self.step_list.currentRowChanged.connect(self._on_row_changed)
        splitter.addWidget(self.step_list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)

        self.title_label = QLabel('未选择步骤')
        self.title_label.setStyleSheet('font-size: 18px; font-weight: bold;')
        right_layout.addWidget(self.title_label)

        previews = QHBoxLayout()
        self.before_view = PreviewWidget()
        self.after_view = PreviewWidget()
        before_box = QGroupBox('动作前（标记点击点 / 滑动方向）')
        QVBoxLayout(before_box).addWidget(self.before_view)
        after_box = QGroupBox('动作后')
        after_layout = QVBoxLayout(after_box)
        after_layout.addWidget(self.after_view)
        self.after_combo = QComboBox()
        self.after_combo.setToolTip('动作后补拍的多帧，可切换查看（滑动默认显示动作结束瞬间，点击默认显示最后一帧）')
        self.after_combo.currentIndexChanged.connect(self._on_after_frame_changed)
        self.after_combo.setVisible(False)
        after_layout.addWidget(self.after_combo)
        previews.addWidget(before_box, 3)
        previews.addWidget(after_box, 2)
        right_layout.addLayout(previews, 3)

        self.detail_label = QLabel('')
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right_layout.addWidget(self.detail_label)

        page_row = QHBoxLayout()
        page_row.addWidget(QLabel('页面'))
        self.page_combo = QComboBox()
        self.page_combo.setEditable(True)
        self.page_combo.setInsertPolicy(QComboBox.NoInsert)
        self.page_combo.setMinimumWidth(240)
        self.page_combo.lineEdit().setPlaceholderText('自动识别不出时可手动填写，如 page_realm_raid')
        self.page_combo.currentTextChanged.connect(self._on_page_changed)
        page_row.addWidget(self.page_combo, 1)
        right_layout.addLayout(page_row)

        semantic_box = QGroupBox('语义说明（给 AI 的步骤描述，例如：点击挑战按钮进入战斗准备）')
        semantic_layout = QVBoxLayout(semantic_box)
        self.semantic_edit = QPlainTextEdit()
        self.semantic_edit.setPlaceholderText('在这里描述这一步在做什么、期望发生什么……（自动保存）')
        self.semantic_edit.setMinimumHeight(90)
        self.semantic_edit.textChanged.connect(self._on_semantic_changed)
        semantic_layout.addWidget(self.semantic_edit)
        right_layout.addWidget(semantic_box, 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([440, 840])
        root.addWidget(splitter, 1)

        self.setCentralWidget(central)
        self.status = self.statusBar()
        self._set_detail_enabled(False)

    def _set_detail_enabled(self, enabled: bool):
        self.before_view.setEnabled(enabled)
        self.after_view.setEnabled(enabled)
        self.semantic_edit.setEnabled(enabled)
        self.page_combo.setEnabled(enabled)

    # ---------------- 会话 ----------------

    def reload_sessions(self, select: str | None = None):
        current = select or (self.session.path.name if self.session else None)
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        names = []
        if self.base.exists():
            names = sorted(
                (p.name for p in self.base.iterdir()
                 if p.is_dir() and (p / 'events.jsonl').exists()),
                reverse=True,
            )
        self.session_combo.addItems(names)
        if names:
            index = names.index(current) if current in names else 0
            self.session_combo.setCurrentIndex(index)
        self.session_combo.blockSignals(False)
        self._on_session_changed()

    def _on_session_changed(self):
        self._flush_annotations()
        name = self.session_combo.currentText()
        if not name:
            self.session = None
            self.step_list.clear()
            self.title_label.setText('未找到采集会话')
            self.status.showMessage('请先运行 python collector.py 采集数据')
            return
        self.session = load_session(self.base / name)
        self.current_index = None
        self._after_paths: list[Path] = []
        self._populate_pages()
        self._rebuild_list()
        if self.step_list.count():
            self.step_list.setCurrentRow(0)
        else:
            self.title_label.setText('该会话没有点击 / 滑动事件')

    def _rebuild_list(self):
        if self.session is None:
            return
        mode = self.filter_combo.currentText()
        self.step_list.blockSignals(True)
        self.step_list.clear()
        for index, step in enumerate(self.session.steps):
            annotated = bool(self.session.semantic(step['event_id']).strip())
            if mode == '未标注' and annotated:
                continue
            if mode == '只看点击' and step['kind'] != 'click':
                continue
            if mode == '只看滑动' and step['kind'] != 'swipe':
                continue
            item = QListWidgetItem(self._item_text(index, step))
            item.setData(Qt.UserRole, index)
            item.setSizeHint(QSize(0, 84))
            icon_path = self.session.before_image(step)
            if icon_path.exists():
                item.setIcon(QIcon(str(icon_path)))
            self.step_list.addItem(item)
        self.step_list.blockSignals(False)
        # 筛选后尽量保持当前步骤的选中状态
        target_row = -1
        for row in range(self.step_list.count()):
            if self.step_list.item(row).data(Qt.UserRole) == self.current_index:
                target_row = row
                break
        if target_row < 0 and self.step_list.count():
            target_row = 0
        self.step_list.setCurrentRow(target_row)
        self._update_status()

    def _item_text(self, index: int, step: dict) -> str:
        semantic = self.session.semantic(step['event_id']).strip()
        if step['kind'] == 'click':
            action = f"点击  ({step['x']:.0f}, {step['y']:.0f})"
        else:
            dx, dy = step['end_x'] - step['start_x'], step['end_y'] - step['start_y']
            action = (f"滑动{swipe_direction(dx, dy)}  "
                      f"({step['start_x']:.0f},{step['start_y']:.0f}) → "
                      f"({step['end_x']:.0f},{step['end_y']:.0f})")
        manual = self.session.page(step)
        if manual != step.get('page_before', 'unknown'):
            page = f'{manual}（手动）'
        else:
            page = f"{step.get('page_before', '?')} → {step.get('page_after', '?')}"
        tail = semantic[:26] if semantic else '（未标注）'
        return f'#{index + 1:02d}  {action}\n{page} · {tail}'

    def _on_row_changed(self, row: int):
        self._flush_annotations()
        if self.session is None or row < 0:
            return
        item = self.step_list.item(row)
        index = item.data(Qt.UserRole)
        self.current_index = index
        step = self.session.steps[index]
        self._set_detail_enabled(True)
        self.before_view.set_preview(self.session.before_image(step), step)
        # 动作后为多帧：滑动默认看结束瞬间，点击默认看最后一帧，可在下拉框切换
        self._after_paths = self.session.after_images(step)
        base_ts = step.get('ts_release', step.get('ts_press', step.get('ts', 0)))
        after_ts = step.get('after_ts') or []
        self.after_combo.blockSignals(True)
        self.after_combo.clear()
        for i in range(len(self._after_paths)):
            offset = after_ts[i] - base_ts if i < len(after_ts) else 0.0
            self.after_combo.addItem(
                f'第 {i + 1}/{len(self._after_paths)} 帧  +{offset:.1f}s', i
            )
        default = 0 if step['kind'] == 'swipe' else max(len(self._after_paths) - 1, 0)
        self.after_combo.setCurrentIndex(default)
        self.after_combo.blockSignals(False)
        self.after_combo.setVisible(len(self._after_paths) > 1)
        self._update_after_view()
        self.title_label.setText(f"#{index + 1:02d}  {KIND_LABEL[step['kind']]}")
        self.detail_label.setText(self._detail_text(step))
        self.semantic_edit.blockSignals(True)
        self.semantic_edit.setPlainText(self.session.semantic(step['event_id']))
        self.semantic_edit.blockSignals(False)
        self.page_combo.blockSignals(True)
        self.page_combo.setCurrentText(self.session.page(step))
        self.page_combo.blockSignals(False)

    def _populate_pages(self):
        """下拉框候选：本会话中出现过的页面 + 已手动填写的页面"""
        names = set()
        for step in self.session.steps:
            for key in ('page_before', 'page_after'):
                name = step.get(key)
                if name and name != 'unknown':
                    names.add(name)
            manual = (self.session.annotations.get(step['event_id']) or {}).get('page', '')
            if manual:
                names.add(manual)
        current = self.page_combo.currentText()
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        self.page_combo.addItems(sorted(names))
        self.page_combo.setCurrentText(current)
        self.page_combo.blockSignals(False)

    def _on_page_changed(self, text: str):
        if self.session is None or self.current_index is None:
            return
        step = self.session.steps[self.current_index]
        self.session.set_page(step['event_id'], text)
        self._dirty = True
        self._save_timer.start(700)
        self._refresh_current_item()

    def _update_after_view(self):
        if not self._after_paths:
            return
        index = self.after_combo.currentIndex()
        index = index if 0 <= index < len(self._after_paths) else 0
        self.after_view.set_preview(self._after_paths[index], None)

    def _on_after_frame_changed(self, _index: int):
        self._update_after_view()

    @staticmethod
    def _timing_text(step: dict) -> str:
        parts = []
        age_ms = step.get('before_age_ms')
        if age_ms is not None:
            stale = '（偏旧，画面可能不是紧邻动作前）' if age_ms > 1500 else ''
            parts.append(f'动作前帧距动作 {age_ms / 1000:.1f}s{stale}')
        after_ts = step.get('after_ts') or []
        if after_ts:
            end = step.get('ts_release', step.get('ts_press', after_ts[0]))
            parts.append(f'动作后 {len(after_ts)} 帧，末帧 +{max(after_ts[-1] - end, 0):.1f}s')
        return ('    ' + '    '.join(parts)) if parts else ''

    @staticmethod
    def _detail_text(step: dict) -> str:
        page = f"页面：{step.get('page_before', '?')} → {step.get('page_after', '?')}"
        timing = EditorWindow._timing_text(step)
        ts = time.strftime('%H:%M:%S', time.localtime(step.get('ts_press', step.get('ts', 0))))
        if step['kind'] == 'click':
            return f"时间 {ts}    坐标 ({step['x']:.0f}, {step['y']:.0f})    {page}{timing}"
        dx, dy = step['end_x'] - step['start_x'], step['end_y'] - step['start_y']
        return (f"时间 {ts}    起点 ({step['start_x']:.0f}, {step['start_y']:.0f}) → "
                f"终点 ({step['end_x']:.0f}, {step['end_y']:.0f})    "
                f"方向 {swipe_direction(dx, dy)}    "
                f"时长 {step.get('duration', 0):.2f}s    距离 {step.get('distance', 0):.0f}px    {page}{timing}")

    # ---------------- 标注 ----------------

    def _on_semantic_changed(self):
        if self.session is None or self.current_index is None:
            return
        step = self.session.steps[self.current_index]
        self.session.set_semantic(step['event_id'], self.semantic_edit.toPlainText())
        self._dirty = True
        self._save_timer.start(700)
        self._refresh_current_item()

    def _refresh_current_item(self):
        if self.current_index is None:
            return
        for row in range(self.step_list.count()):
            item = self.step_list.item(row)
            if item.data(Qt.UserRole) == self.current_index:
                item.setText(self._item_text(self.current_index, self.session.steps[self.current_index]))
                break
        self._update_status()

    def _flush_annotations(self):
        if self._dirty and self.session is not None:
            try:
                self.session.save_annotations()
                self._dirty = False
                self.status.showMessage(f'已保存 {self.session.path / "annotations.json"}', 3000)
            except OSError as e:
                self.status.showMessage(f'保存失败：{e}', 5000)

    def _update_status(self):
        if self.session is None:
            return
        total = len(self.session.steps)
        clicks = sum(1 for s in self.session.steps if s['kind'] == 'click')
        swipes = total - clicks
        annotated = sum(1 for s in self.session.steps if self.session.semantic(s['event_id']).strip())
        self.status.showMessage(
            f'共 {total} 步（点击 {clicks} / 滑动 {swipes}）    已标注 {annotated}/{total}'
        )

    def closeEvent(self, event):
        self._save_timer.stop()
        self._flush_annotations()
        super().closeEvent(event)

    # ---------------- 导出 ----------------

    def _export_steps(self) -> list[dict]:
        steps = []
        for index, step in enumerate(self.session.steps):
            semantic = self.session.semantic(step['event_id']).strip()
            item = {
                'index': index + 1,
                'type': step['kind'],
                'event_id': step['event_id'],
                'time': time.strftime('%H:%M:%S', time.localtime(step.get('ts_press', step.get('ts', 0)))),
                'page': self.session.page(step),
                'page_before': step.get('page_before', ''),
                'page_after': step.get('page_after', ''),
                'semantic': semantic,
                'before_image': self.session.before_image(step).relative_to(self.session.path).as_posix(),
                'after_image': self.session.after_image(step).relative_to(self.session.path).as_posix(),
            }
            if step['kind'] == 'click':
                item.update({'x': step['x'], 'y': step['y']})
            else:
                dx, dy = step['end_x'] - step['start_x'], step['end_y'] - step['start_y']
                item.update({
                    'start': [step['start_x'], step['start_y']],
                    'end': [step['end_x'], step['end_y']],
                    'direction': swipe_direction(dx, dy),
                    'duration': step.get('duration', 0),
                    'distance': step.get('distance', 0),
                    'path': step.get('path', []),
                })
            steps.append(item)
        return steps

    def export_json(self):
        if not self._ensure_session():
            return
        steps = self._export_steps()
        payload = {
            'session': self.session.path.name,
            'screen': [1280, 720],
            'coordinate_system': '1280x720 逻辑坐标，原点在左上角；页面名来自采集时的自动识别',
            'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'summary': {
                'total': len(steps),
                'click': sum(1 for s in steps if s['type'] == 'click'),
                'swipe': sum(1 for s in steps if s['type'] == 'swipe'),
                'annotated': sum(1 for s in steps if s['semantic']),
            },
            'steps': steps,
        }
        path = self.session.path / 'sequence.json'
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, '导出完成', f'已导出：\n{path}')

    def export_markdown(self):
        if not self._ensure_session():
            return
        steps = self._export_steps()
        lines = [
            f'# 操作序列 {self.session.path.name}',
            '',
            '- 屏幕：1280x720 逻辑坐标（左上角为原点）',
            f"- 共 {len(steps)} 步，点击 {sum(1 for s in steps if s['type'] == 'click')} 次，"
            f"滑动 {sum(1 for s in steps if s['type'] == 'swipe')} 次",
            '',
        ]
        for step in steps:
            semantic = step['semantic'] or '（未标注）'
            lines.append(f"## {step['index']}. {KIND_LABEL[step['type']]}｜{semantic}")
            lines.append('')
            if step['type'] == 'click':
                lines.append(f"- 坐标：({step['x']:.0f}, {step['y']:.0f})")
            else:
                lines.append(f"- 轨迹：({step['start'][0]:.0f}, {step['start'][1]:.0f}) → "
                             f"({step['end'][0]:.0f}, {step['end'][1]:.0f})，"
                             f"方向 {step['direction']}，时长 {step['duration']:.2f}s")
            lines.append(f"- 页面：{step['page']}")
            lines.append(f"- 画面：`{step['before_image']}`")
            lines.append('')
        path = self.session.path / 'sequence.md'
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        QMessageBox.information(self, '导出完成', f'已导出：\n{path}')

    def _ensure_session(self) -> bool:
        if self.session is None or not self.session.steps:
            QMessageBox.warning(self, '没有数据', '当前会话没有可导出的点击 / 滑动事件')
            return False
        self._save_timer.stop()
        self._flush_annotations()
        return True


def run(base: str = './log/collector', session: str | None = None):
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    window = EditorWindow(base=base, session=session)
    window.show()
    return app.exec()
