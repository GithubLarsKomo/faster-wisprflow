"""PySide6 dock widget — replaces both overlay.py and popups.py."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import time
from enum import Enum, auto

from PySide6.QtCore import (Property, QEasingCurve, QEvent, QPoint,
                            QPropertyAnimation, QRect, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel,
                               QToolButton, QWidget)

from ui import theme as T
from ui.translations import TRANSLATIONS

# ── Clickable label helper ──────────────────────────────────────────────────


class _ClickableLabel(QLabel):
    """QLabel that emits `clicked` on left-mouse-button release."""

    clicked = Signal()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


# ── Waveform widget ──────────────────────────────────────────────────────────


class _WaveWidget(QWidget):
    """Animated waveform / breathing bars."""

    _BAR_COUNT = 7
    _BAR_W = 3
    _BAR_GAP = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rms: float = 0.0
        self._phase: float = 0.0
        self._recording: bool = False
        total_w = self._BAR_COUNT * (self._BAR_W + self._BAR_GAP) - self._BAR_GAP
        self.setFixedSize(total_w, 32)
        self._tick = QTimer(self)
        self._tick.setInterval(40)
        self._tick.timeout.connect(self._on_tick)
        # Timer only runs during recording — not in idle state

    def set_rms(self, rms: float) -> None:
        self._rms = rms

    def set_recording(self, on: bool) -> None:
        self._recording = on
        if on:
            self._tick.start()
        else:
            self._tick.stop()
            self.update()  # repaint once to static state

    def _on_tick(self) -> None:
        self._phase += 0.12
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        import math

        for i in range(self._BAR_COUNT):
            x = i * (self._BAR_W + self._BAR_GAP)
            if self._recording:
                # RMS-driven with natural phase offset per bar
                amp = max(0.05, min(self._rms * 4.0, 0.95))
                wave = 0.5 + 0.5 * math.sin(self._phase + i * 0.8) * amp
                bar_h = max(4, int(h * wave))
                color = T.REC_RED
            else:
                # Static minimal bars when idle
                bar_h = 4
                color = T.ACCENT
            y = (h - bar_h) // 2
            color_with_alpha = QColor(color)
            p.fillRect(x, y, self._BAR_W, bar_h, color_with_alpha)
        p.end()


# ── Dock state ───────────────────────────────────────────────────────────────


class DockState(Enum):
    STRIP = auto()
    IDLE = auto()
    RECORDING = auto()
    PROCESSING = auto()
    DONE = auto()
    ERROR = auto()


# ── Inner bar widget (painted, animated as child of DockWindow) ─────────────────


class _DockBar(QWidget):
    """
    The visible bar.  Lives inside the transparent fixed-size DockWindow and
    is the ONLY widget that moves/resizes during state transitions.  Because
    it is a *child* widget, Qt handles its geometry changes internally with no
    Win32 SetWindowPos calls, so the animation is perfectly symmetric.
    """

    def paintEvent(self, _event) -> None:  # noqa: N802
        dock: "DockWindow" = self.parent()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        bg_map = {
            DockState.STRIP: T.ACCENT,
            DockState.IDLE: T.DOCK_BG,
            DockState.RECORDING: T.DOCK_BG_REC,
            DockState.PROCESSING: T.DOCK_BG,
            DockState.DONE: T.DOCK_BG_DONE,
            DockState.ERROR: T.DOCK_BG_ERR,
        }
        bg = bg_map.get(dock._state, T.DOCK_BG)
        radius = T.RADIUS if dock._state != DockState.STRIP else 5

        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(
            rect.x(), rect.y(), rect.width(), rect.height(), radius, radius
        )
        p.fillPath(path, bg)

        border_col = {
            DockState.STRIP: T.ACCENT,
            DockState.RECORDING: T.REC_RED,
            DockState.DONE: T.SUCCESS_GREEN,
            DockState.ERROR: T.ERROR_RED,
        }.get(dock._state, T.DOCK_BORDER)
        p.setPen(QPen(border_col, 1))
        p.drawPath(path)
        p.end()


# ── Win32 acrylic / blur-behind ───────────────────────────────────────────────


def _try_acrylic(hwnd: int) -> None:
    """Attempt to enable DWM acrylic blur on Windows 10+."""
    try:

        class _ACCENT(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_int),
            ]

        class _WINCOMP(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_ulong),
            ]

        accent = _ACCENT()
        accent.AccentState = 4  # ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.GradientColor = 0xCC1C1C22  # ARGB
        data = _WINCOMP()
        data.Attribute = 19  # WCA_ACCENT_POLICY
        data.SizeOfData = ctypes.sizeof(accent)
        data.Data = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.pointer(data))
    except Exception:  # noqa: BLE001
        pass


# ── Main dock window ─────────────────────────────────────────────────────────


class DockWindow(QWidget):
    """
    Translucent always-on-top dock at the bottom of the screen.
    Replaces both Overlay (text pill) and _MicLevelPopup (animated dock).
    """

    open_settings_requested = Signal()
    quit_requested = Signal()
    config_saved = Signal()
    show_error_signal = Signal(str)
    show_info_signal = Signal(str, str)  # title, body
    llm_toggled = Signal(bool)  # emitted when the LLM badge is clicked

    def __init__(
        self,
        config,
        on_open_settings=None,
        on_quit=None,
        on_config_saved=None,
        on_llm_toggled=None,
    ) -> None:
        app = QApplication.instance()
        super().__init__(
            None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # Fixed-size transparent outer shell.  The bar is a child widget and
        # is the only thing that animates — no OS window moves during transitions.
        self._bar = _DockBar(self)
        self._setup_outer_geometry()

        self._config = config
        self._state = DockState.IDLE
        self._max_seconds: int = 60
        self._rec_start: float = 0.0
        self._on_timeout_cb = None
        self._dot_count = 0
        self._tr: dict = {}
        self._cur_rect = QRect()
        self._anim: QPropertyAnimation | None = None
        self._animating: bool = False
        self._llm_active: bool = False

        # ── connect optional callbacks to signals ──────────────────────────
        if on_open_settings:
            self.open_settings_requested.connect(on_open_settings)
        if on_quit:
            self.quit_requested.connect(on_quit)
        if on_config_saved:
            self.config_saved.connect(on_config_saved)
        if on_llm_toggled:
            self.llm_toggled.connect(on_llm_toggled)

        self.show_error_signal.connect(self.show_error)
        self.show_info_signal.connect(self._show_info_slot)

        # ── build UI ───────────────────────────────────────────────────────
        self._build_ui()  # builds layout inside self._bar
        self._apply_language(config.get("ui_language", "de"))
        self._goto_state(DockState.IDLE, animated=False)

        # ── hover / leave timers ───────────────────────────────────────────
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(50)
        self._hover_timer.timeout.connect(self._check_hover)
        self._hover_timer.start()

        self._leave_timer = QTimer(self)
        self._leave_timer.setSingleShot(True)
        self._leave_timer.setInterval(T.LEAVE_DELAY_MS)
        self._leave_timer.timeout.connect(self._on_leave_timeout)

        # ── recording timer ────────────────────────────────────────────────
        self._rec_timer = QTimer(self)
        self._rec_timer.setInterval(250)
        self._rec_timer.timeout.connect(self._update_rec_timer_label)

        # ── dot animation timer ────────────────────────────────────────────
        self._dot_timer = QTimer(self)
        self._dot_timer.setInterval(400)
        self._dot_timer.timeout.connect(self._cycle_dots)

        self.show()
        QTimer.singleShot(50, self._apply_acrylic)

    # ── backward compat property ───────────────────────────────────────────
    @property
    def top(self) -> "DockWindow":
        return self

    # ── outer shell geometry (set once, never changes) ───────────────────────
    def _setup_outer_geometry(self) -> None:
        """Position DockWindow at a fixed size large enough for all states."""
        max_w = max(T.STRIP_W, T.IDLE_W, T.REC_W, T.PROC_W, T.DONE_W, T.ERR_W)
        max_h = max(T.STRIP_H, T.IDLE_H, T.REC_H, T.PROC_H, T.DONE_H, T.ERR_H)
        screens = sorted(
            QApplication.instance().screens(),
            key=lambda s: s.geometry().left(),
        )
        screen = screens[len(screens) // 2]
        geo = screen.geometry()
        bottom_anchor = geo.top() + geo.height() - T.BOTTOM_MARGIN
        outer_x = geo.left() + (geo.width() - max_w) // 2
        outer_y = bottom_anchor - max_h
        self.setGeometry(outer_x, outer_y, max_w, max_h)

    # ── build ─────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        layout = QHBoxLayout(self._bar)  # layout lives in the animated child
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(6)

        # Language combo
        self._lang_combo = QComboBox()
        self._lang_combo.setFixedHeight(28)
        # Set font programmatically to avoid QFont::setPointSize(-1) warnings
        # that Qt emits when pixel-based font sizes are inherited by the popup view.
        _combo_font = QFont("Segoe UI", 9)  # 9pt ≈ 12px at 96 DPI
        self._lang_combo.setFont(_combo_font)
        self._lang_combo.setStyleSheet(
            "QComboBox { background: rgba(255,255,255,18); border: 1px solid "
            "rgba(255,255,255,30); border-radius: 10px; padding: 2px 6px; "
            "color: #e2e8f0; } "
            "QComboBox::drop-down { border: none; width: 16px; } "
            "QComboBox QAbstractItemView { background: #2a2a32; color: #e2e8f0; "
            "selection-background-color: #8b5cf6; border: 1px solid #3f3f50; }"
        )
        for code, label in [
            ("", "— auto —"),
            ("de", "Deutsch"),
            ("en", "English"),
            ("fr", "Français"),
            ("es", "Español"),
            ("zh", "中文"),
            ("pt", "Português"),
            ("pl", "Polski"),
            ("it", "Italiano"),
            ("nl", "Nederlands"),
            ("ru", "Русский"),
            ("ja", "日本語"),
            ("ko", "한국어"),
            ("ar", "العربية"),
        ]:
            self._lang_combo.addItem(label, userData=code)
        self._lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        layout.addWidget(self._lang_combo)

        # Provider badge
        self._provider_lbl = QLabel()
        self._provider_lbl.setFixedHeight(22)
        self._provider_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)
        self._provider_lbl.setStyleSheet(
            "QLabel { background: rgba(29,78,216,190); border-radius: 9px; "
            "padding: 1px 7px; color: #93c5fd; font-size: 11px; }"
        )
        layout.addWidget(self._provider_lbl)

        # LLM badge — clickable toggle
        self._llm_lbl = _ClickableLabel("LLM ✓")
        self._llm_lbl.setFixedHeight(22)
        self._llm_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)
        self._llm_lbl.setVisible(False)
        self._llm_lbl.clicked.connect(self._toggle_llm)
        layout.addWidget(self._llm_lbl)

        layout.addStretch()

        # Waveform widget (recording / idle breathing)
        self._wave = _WaveWidget()
        layout.addWidget(self._wave)

        # Status / info label (processing state, done, error)
        self._status_lbl = QLabel()
        self._status_lbl.setStyleSheet(
            "QLabel { color: #e2e8f0; font-size: 13px; background: transparent; }"
        )
        self._status_lbl.setVisible(False)
        layout.addWidget(self._status_lbl)

        layout.addStretch()

        # Timer label (recording countdown)
        self._timer_lbl = QLabel("0:00")
        self._timer_lbl.setStyleSheet(
            "QLabel { color: #94a3b8; font-size: 12px; min-width: 32px; "
            "background: transparent; }"
        )
        self._timer_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self._timer_lbl)

        # Settings button
        self._settings_btn = QToolButton()
        self._settings_btn.setText("⚙")
        self._settings_btn.setFixedSize(28, 28)
        self._settings_btn.setStyleSheet(
            "QToolButton { background: transparent; border: none; color: #94a3b8; "
            "font-size: 15px; border-radius: 6px; } "
            "QToolButton:hover { background: rgba(255,255,255,15); color: #e2e8f0; }"
        )
        self._settings_btn.clicked.connect(self.open_settings_requested)
        layout.addWidget(self._settings_btn)

        # Close button
        self._close_btn = QToolButton()
        self._close_btn.setText("✕")
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setStyleSheet(
            "QToolButton { background: transparent; border: none; color: #64748b; "
            "font-size: 13px; border-radius: 6px; } "
            "QToolButton:hover { background: rgba(239,68,68,60); color: #f87171; }"
        )
        self._close_btn.clicked.connect(self.quit_requested)
        layout.addWidget(self._close_btn)

    # ── language / config ──────────────────────────────────────────────────
    def _apply_language(self, lang: str) -> None:
        self._tr = TRANSLATIONS.get(lang, TRANSLATIONS["de"])
        lang_code = self._config.get("language", "")
        idx = self._lang_combo.findData(lang_code)
        self._lang_combo.blockSignals(True)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.blockSignals(False)

    def _on_lang_changed(self, _idx: int) -> None:
        code = self._lang_combo.currentData()
        self._config["language"] = code
        from config import save_config

        save_config(self._config)
        self.config_saved.emit()

    def update_language(self, lang: str) -> None:
        self._apply_language(lang)

    # ── state transitions ──────────────────────────────────────────────────
    def _goto_state(self, state: DockState, animated: bool = True) -> None:
        self._state = state
        sizes = {
            DockState.STRIP: (T.STRIP_W, T.STRIP_H),
            DockState.IDLE: (T.IDLE_W, T.IDLE_H),
            DockState.RECORDING: (T.REC_W, T.REC_H),
            DockState.PROCESSING: (T.PROC_W, T.PROC_H),
            DockState.DONE: (T.DONE_W, T.DONE_H),
            DockState.ERROR: (T.ERR_W, T.ERR_H),
        }
        w, h = sizes[state]
        target_rect = self._dock_rect(w, h)
        self._update_widget_visibility()
        self._bar.update()
        self._animate_to(target_rect, animated)

    def _update_widget_visibility(self) -> None:
        s = self._state
        is_idle_or_rec = s in (DockState.IDLE, DockState.RECORDING)
        is_status = s in (DockState.PROCESSING, DockState.DONE, DockState.ERROR)
        is_strip = s == DockState.STRIP
        self._lang_combo.setVisible(is_idle_or_rec)
        self._provider_lbl.setVisible(is_idle_or_rec)
        self._wave.setVisible(is_idle_or_rec)
        self._wave.set_recording(s == DockState.RECORDING)
        self._timer_lbl.setVisible(s == DockState.RECORDING)
        self._status_lbl.setVisible(is_status)
        self._settings_btn.setVisible(is_idle_or_rec)
        self._close_btn.setVisible(is_idle_or_rec)
        # LLM badge follows idle/rec visibility and is suppressed in strip state
        if is_strip:
            self._llm_lbl.setVisible(False)
        elif self._llm_active or self._llm_lbl.isVisible():
            self._llm_lbl.setVisible(is_idle_or_rec)

    # ── geometry helpers ───────────────────────────────────────────────────
    def _dock_rect(self, w: int, h: int) -> QRect:
        """Bar rect in DockWindow-local coordinates (bottom-centre aligned)."""
        return QRect((self.width() - w) // 2, self.height() - h, w, h)

    def _animate_to(self, target: QRect, animated: bool = True) -> None:
        """Animate self._bar to *target* (local coords).  No OS window moves."""
        if not animated or self._cur_rect.isEmpty():
            self._bar.setGeometry(target)
            self._cur_rect = target
            return
        if self._anim and self._anim.state() == QPropertyAnimation.Running:
            self._anim.stop()
        # Animate the child widget — Qt handles this internally; no Win32
        # SetWindowPos is called per frame, so expansion is perfectly symmetric.
        self._anim = QPropertyAnimation(self._bar, b"geometry", self)
        dur = (
            T.ANIM_EXPAND_MS
            if target.width() >= self._cur_rect.width()
            else T.ANIM_COLLAPSE_MS
        )
        self._anim.setDuration(dur)
        self._anim.setStartValue(self._bar.geometry())
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._animating = True

        def _done():
            self._cur_rect = target
            self._animating = False

        self._anim.finished.connect(_done)
        self._anim.start()
        self._cur_rect = target

    # ── hover detection ────────────────────────────────────────────────────
    def _check_hover(self) -> None:
        if self._state not in (DockState.STRIP, DockState.IDLE):
            return
        if getattr(self, "_animating", False):
            return
        cursor = QCursor.pos()
        # Use _bar's global rect so hover detection is independent of
        # DockWindow's (fixed, larger) outer geometry.
        bar_origin = self._bar.mapToGlobal(QPoint(0, 0))
        bar_rect = QRect(bar_origin, self._bar.size())
        expanded = QRect(
            bar_rect.x(),
            bar_rect.y() - T.HOVER_ZONE_H,
            bar_rect.width(),
            bar_rect.height() + T.HOVER_ZONE_H,
        )
        mouse_near = expanded.contains(cursor)

        if self._state == DockState.STRIP and mouse_near:
            self._leave_timer.stop()
            self._goto_state(DockState.IDLE)
        elif self._state == DockState.IDLE and not mouse_near:
            if not self._leave_timer.isActive():
                self._leave_timer.start()
        elif self._state == DockState.IDLE and mouse_near:
            self._leave_timer.stop()

    def _on_leave_timeout(self) -> None:
        if self._state == DockState.IDLE:
            self._goto_state(DockState.STRIP)

    # ── public API (matches _MicLevelPopup interface) ──────────────────────
    def set_rms(self, rms: float) -> None:
        self._wave.set_rms(rms)

    def set_recording(self, on_timeout=None) -> None:
        self._on_timeout_cb = on_timeout
        self._rec_start = time.monotonic()
        self._goto_state(DockState.RECORDING)
        self._rec_timer.start()

    def set_idle(self) -> None:
        self._rec_timer.stop()
        self._dot_timer.stop()
        self._on_timeout_cb = None
        self._goto_state(DockState.IDLE)

    def set_processing(self) -> None:
        self._rec_timer.stop()
        self._status_lbl.setText("●●●")
        self._status_lbl.setStyleSheet(
            "QLabel { color: #93c5fd; font-size: 14px; background: transparent; }"
        )
        self._goto_state(DockState.PROCESSING)
        self._dot_timer.start()

    def expand_for_dots(self) -> None:
        """Transition to PROCESSING state (replaces expand_for_dots in popups)."""
        self.set_processing()

    def show_dots(self, n: int) -> None:
        """Legacy no-op — dot animation is managed internally."""

    def set_done(self, hold_ms: int = T.DONE_HOLD_MS) -> None:
        self._dot_timer.stop()
        self._status_lbl.setText("✓ " + self._tr.get("dock_done", "Eingefügt"))
        self._status_lbl.setStyleSheet(
            "QLabel { color: #6ee7b7; font-size: 13px; background: transparent; }"
        )
        self._goto_state(DockState.DONE)
        QTimer.singleShot(hold_ms, self.set_idle)

    def show_error(self, msg: str) -> None:
        self._dot_timer.stop()
        self._rec_timer.stop()
        self._status_lbl.setText(f"✗ {msg}")
        self._status_lbl.setStyleSheet(
            "QLabel { color: #f87171; font-size: 12px; background: transparent; }"
        )
        self._goto_state(DockState.ERROR)
        QTimer.singleShot(T.ERROR_HOLD_MS, self.set_idle)

    def show(self, text: str = "") -> None:
        """Overlay-compatible: show an info/error pill message."""
        if text:
            self.show_error(text)
        else:
            super().show()

    def set_llm_enabled(self, enabled: bool) -> None:
        self._llm_active = enabled
        self._update_llm_badge()
        # Only show the badge when the dock is not collapsed to a strip
        if self._state != DockState.STRIP:
            self._llm_lbl.setVisible(True)

    def _toggle_llm(self) -> None:
        self._llm_active = not self._llm_active
        self._update_llm_badge()
        self.llm_toggled.emit(self._llm_active)

    def _update_llm_badge(self) -> None:
        if self._llm_active:
            self._llm_lbl.setText("LLM ✓")
            self._llm_lbl.setStyleSheet(
                "QLabel { background: rgba(76,29,149,190); border-radius: 9px; "
                "padding: 1px 7px; color: #c084fc; font-size: 11px; "
                "cursor: pointer; }"
            )
        else:
            self._llm_lbl.setText("LLM ✗")
            self._llm_lbl.setStyleSheet(
                "QLabel { background: rgba(55,55,65,160); border-radius: 9px; "
                "padding: 1px 7px; color: #6b7280; font-size: 11px; "
                "cursor: pointer; }"
            )

    def set_max_seconds(self, n: int) -> None:
        self._max_seconds = n

    def set_provider(self, name: str) -> None:
        self._provider_lbl.setText(name)

    def set_target_language(self, lang: str) -> None:
        idx = self._lang_combo.findData(lang)
        self._lang_combo.blockSignals(True)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.blockSignals(False)

    def set_ui_language(self, lang: str) -> None:
        self._apply_language(lang)

    # ── internal helpers ───────────────────────────────────────────────────
    def _update_rec_timer_label(self) -> None:
        elapsed = time.monotonic() - self._rec_start
        remaining = max(0.0, self._max_seconds - elapsed)
        mins, secs = divmod(int(remaining), 60)
        self._timer_lbl.setText(f"{mins}:{secs:02d}")
        if remaining <= 0 and self._on_timeout_cb:
            self._rec_timer.stop()
            cb = self._on_timeout_cb
            self._on_timeout_cb = None
            cb()

    def _cycle_dots(self) -> None:
        self._dot_count = (self._dot_count + 1) % 3
        dots = ["●○○", "●●○", "●●●"][self._dot_count]
        self._status_lbl.setText(dots)

    def _show_info_slot(self, title: str, body: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(None, title, body)

    def _apply_acrylic(self) -> None:
        hwnd = int(self.winId())
        _try_acrylic(hwnd)

    # ── painting ───────────────────────────────────────────────────────────
    def paintEvent(self, _event) -> None:  # noqa: N802
        # DockWindow is a fully transparent container; _DockBar handles painting.
        pass
