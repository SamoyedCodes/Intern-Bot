"""Design tokens, live macOS light/dark theming and the few widgets every view shares."""
from functools import lru_cache
from pathlib import Path
from string import Template

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import QFormLayout, QFrame, QLabel, QPushButton, QToolButton, QVBoxLayout

LIGHT = {
    "bg": "#f6f7f9", "surface": "#ffffff", "surface2": "#eef0f3", "border": "#dcdfe5",
    "text": "#16181d", "text2": "#555d6b", "text3": "#6b7280",
    "accent": "#15803d", "accent_hover": "#116b33", "on_accent": "#ffffff", "selection": "#d7efe0",
    "info": "#1d5fd1", "warning": "#a35f00", "danger": "#c62f3b", "success": "#15803d", "neutral": "#6b7280",
}
DARK = {
    "bg": "#0f1115", "surface": "#161920", "surface2": "#1e222b", "border": "#2a2f3a",
    "text": "#e8eaf0", "text2": "#a0a7b4", "text3": "#7d8594",
    "accent": "#2fbf71", "accent_hover": "#3fd283", "on_accent": "#04130a", "selection": "#1c3a2b",
    "info": "#5b9dff", "warning": "#e5a50a", "danger": "#f0616d", "success": "#2fbf71", "neutral": "#7d8594",
}
TOKENS = dict(LIGHT)  # live palette; apply_theme updates it in place
_QSS = Path(__file__).with_name("styles.qss")


def apply_theme(app):
    """Style the app from the system colour scheme and follow it when it changes."""
    def apply(*_):
        dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
        TOKENS.update(DARK if dark else LIGHT)
        t = {k: QColor(v) for k, v in TOKENS.items()}
        palette = QPalette()
        for role, key in [(QPalette.Window, "bg"), (QPalette.WindowText, "text"), (QPalette.Base, "surface"),
                          (QPalette.AlternateBase, "surface2"), (QPalette.Text, "text"), (QPalette.Button, "surface"),
                          (QPalette.ButtonText, "text"), (QPalette.Highlight, "selection"), (QPalette.HighlightedText, "text"),
                          (QPalette.PlaceholderText, "text3"), (QPalette.ToolTipBase, "surface2"), (QPalette.ToolTipText, "text"),
                          (QPalette.Link, "accent"), (QPalette.Mid, "border")]:
            palette.setColor(role, t[key])
        app.setPalette(palette)
        app.setStyleSheet(Template(_QSS.read_text(encoding="utf-8")).substitute(TOKENS, chevron=_QSS.with_name("chevron.svg").as_posix()))
    apply()
    if not app.property("themeFollowsSystem"):
        app.setProperty("themeFollowsSystem", True)
        app.styleHints().colorSchemeChanged.connect(apply)


@lru_cache(maxsize=64)
def _dot(color: str) -> QIcon:
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(4, 4, 12, 12)
    painter.end()
    return QIcon(pixmap)


def dot_icon(tone: str) -> QIcon:
    return _dot(TOKENS.get(tone, TOKENS["neutral"]))


def restyle(widget, **properties):
    """Set dynamic style properties (variant, tone, role) and re-apply the stylesheet."""
    for name, value in properties.items():
        widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def button(text, slot=None, variant="secondary", tip=""):
    widget = QPushButton(text)
    widget.setProperty("variant", variant)
    widget.setCursor(Qt.PointingHandCursor)
    if slot:
        widget.clicked.connect(slot)
    if tip:
        widget.setToolTip(tip)
    return widget


def more_button(menu, name="More actions"):
    widget = QToolButton()
    widget.setText("⋯")
    widget.setAccessibleName(name)
    widget.setToolTip(name)
    widget.setPopupMode(QToolButton.InstantPopup)
    widget.setMenu(menu)
    return widget


def shortcut(keys, parent, slot, context=Qt.WindowShortcut):
    widget = QShortcut(QKeySequence(keys), parent)
    widget.setContext(context)
    widget.activated.connect(slot)
    return widget


def label(text="", role="", wrap=True):
    widget = QLabel(text)
    widget.setWordWrap(wrap)
    if role:
        widget.setProperty("role", role)
    return widget


def form_layout(spacing=10):
    """A form whose fields fill the width. macOS otherwise keeps fields at their size hint."""
    layout = QFormLayout()
    layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    layout.setLabelAlignment(Qt.AlignLeft)
    layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
    layout.setVerticalSpacing(spacing)
    return layout


def card(spacing=12):
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 18)
    layout.setSpacing(spacing)
    return frame, layout


class MessageBar(QLabel):
    """Inline feedback next to where the user acted. Info fades; warnings stay until the next message."""

    def __init__(self):
        super().__init__()
        self.setObjectName("messageBar")
        self.setWordWrap(True)
        self.hide()
        self._timer = QTimer(self, singleShot=True, interval=6000, timeout=self.hide)

    def notify(self, text, tone="info"):
        self.setText(text)
        restyle(self, tone=tone)
        self.setVisible(bool(text))
        self._timer.stop()
        if tone in {"info", "success"}:
            self._timer.start()
