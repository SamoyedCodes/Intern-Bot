"""Design tokens, live macOS light/dark theming and the few widgets every view shares."""
from functools import lru_cache
from pathlib import Path
from string import Template

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QStyledItemDelegate, QToolButton, QTreeWidget, QVBoxLayout, QWidget

LIGHT = {
    "bg": "#f7f6f1", "surface": "#fffef8", "surface2": "#e9ede4", "border": "#b9c5ba",
    "text": "#192d28", "text2": "#40564e", "text3": "#52635b",
    "accent": "#a73e22", "accent_hover": "#873016", "on_accent": "#ffffff", "selection": "#d6e5d7",
    "info": "#275e78", "warning": "#895019", "danger": "#a93038", "success": "#306342", "neutral": "#52635b",
    "panel": "#193530", "panel_text": "#f4f4e7", "panel_muted": "#cad9ca", "panel_button": "#ffae78",
    "panel_line": "#547169", "panel_inset": "#27453d",
}
DARK = {
    "bg": "#15241f", "surface": "#20332b", "surface2": "#2b4036", "border": "#4f6357",
    "text": "#f0f2e7", "text2": "#cfdbca", "text3": "#adbfae",
    "accent": "#ffad75", "accent_hover": "#ffc298", "on_accent": "#251c12", "selection": "#405a48",
    "info": "#93cde5", "warning": "#f3ba70", "danger": "#ffa3a5", "success": "#abd6a8", "neutral": "#adbfae",
    "panel": "#112b25", "panel_text": "#f4f4e7", "panel_muted": "#cad9ca", "panel_button": "#ffae78",
    "panel_line": "#56736a", "panel_inset": "#28473d",
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


def station_heading(title, station, description="", compact=False):
    """A workbench nameplate made from the same model as the live scene."""
    frame = QWidget()
    row = QHBoxLayout(frame)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(12)
    art = QLabel()
    size = QSize(62, 48) if compact else QSize(91, 70)
    asset = Path(__file__).with_name("crew") / f"{station}.png"
    art.setPixmap(QPixmap(str(asset)).scaled(size * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    art.setFixedSize(size)
    art.setScaledContents(True)
    row.addWidget(art)
    text = QVBoxLayout()
    text.setSpacing(2)
    text.addWidget(label(title, "section" if compact else "pageTitle"))
    if description:
        text.addWidget(label(description, "muted"))
    row.addLayout(text, 1)
    return frame


def card(spacing=12):
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 18)
    layout.setSpacing(spacing)
    return frame, layout


class ReadableTree(QTreeWidget):
    """Size read-only rows to their full text, including paragraphs and long URLs."""

    class Delegate(QStyledItemDelegate):
        def sizeHint(self, option, index):
            tree = self.parent()
            width = tree.columnWidth(index.column()) - 20
            if index.column() == 0:
                width -= tree.indentation() * (2 if index.parent().isValid() else 1)
            text = str(index.data(Qt.DisplayRole) or "")
            bounds = option.fontMetrics.boundingRect(QRect(0, 0, max(40, width), 0), Qt.TextWordWrap | Qt.TextWrapAnywhere, text)
            return QSize(width, max(30, bounds.height() + 12))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(self.Delegate(self))
        self.setWordWrap(True)
        self.setTextElideMode(Qt.ElideNone)
        self.setEditTriggers(QTreeWidget.NoEditTriggers)
        self.header().sectionResized.connect(lambda *_: self.scheduleDelayedItemsLayout())


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
