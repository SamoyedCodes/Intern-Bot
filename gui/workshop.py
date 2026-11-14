"""Local, read-only views of the current application checkpoints: the orbit chart and the Bar field."""
import json
import math
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QUrl, Signal, Slot, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QSizePolicy, QStackedLayout, QVBoxLayout, QWidget

from core.automation.models import site_key
from gui.theme import DARK, label

ASSETS = Path(__file__).with_name("crew")
STATIONS = ("Intake", "Fill", "Verify", "Dispatch")
STATION_HELP = (
    "Intake opens the posting and loads this application's profile.",
    "Fill uses profile facts and approved answers for the employer's form.",
    "Verify checks field values and brings missing answers back to you.",
    "Dispatch handles review, sending and employer confirmation.",
)
MAX_BARS = 18
ORBITS = (*STATIONS, "Applied", "Closed")
# Orbit radii in scene units, outer Intake to inner Applied, then the rim; the 3D scene uses the same values.
RADII = (7.8, 6.2, 4.6, 3.0, 1.9, 8.9)
LANE_CENTRE = (-1.6, 2.4, -0.5, 0.35, 2.6, -2.5)
SKY, CHALK = "#0f1532", "#eef0fa"


def orbit_of(row):
    """Applied and Closed records leave the station orbits; a send attempt alone stays at Dispatch."""
    return 5 if row["group"] == "Closed" else 4 if row["group"] == "Applied" else row["station"]


def crew_row(run, active_id):
    """Expose only the identity and field dispositions that the scene draws."""
    fields = list(run.fields.values())
    ask = any(i.question for i in run.interventions) and run.status == "needs_input"
    dispatch = run.submission_attempted or run.is_submitted or run.status == "ready_for_review"
    if dispatch:
        station = 3
    elif run.status == "running":
        station = ("intake", "fill", "verify", "dispatch").index(run.work_phase)
    elif ask or (fields and run.status in {"needs_input", "failed"}):
        station = 2
    else:
        station = 0
    bars = []
    count = min(len(fields), MAX_BARS)
    for i in range(count):
        batch = fields[i * len(fields) // count:(i + 1) * len(fields) // count]
        bars.append([sum(f.disposition == "verified" for f in batch) / len(batch),
                     any(f.disposition in {"blocked", "needs_input"} for f in batch),
                     all(f.disposition == "intentionally_omitted" for f in batch)])
    sending = run.submission_attempted and run.status == "ready_for_review"
    moving = run.id == active_id and not run.is_submitted and (run.status == "running" or sending)
    return dict(id=run.id, name=run.company or site_key(run.job_url), station=station, ask=ask,
                moving=moving, bars=bars, total=len(fields),
                sent=run.submission_attempted, receipt=run.submission_confirmed)


class SceneBridge(QObject):
    snapshot = Signal(str)
    ready = Signal(bool)
    picked = Signal(str)
    station = Signal(int)

    @Slot(bool)
    def available(self, ok):
        self.ready.emit(ok)

    @Slot(str)
    def selectRun(self, run_id):
        self.picked.emit(run_id)

    @Slot(int)
    def inspectStation(self, index):
        if 0 <= index < len(STATIONS):
            self.station.emit(index)


class StillScene(QWidget):
    """The orbit chart or the assessment bands, painted flat when a 3D context is unavailable."""
    def __init__(self):
        super().__init__()
        self.state = {}

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()  # match the rounded top of the live scene and the caption bar below it
        clip.addRoundedRect(QRectF(self.rect()).adjusted(0, 0, 0, 14), 14, 14)
        p.setClipPath(clip)
        p.fillRect(self.rect(), QColor(SKY))
        rows, selected = self.state.get("rows", []), self.state.get("selected")
        if not rows:
            p.setPen(QColor(CHALK))
            p.drawText(self.rect(), Qt.AlignCenter, "No applications in this view")
        elif self.state.get("field"):
            self._bars(p, rows, selected)
        else:
            self._orbits(p, rows, selected)
        p.end()

    def _orbits(self, p, rows, selected):
        centre = QPointF(self.width() / 2, self.height() / 2)
        unit = min(self.width(), self.height()) / 2 / (RADII[5] + .6)
        lanes = [[] for _ in RADII]
        for row in rows:
            lanes[orbit_of(row)].append(row)
        for lane, (radius, members) in enumerate(zip(RADII, lanes)):
            chosen = any(row["id"] == selected for row in members)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 230 if chosen else 90), 1.2))
            p.drawEllipse(centre, radius * unit, radius * unit)
            step = min(2 * math.pi / max(1, len(members)), .3 if lane == 5 else .9)
            for k, row in enumerate(members):
                angle = LANE_CENTRE[lane] + (k - (len(members) - 1) / 2) * step
                spot = centre + QPointF(math.sin(angle), math.cos(angle)) * radius * unit
                size = (4 if lane == 5 else 7) * (1.3 if row["id"] == selected else 1)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(row["color"]))
                p.drawEllipse(spot, size, size)
                if row["id"] == selected:
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QPen(QColor(CHALK), 1.5))
                    p.drawEllipse(spot, size + 5, size + 5)
            if lane < 4:
                p.setPen(QColor("#c3cae6"))
                p.drawText(centre + QPointF(radius * unit * .72 + 4, radius * unit * .7), f"{STATIONS[lane]} {len(members)}")
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffd596"))
        p.drawEllipse(centre, .8 * unit, .8 * unit)

    def _bars(self, p, rows, selected):
        line = self.height() / len(rows)
        for i, row in enumerate(rows):
            y = i * line
            p.setPen(QColor("#ffb347" if row["id"] == selected else CHALK))
            name_rect = QRectF(14, y, self.width() * .32 - 18, line)
            p.drawText(name_rect, Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(row["name"], Qt.ElideRight, max(0, int(name_rect.width()))))
            bars = row["bars"]
            if not bars:
                p.drawText(QRectF(self.width() * .33, y, self.width() * .6, line), Qt.AlignVCenter, "No fields assessed")
            gap = min(30, (self.width() * .62) / max(1, len(bars)))
            for n, (share, blocked, omitted) in enumerate(bars):
                height = line * (.07 + .46 * share)
                x, top = self.width() * .33 + n * gap, y + line * .76 - height
                p.fillRect(QRectF(x, top, gap * .75, height), QColor("#ffb347" if blocked else "#7f89b3" if omitted else "#c3cae6"))
                if blocked:
                    p.fillRect(QRectF(x + 2, top - 14, 2, 14), QColor(CHALK))
                    p.fillRect(QRectF(x + 4, top - 14, 8, 5), QColor("#ffb347"))


