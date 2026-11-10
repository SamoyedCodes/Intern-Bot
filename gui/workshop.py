"""Local, read-only views of the current application checkpoints."""
import json
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Qt, QUrl, Signal, Slot, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QSizePolicy, QStackedLayout, QVBoxLayout, QWidget

from core.automation.models import site_key
from gui.theme import label

ASSETS = Path(__file__).with_name("crew")
STATIONS = ("Intake", "Fill", "Verify", "Dispatch")
STATION_HELP = (
    "Intake opens the posting and loads this application's profile.",
    "Fill uses profile facts and approved answers for the employer's form.",
    "Verify checks field values and brings missing answers back to you.",
    "Dispatch handles review, sending and employer confirmation.",
)
MAX_BARS = 18


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
    """The same stations and assessment bands when a 3D context is unavailable."""
    def __init__(self):
        super().__init__()
        self.images = [QPixmap(str(ASSETS / f"{name.lower()}.png")) for name in STATIONS]
        self.state = {}

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()  # match the rounded top of the live scene and the caption bar below it
        clip.addRoundedRect(QRectF(self.rect()).adjusted(0, 0, 0, 12), 10, 10)
        p.setClipPath(clip)
        field = self.state.get("field")
        rows = self.state.get("rows", [])
        selected = self.state.get("selected")
        viewing = next((r for r in rows if r["id"] == selected), None)
        p.fillRect(self.rect(), QColor("#28342f" if field or self.state.get("dark") else "#ccdbcf"))
        if field:
            if not rows:
                p.setPen(QColor("#e1eadc"))
                p.drawText(self.rect(), Qt.AlignCenter, "No applications in this view")
            for i, row in enumerate(rows):
                line = self.height() / len(rows)
                y = i * line
                p.setPen(QColor("#d9f197" if row["id"] == selected else "#ebf0e6"))
                name_rect = QRectF(14, y, self.width()*.32-18, line)
                name = p.fontMetrics().elidedText(row["name"], Qt.ElideRight, max(0, int(name_rect.width())))
                p.drawText(name_rect, Qt.AlignVCenter | Qt.AlignLeft, name)
                bars = row["bars"]
                if not bars:
                    p.drawText(QRectF(self.width()*.33,y,self.width()*.6,line), Qt.AlignVCenter, "No fields assessed")
                gap = min(30, (self.width()*.62) / max(1, len(bars)))
                for n,(share, blocked, omitted) in enumerate(bars):
                    height = line*(.07 + .46*share)
                    color = "#eeb75b" if blocked else "#94a7b7" if omitted else "#d4ddbe"
                    x, top = self.width()*.33+n*gap, y+line*.76-height
                    p.fillRect(QRectF(x, top, gap*.75, height), QColor(color))
                    if blocked:
                        p.fillRect(QRectF(x+2, top-14, 2, 14), QColor("#f4ead1"))
                        p.fillRect(QRectF(x+4, top-14, 8, 5), QColor("#eeb75b"))
        else:
            cell = self.width() / 4
            for i, img in enumerate(self.images):
                size = img.size().scaled(int(cell+4), max(1,self.height()-12), Qt.KeepAspectRatio)
                rect = QRectF(i*cell+(cell-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())
                p.drawPixmap(rect,img,QRectF(img.rect()))
                if viewing and i == viewing["station"]:
                    p.fillRect(QRectF(i*cell+cell*.18,self.height()-5,cell*.64,3), QColor("#bf542b" if not self.state["dark"] else "#ffb179"))
        p.end()


class Workshop(QWidget):
    picked = Signal(str)
    def __init__(self, store):
        super().__init__()
        self.store = store
        self.setObjectName("workshopPanel")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(135)
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
        self.rotate_hint = label("Drag or use ← → to rotate", "sceneCaption", wrap=False)
        self.rotate_hint.hide()
        caption_row.addWidget(self.rotate_hint)
        box.addWidget(caption_bar)
        self.setAccessibleName("Application workshop")

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
        self.web.setAccessibleName("Rotatable 3D workshop. Left and right arrows turn the scene.")
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

    def display(self, runs, selected, active_id, status_label):
        index = next((i for i, run in enumerate(runs) if run.id == selected), 0)
        offset = index // 3 * 3
        rows = [crew_row(run, active_id) for run in runs[offset:offset+3]]
        viewed = next((row for row in rows if row["id"] == selected), None)
        if self.field:
            caption = (f"Tracks {offset+1}–{offset+len(rows)} of {len(runs)} · Height shows verified share · Flag needs attention"
                       if rows else "Bar field · No matching applications")
        elif viewed:
            caption = f"{STATIONS[viewed['station']]}  ·  {viewed['name']}  ·  {status_label}"
        else:
            caption = "Crew standing by  ·  Intake  /  Fill  /  Verify  /  Dispatch"
        self.caption.setText(caption)
        self.still.setAccessibleName(caption)
        state = dict(field=self.field, rows=rows, selected=selected, motion=self.store.get("crew_motion", True),
                     dark=QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark)
        if state != self.payload:
            self.payload = self.still.state = state
            self.still.update()
            if self.ready:
                self.bridge.snapshot.emit(json.dumps(state))
