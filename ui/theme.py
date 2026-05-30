"""UI theme constants for the PySide6 dock and settings dialog."""

from PySide6.QtGui import QColor

# ── Dock colours ──────────────────────────────────────────────────────────────
DOCK_BG = QColor(28, 28, 34, 220)
DOCK_BG_REC = QColor(35, 22, 30, 230)
DOCK_BG_DONE = QColor(20, 80, 56, 220)
DOCK_BG_ERR = QColor(65, 18, 18, 220)
DOCK_BORDER = QColor(255, 255, 255, 22)

ACCENT = QColor(139, 92, 246)
ACCENT_GLOW = QColor(139, 92, 246, 55)
REC_RED = QColor(239, 68, 68)
REC_GLOW = QColor(239, 68, 68, 55)
PROC_BLUE = QColor(59, 130, 246)
SUCCESS_GREEN = QColor(16, 185, 129)
ERROR_RED = QColor(248, 113, 113)

TEXT_PRIMARY = QColor(241, 245, 249)
TEXT_SECONDARY = QColor(148, 163, 184)
TEXT_MUTED = QColor(71, 85, 105)

BADGE_CLOUD_BG = QColor(29, 78, 216, 190)
BADGE_CLOUD_FG = QColor(147, 197, 253)
BADGE_LOCAL_BG = QColor(63, 63, 70, 190)
BADGE_LOCAL_FG = QColor(161, 161, 170)
BADGE_LLM_BG = QColor(76, 29, 149, 190)
BADGE_LLM_FG = QColor(192, 132, 252)

# ── Dock geometry ─────────────────────────────────────────────────────────────
STRIP_W, STRIP_H = 90, 10
IDLE_W, IDLE_H = 380, 40
REC_W, REC_H = 420, 52
PROC_W, PROC_H = 400, 40
DONE_W, DONE_H = 380, 40
ERR_W, ERR_H = 380, 40

RADIUS = 24
BOTTOM_MARGIN = 70  # px from bottom of screen
HOVER_ZONE_H = 80  # px above strip that triggers expand
LEAVE_DELAY_MS = 2000  # ms before collapsing

# ── Animation durations ───────────────────────────────────────────────────────
ANIM_EXPAND_MS = 180
ANIM_COLLAPSE_MS = 260
DONE_HOLD_MS = 1500
ERROR_HOLD_MS = 3000

# ── Settings dialog stylesheet ────────────────────────────────────────────────
SETTINGS_STYLESHEET = """
QDialog, QWidget {
    background-color: #1c1c22;
    color: #e2e8f0;
    font-family: 'Segoe UI Variable Display', 'Segoe UI', sans-serif;
    font-size: 13px;
}
QGroupBox {
    border: 1px solid rgba(255,255,255,15);
    border-radius: 8px;
    margin-top: 10px;
    padding: 8px;
    font-size: 11px;
    color: #94a3b8;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #2a2a32;
    border: 1px solid #3f3f50;
    border-radius: 6px;
    padding: 4px 8px;
    color: #e2e8f0;
    selection-background-color: #8b5cf6;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #8b5cf6;
}
QLineEdit:disabled {
    color: #6b7280;
    background-color: #22222a;
}
QComboBox {
    background-color: #2a2a32;
    border: 1px solid #3f3f50;
    border-radius: 6px;
    padding: 4px 8px;
    color: #e2e8f0;
    min-width: 60px;
}
QComboBox:focus {
    border-color: #8b5cf6;
}
QComboBox:disabled {
    color: #6b7280;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #2a2a32;
    border: 1px solid #3f3f50;
    color: #e2e8f0;
    selection-background-color: #8b5cf6;
}
QPushButton {
    background-color: #3b3b50;
    border: 1px solid #4f4f6a;
    border-radius: 6px;
    padding: 5px 14px;
    color: #e2e8f0;
}
QPushButton:hover {
    background-color: #4f4f6a;
}
QPushButton:pressed {
    background-color: #5b5b7a;
}
QPushButton:disabled {
    color: #6b7280;
    background-color: #2a2a32;
    border-color: #353540;
}
QPushButton#primary {
    background-color: #8b5cf6;
    border-color: #7c3aed;
    color: #ffffff;
}
QPushButton#primary:hover {
    background-color: #7c3aed;
}
QCheckBox {
    color: #e2e8f0;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #4f4f6a;
    border-radius: 4px;
    background-color: #2a2a32;
}
QCheckBox::indicator:checked {
    background-color: #8b5cf6;
    border-color: #8b5cf6;
}
QLabel {
    color: #e2e8f0;
    background: transparent;
}
QLabel#muted {
    color: #6b7280;
    font-size: 11px;
}
QScrollArea, QScrollArea > QWidget > QWidget {
    background-color: #1c1c22;
}
QScrollBar:vertical {
    background: #1c1c22;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #3f3f50;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QListWidget {
    background-color: #2a2a32;
    border: 1px solid #3f3f50;
    border-radius: 6px;
    color: #e2e8f0;
    outline: none;
}
QListWidget::item:selected {
    background-color: #8b5cf6;
    color: #ffffff;
}
QListWidget::item:hover {
    background-color: #3f3f50;
}
QTableWidget {
    background-color: #2a2a32;
    border: 1px solid #3f3f50;
    border-radius: 6px;
    color: #e2e8f0;
    gridline-color: #3f3f50;
    outline: none;
}
QTableWidget::item:selected {
    background-color: #8b5cf6;
}
QHeaderView::section {
    background-color: #22222a;
    color: #94a3b8;
    border: none;
    border-bottom: 1px solid #3f3f50;
    padding: 4px 8px;
    font-size: 11px;
}
QProgressBar {
    background-color: #2a2a32;
    border: 1px solid #3f3f50;
    border-radius: 4px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #8b5cf6;
    border-radius: 4px;
}
QSplitter::handle {
    background-color: #3f3f50;
}
"""