class Workshop(QWidget):
    picked = Signal(str)
    def __init__(self, store):
        super().__init__()
        self.store = store
        self.setObjectName("workshopPanel")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(220)
        self.field = False
        self.payload = {}
        self.web = None
        self.started = self.ready = False
        self.bridge = SceneBridge(self)
        self.bridge.ready.connect(self._ready)
        self.bridge.picked.connect(self._pick)
        self.bridge.station.connect(lambda i: self.caption.setText(STATION_HELP[i]))
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.layers = QStackedLayout()
        self.still = StillScene()
        self.layers.addWidget(self.still)
        box.addLayout(self.layers, 1)
        caption_bar = QFrame()
        caption_bar.setObjectName("sceneCaptionBar")
        caption_row = QHBoxLayout(caption_bar)
        caption_row.setContentsMargins(0, 0, 0, 0)
        caption_row.setSpacing(0)
        self.caption = label(role="sceneCaption")
        self.caption.setTextFormat(Qt.PlainText)
        caption_row.addWidget(self.caption, 1)
        self.rotate_hint = label("Drag or use ← → to turn", "sceneCaption", wrap=False)
        self.rotate_hint.hide()
        caption_row.addWidget(self.rotate_hint)
        box.addWidget(caption_bar)
        self.setAccessibleName("Application orbit chart")

    def _pick(self, run_id):
        if any(row["id"] == run_id for row in self.payload.get("rows", [])):
            self.picked.emit(run_id)

    def showEvent(self, event):
        super().showEvent(event)
        if not self.started:
            self.started = True
            if QGuiApplication.platformName() not in {"offscreen", "minimal"}:
                QTimer.singleShot(0, self, self._open_scene)

    def _open_scene(self):
        try:
            from PySide6.QtWebChannel import QWebChannel
            from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError:
            return
        self.web = QWebEngineView(self)
        self.web.setContextMenuPolicy(Qt.NoContextMenu)
        self.web.setAcceptDrops(False)
        self.web.setAccessibleName("Rotatable 3D orbit chart. Left and right arrows turn it.")
        app = QApplication.instance()
        if not hasattr(app, "_crew_profile"):
            app._crew_profile = QWebEngineProfile(app)  # unnamed profiles keep session data in memory
        page = QWebEnginePage(app._crew_profile, self.web)
        page.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
        page.settings().setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
        page.settings().setAttribute(QWebEngineSettings.LocalStorageEnabled, False)
        page.setBackgroundColor(Qt.transparent)
        self.web.setPage(page)
        self.channel = QWebChannel(page)
        self.channel.registerObject("crew", self.bridge)
        page.setWebChannel(self.channel)
        self.layers.addWidget(self.web)
        self.web.renderProcessTerminated.connect(lambda *_: self._ready(False))
        self.web.load(QUrl.fromLocalFile(str(ASSETS / "viewport.html")))

    def _ready(self, ok):
        self.ready = ok
        self.layers.setCurrentWidget(self.web if ok else self.still)
        self.rotate_hint.setVisible(ok)
        if ok and self.payload:
            self.bridge.snapshot.emit(json.dumps(self.payload))

    def display(self, runs, selected, active_id, meta):
        """Draw the visible table rows: every row as a planet, or a page of three Bar field tracks."""
        index = next((i for i, run in enumerate(runs) if run.id == selected), 0)
        offset = index // 3 * 3 if self.field else 0
        shown = runs[offset:offset + 3] if self.field else runs
        rows = []
        for run in shown:
            text, tone, group = meta(run)
            row = crew_row(run, active_id)
            row.update(status=text, group=group, color=DARK.get(tone, DARK["neutral"]), ready=tone == "ready")
            rows.append(row)
        viewed = next((row for row in rows if row["id"] == selected), None)
        if self.field:
            caption = (f"Tracks {offset+1}–{offset+len(rows)} of {len(runs)} · Height shows verified share · Flag needs attention"
                       if rows else "Bar field · No matching applications")
        elif viewed:
            # "Applied · Kestrel Bio · Applied" says the same thing twice.
            caption = "  ·  ".join(dict.fromkeys((ORBITS[orbit_of(viewed)], viewed["name"], viewed["status"])))
        else:
            caption = "No applications in this view" if not rows else "Intake  /  Fill  /  Verify  /  Dispatch  /  Applied"
        self.caption.setText(caption)
        self.still.setAccessibleName(caption)
        state = dict(field=self.field, rows=rows, selected=selected, motion=self.store.get("crew_motion", True))
        if state != self.payload:
            self.payload = self.still.state = state
            self.still.update()
            if self.ready:
                self.bridge.snapshot.emit(json.dumps(state))
