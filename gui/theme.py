"""Design tokens, live macOS light/dark theming and the few widgets every view shares."""
from functools import lru_cache
from pathlib import Path
from string import Template

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPalette, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QStyledItemDelegate, QToolButton, QTreeWidget, QVBoxLayout, QWidget

LIGHT = {
    "bg": "#eef0f6", "surface": "#fbfcff", "surface2": "#e2e6f1", "border": "#b3bad2",
    "text": "#11173a", "text2": "#394267", "text3": "#4f587d",
    "accent": "#ffb347", "accent_hover": "#f5a433", "on_accent": "#1d1405", "focus": "#2b46c4", "selection": "#d9dff5", "ready": "#11173a",
    "info": "#2453c4", "warning": "#965100", "danger": "#b1243a", "success": "#1d7449", "neutral": "#535c82",
    "panel": "#141b40", "panel_text": "#eef0fa", "panel_muted": "#b9c0e0", "panel_button": "#ffb347",
    "panel_line": "#39437c", "panel_inset": "#222a5a", "sky": "#0f1532",
}
DARK = {
    "bg": "#0a0e22", "surface": "#121838", "surface2": "#1b2250", "border": "#3a4479",
    "text": "#eef0fa", "text2": "#c3cae6", "text3": "#a4acd0",
    "accent": "#ffb347", "accent_hover": "#ffc670", "on_accent": "#1d1405", "focus": "#ffd596", "selection": "#2b3570", "ready": "#ffffff",
    "info": "#6fb6ff", "warning": "#ffb347", "danger": "#ff9a9a", "success": "#7ee0a8", "neutral": "#8f98c2",
    "panel": "#161d45", "panel_text": "#eef0fa", "panel_muted": "#b9c0e0", "panel_button": "#ffb347",
    "panel_line": "#3d4884", "panel_inset": "#232c60", "sky": "#0f1532",
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
                          (QPalette.Link, "focus"), (QPalette.Mid, "border")]:
            palette.setColor(role, t[key])
        app.setPalette(palette)
        app.setStyleSheet(Template(_QSS.read_text(encoding="utf-8")).substitute(TOKENS, chevron=_QSS.with_name("chevron.svg").as_posix()))
    apply()
    if not app.property("themeFollowsSystem"):
        app.setProperty("themeFollowsSystem", True)
        app.styleHints().colorSchemeChanged.connect(apply)


@lru_cache(maxsize=64)
def _dot(color: str, ringed: bool = False) -> QIcon:
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    if ringed:  # the ringed planet of an application waiting for approval
        painter.drawEllipse(6, 6, 8, 8)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(color), 1.6))
        painter.drawEllipse(QRectF(2.5, 2.5, 15, 15))
    else:
        painter.drawEllipse(4, 4, 12, 12)
    painter.end()
    return QIcon(pixmap)


def dot_icon(tone: str, palette=None) -> QIcon:
    """A status dot in the live palette, or in DARK for marks on the always-navy panels."""
    palette = palette or TOKENS
    return _dot(palette.get(tone, palette["neutral"]), tone == "ready")


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


@lru_cache(maxsize=16)
def orbit_glyph(station: str, width: int, height: int) -> QPixmap:
    """A small night-sky chart with this destination's orbit lit, drawn like the live Applications scene."""
    scale = 2
    pixmap = QPixmap(width * scale, height * scale)
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(DARK["sky"]))
    p.drawRoundedRect(QRectF(0, 0, width, height), 10, 10)
    centre = QPointF(width * .5, height * .54)
    lit = ("intake", "fill", "verify", "dispatch").index(station)
    for index, share in enumerate((.42, .33, .24, .15)):
        rx, ry = width * share, height * share * 1.05
        on = index == lit
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(DARK["accent"] if on else "#5b6596"), 1.6 if on else 1))
        p.drawEllipse(centre, rx, ry * .62)
        if on:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(DARK["accent"]))
            p.drawEllipse(centre + QPointF(-rx * .72, ry * .62 * .69), 3.2, 3.2)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ffd596"))
    p.drawEllipse(centre, width * .055, width * .055)
    p.end()
    return pixmap


def station_heading(title, station, description="", compact=False):
    """A destination heading with its orbit from the Applications chart."""
    frame = QWidget()
    row = QHBoxLayout(frame)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(12)
    art = QLabel()
    size = QSize(62, 48) if compact else QSize(91, 70)
    art.setPixmap(orbit_glyph(station, size.width(), size.height()))
    art.setFixedSize(size)
    art.setAccessibleName(f"{station.title()} orbit")
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
