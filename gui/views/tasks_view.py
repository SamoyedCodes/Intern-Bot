"""Applications workspace: one list, one detail panel, one sequential queue."""
import subprocess
import sys
from datetime import datetime, timezone

from PySide6.QtCore import QEvent, QPointF, QRectF, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QGuiApplication, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QScrollArea,
    QSizePolicy, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from core.automation.accounts import login_address
from core.automation.assistant import ai_config
from core.automation.recipes import build_from_capture, recipe_for
from core.automation.self_teach import consent_text
from core.automation.models import ApplicantProfile, ApplicationRun, InterventionRequest, ats_name, canonical_url, job_identity, now, site_key
from core.automation.review import review_values
from core.automation.service import AutomationService
from core.storage.local_store import LocalStore
from core.tracker import PIPELINE, activity, export_csv, import_csv
from gui.theme import TOKENS, form_layout, MessageBar, button, card, dot_icon, label, more_button, restyle, shortcut, station_heading
from gui.workshop import Workshop
from gui.views.application_dialogs import ProfileDialog, RecipeReviewDialog, ReviewDialog, RunDetailsDialog

BULK_LABELS = {"retry": "Retry failed", "restart": "Restart from beginning", "cancel": "Cancel tasks", "delete": "Delete tasks"}
GROUPS = ("All", "Needs you", "In progress", "Applied", "Closed")
STATUS = {
    "queued": ("Queued", "neutral", "In progress"),
    "running": ("Preparing…", "info", "In progress"),
    "ready_for_review": ("Ready to approve", "accent", "Needs you"),
    "failed": ("Failed", "danger", "Needs you"),
    "cancelled": ("Cancelled", "neutral", "Closed"),
}
FINISHED = {
    "needs_input": ("{} needs your input.", "warning"),
    "ready_for_review": ("{} is ready to approve. Review what was filled, then send it from here.", "success"),
    "failed": ("{} stopped with an error. Open it to see why.", "danger"),
}


def receipt_unconfirmed(run):
    """Send was clicked once but no employer receipt was recognized: never offer Send again."""
    return run.submission_attempted and not run.is_submitted


def unsupported(run):
    """Stopped because no adapter or recipe knows this site: it can be taught."""
    return run.status == "needs_input" and any(i.message.startswith("No supported application form") for i in run.interventions)


def awaiting_verification(run):
    return run.status == "needs_input" and any(i.kind == "activation" for i in run.interventions)


def desktop_notification(title, text):
    if sys.platform == "darwin":
        # Values travel as argv, never as AppleScript source.
        subprocess.Popen(["osascript", "-e", "on run argv", "-e", "display notification (item 2 of argv) with title (item 1 of argv)", "-e", "end run", title, text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def status_meta(run):
    """(label, tone, filter group) for a run: the single source of truth for status display."""
    if run.pipeline in {"rejected", "archived"}:
        return run.pipeline.title(), "neutral", "Closed"
    if run.pipeline not in {"saved", "applied"}:
        return run.pipeline.title(), "success", "Applied"
    if run.is_submitted or run.submitted_at or run.pipeline == "applied":
        return ("Submitted by you" if run.submitted_by_user else "Applied"), "success", "Applied"
    if receipt_unconfirmed(run):
        return "Sent · receipt unconfirmed", "warning", "Needs you"
    if awaiting_verification(run):
        return "Waiting for email verification", "warning", "Needs you"
    if run.status == "needs_input":
        return ("Needs your answer" if any(i.question for i in run.interventions) else "Needs attention"), "warning", "Needs you"
    return STATUS[run.status]


def ago(iso):
    try:
        seconds = int((datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds())
    except (TypeError, ValueError):
        return iso[:10]
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago" if seconds < 7 * 86400 else iso[:10]


def stage_text(run):
    if 0 <= run.step < len(run.steps):
        return f"{run.steps[run.step]} · step {run.step + 1} of {len(run.steps)}"
    if run.stage == "start":
        return "Not started"
    stage = "Application form" if run.stage.startswith("form_") else run.stage.replace("_", " ")
    return stage[:1].upper() + stage[1:]


def duration(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes} min {seconds} s" if minutes else f"{seconds} s"


class Stepper(QWidget):
    """The site's own steps as dots on a line: done, current (ringed, bold) and still to come."""

    def __init__(self):
        super().__init__()
        self.steps, self.current = [], -1
        font = QFont(self.font())
        font.setPixelSize(11)
        self.setFont(font)
        self.setFixedHeight(22 + 3 * self.fontMetrics().height())

    def set_steps(self, steps, current):
        self.steps, self.current = steps, current
        self.setToolTip("\n".join(f"{i + 1}. {name}" for i, name in enumerate(steps)))
        self.setAccessibleName("Application progress")
        self.setAccessibleDescription((f"Step {current + 1} of {len(steps)}: {steps[current]}. " if 0 <= current < len(steps) else "") + "; ".join(steps))
        self.update()

    def paintEvent(self, _):
        if not self.steps:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, y = self.width() / len(self.steps), 9
        accent, muted = QColor(TOKENS["panel_button"]), QColor(TOKENS["panel_line"])
        painter.setPen(QPen(muted, 2))
        painter.drawLine(QPointF(width / 2, y), QPointF(self.width() - width / 2, y))
        if self.current > 0:
            painter.setPen(QPen(accent, 2))
            painter.drawLine(QPointF(width / 2, y), QPointF(width / 2 + self.current * width, y))
        # The current step is also written in full above the diagram.
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(11)
        for i, name in enumerate(self.steps):
            center = QPointF(width / 2 + i * width, y)
            painter.setPen(Qt.NoPen)
            painter.setBrush(accent if i <= self.current else muted)
            radius = 8 if i == self.current else 5
            painter.drawEllipse(center, radius, radius)
            if i == self.current:
                painter.setBrush(QColor(TOKENS["panel"]))
                painter.drawEllipse(center, 3, 3)
            font.setBold(i == self.current)
            painter.setFont(font)
            painter.setPen(QColor(TOKENS["panel_text" if i == self.current else "panel_muted"]))
            name = " ".join(QFontMetrics(font).elidedText(word, Qt.ElideRight, int(width) - 4) for word in name.split())
            painter.drawText(QRectF(i * width + 2, y + 13, width - 4, self.height() - y - 13), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, name)


class Item(QTableWidgetItem):
    """Sorts by its UserRole + 1 key when present (timestamps), otherwise by text."""

    def __lt__(self, other):
        mine, theirs = self.data(Qt.UserRole + 1), other.data(Qt.UserRole + 1)
        return mine < theirs if mine is not None and theirs is not None else self.text().casefold() < other.text().casefold()


class TaskDialog(QDialog):
    def __init__(self, parent=None, url=""):
        super().__init__(parent)
        self.store = parent.store if parent else LocalStore()
        self.start_after = False
        self.setWindowTitle("New application")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(station_heading("New application", "intake", compact=True))
        form = form_layout(10)
        self.url, self.company, self.role = QLineEdit(), QLineEdit(), QLineEdit()
        self.url.setPlaceholderText("https://company.wd1.myworkdayjobs.com/…")
        self.role.setPlaceholderText("Internship")
        self.detected = label(role="caption")
        self.url.textChanged.connect(self.detect)
        url_box = QVBoxLayout()
        url_box.setSpacing(4)
        url_box.addWidget(self.url)
        url_box.addWidget(self.detected)
        form.addRow("Job URL", url_box)
        form.addRow("Company", self.company)
        form.addRow("Role", self.role)
        self.profile = QComboBox()
        self.profile.addItems(self.store.profiles())
        self.profile.setCurrentText(self.store.get("active_profile", "Default"))
        form.addRow("Profile", self.profile)
        self.mode = QComboBox()
        self.mode.addItem("Classic · fills the form in the browser", "classic")
        self.mode.addItem("Request · Workday API questions, then browser completion (beta)", "request")
        form.addRow("Mode", self.mode)
        layout.addLayout(form)
        layout.addWidget(label("Company and role are read from the posting when left blank. Nothing is sent until you review and approve the filled application.", "caption"))
        self.error = label()
        self.error.setProperty("tone", "danger")
        layout.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(button("Cancel", self.reject, "ghost"))
        buttons.addWidget(button("Add", lambda: self.validate(False)))
        add_and_start = button("Add and prepare", lambda: self.validate(True), "primary")
        add_and_start.setDefault(True)
        buttons.addWidget(add_and_start)
        layout.addLayout(buttons)
        clipboard = url or QGuiApplication.clipboard().text().strip()
        if clipboard.startswith("https://") and not any(c.isspace() for c in clipboard):
            self.url.setText(clipboard)
            self.url.selectAll()
        self.detect()
        self.url.setFocus()

    def detect(self):
        text, tone, message = self.url.text().strip(), "", ""
        if text:
            try:
                canonical_url(text, supported_only=False)
                name = ats_name(text)
                tone, message = ("success", f"{name} · supported") if name else (
                    "warning", "Unrecognized site · it opens for detection, and you may need to finish it manually")
            except ValueError as exc:
                tone, message = "danger", str(exc)
        self.detected.setText(message)
        restyle(self.detected, tone=tone)

    def validate(self, start=False):
        try:
            canonical_url(self.url.text().strip(), supported_only=False)
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        if self.mode.currentData() == "request" and ats_name(self.url.text().strip()) != "Workday":
            self.error.setText("Request mode works with Workday postings only. Choose Classic for this site.")
            return
        self.start_after = start
        self.accept()

    def application(self):
        return ApplicationRun(job_url=canonical_url(self.url.text().strip(), supported_only=False),
                              company=self.company.text().strip(), role=self.role.text().strip() or "Internship",
                              profile_name=self.profile.currentText(), profile_snapshot=self.store.profiles()[self.profile.currentText()],
                              mode=self.mode.currentData(), **{**self.store.get("automation_options", {}), "browser": "chromium"})


class TasksView(QWidget):
    changed = Signal()
    open_profile = Signal(str)

    def __init__(self, store=None):
        super().__init__()
        self.store = store or LocalStore()
        self.service = AutomationService(self.store, self)
        self.service.progress.connect(self.on_progress)
        self.service.finished.connect(self.on_finished)
        self.tasks = []
        self._checked_ids = set()
        self._queue = []
        self._active_id = None
        self._closing = False
        self._shown_id = None
        self._stopped_id = None  # the run you paused or cancelled, so its stop doesn't notify you
        self._save_timer = QTimer(self, singleShot=True, interval=600, timeout=self.save_tracking)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addLayout(self._build_header())
        layout.addLayout(self._build_paste())
        self.notice = MessageBar()
        layout.addWidget(self.notice)
        splitter = self.splitter = QSplitter()
        splitter.setHandleWidth(12)
        splitter.setChildrenCollapsible(False)
        workbench = QWidget()
        bench = QVBoxLayout(workbench)
        bench.setContentsMargins(0, 0, 0, 0)
        bench.setSpacing(8)
        self.workshop = Workshop(self.store)
        self.workshop.picked.connect(self.select_track)
        bench.addWidget(self.workshop, 5)
        bench.addLayout(self._build_chips())
        bench.addWidget(self._build_bulk_bar())
        bench.addWidget(self._build_table(), 4)
        splitter.addWidget(workbench)
        self.body = QStackedWidget()
        self.body.setMinimumWidth(330)
        self.body.setMaximumWidth(470)
        self.body.addWidget(self._build_empty())
        self.body.addWidget(self._build_detail())
        splitter.addWidget(self.body)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([770, 375])
        splitter.splitterMoved.connect(lambda *_: self.fit_columns())
        layout.addWidget(splitter, 1)
        for keys in (QKeySequence(Qt.Key_Return), QKeySequence(Qt.Key_Enter)):
            shortcut(keys, self.table, self.primary_action, Qt.WidgetShortcut)
        for keys in (QKeySequence.Delete, QKeySequence(Qt.Key_Backspace)):
            shortcut(keys, self.table, lambda: self.bulk_action("delete") if self._checked_ids else self.delete_selected(), Qt.WidgetShortcut)
        self.table.model().layoutChanged.connect(self.update_workshop)
        self.load_state()
        self.switch_scene(self.scene_modes.checkedId(), save=False)

    # Layout

    def _build_header(self):
        row = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.page_title = label("Application workshop", "pageTitle")
        titles.addWidget(self.page_title)
        self.stats = label(role="muted")
        titles.addWidget(self.stats)
        row.addLayout(titles, 1)
        self.scene_modes = QButtonGroup(self)
        for index, text in enumerate(("Workshop", "Bar field", "List")):
            mode = button(text, variant="segment")
            mode.setCheckable(True)
            self.scene_modes.addButton(mode, index)
            row.addWidget(mode)
        saved_mode = self.store.get("application_view", "Workshop")
        self.scene_modes.button({"Bar field": 1, "List": 2}.get(saved_mode, 0)).setChecked(True)
        self.scene_modes.idClicked.connect(self.switch_scene)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search applications")
        self.search.setToolTip("Search company, role or URL")
        self.search.setAccessibleName("Search applications")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(205)
        self.search.setMinimumWidth(130)
        self.search.textChanged.connect(lambda: self.render())
        row.addWidget(self.search)
        self.run_queue = button("Run queue", self.start_all_tasks, tip="Start every queued or failed application, one at a time")
        row.addWidget(self.run_queue)
        menu = QMenu(self)
        menu.addAction("Import CSV…", self.import_file)
        menu.addAction("Export CSV…", self.export_file)
        row.addWidget(more_button(menu, "Import and export"))
        return row

    def switch_scene(self, index, save=True):
        self.workshop.field = index == 1
        self.workshop.setVisible(index != 2)
        self.page_title.setText(("Application workshop", "Field crew", "Applications")[index])
        if save:
            self.store.put("application_view", self.scene_modes.button(index).text())
        self.update_workshop()

    def select_track(self, run_id):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.UserRole) == run_id:
                self.table.selectRow(row)
                break

    def update_workshop(self, *_):
        if self.table.signalsBlocked():
            return
        by_id = {run.id: run for run in self.tasks}
        runs = [by_id[item.data(Qt.UserRole)] for row in range(self.table.rowCount())
                if (item := self.table.item(row, 0)) and item.data(Qt.UserRole) in by_id]
        viewed = by_id.get(self._shown_id)
        self.workshop.display(runs, self._shown_id, self._active_id, status_meta(viewed)[0] if viewed else "")

    def _build_paste(self):
        layout = QVBoxLayout()
        layout.setSpacing(4)
        row = QHBoxLayout()
        self.paste = QLineEdit()
        self.paste.setPlaceholderText("Paste a job link and press Enter")
        self.paste.setAccessibleName("Job link")
        self.paste.setClearButtonEnabled(True)
        self.paste.returnPressed.connect(self.prepare_pasted)
        row.addWidget(self.paste, 1)
        row.addWidget(button("Prepare application", self.prepare_pasted, "primary", "Add the pasted job and start filling it with the active profile (⌘N focuses the link field)"))
        row.addWidget(button("Options…", self.add_dialog, tip="Set company, role, profile or mode before adding"))
        layout.addLayout(row)
        self.paste_profile = label(role="caption")
        layout.addWidget(self.paste_profile)
        self.refresh_paste_profile()
        return layout

    def refresh_paste_profile(self):
        name = self.store.get("active_profile", "Default")
        self.paste_profile.setText(f"Using profile: {name} · Review each application before sending")
        self.paste.setToolTip(f"Uses your active profile: {name}")

    def _build_chips(self):
        row = QHBoxLayout()
        row.setSpacing(6)
        self.chips = QButtonGroup(self)
        for index, name in enumerate(GROUPS):
            chip = button(name, variant="chip")
            chip.setCheckable(True)
            chip.setChecked(index == 0)
            self.chips.addButton(chip, index)
            row.addWidget(chip)
        self.chips.idClicked.connect(lambda _: self.render())
        row.addStretch()
        return row

    def _build_empty(self):
        frame, box = card(12)
        frame.setObjectName("setupPanel")
        box.addWidget(label("Set up your workshop", "inspectorTitle"))
        box.addWidget(label("Give the crew a profile, a resume and a job link. You can review what it filled before sending.", "muted"))
        self.checklist = []
        for text, go, action in [("Add your name and email", "Edit profile", lambda: self.open_profile.emit("Name")),
                                 ("Choose your resume", "Choose resume", lambda: self.open_profile.emit("Documents")),
                                 ("Add your first job", "Paste link", self.focus_paste)]:
            row = QHBoxLayout()
            mark = QLabel()
            mark.setFixedWidth(18)
            row.addWidget(mark)
            row.addWidget(QLabel(text), 1)
            row.addWidget(button(go, action, "ghost"))
            box.addLayout(row)
            self.checklist.append(mark)
        box.addStretch()
        return frame

    def _build_bulk_bar(self):
        self.bulk_bar = QWidget()
        self.bulk_bar.setObjectName("bulkBar")
        row = QHBoxLayout(self.bulk_bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.selection_count = QLabel()
        row.addWidget(self.selection_count)
        self.bulk_buttons = {}
        for action, name in BULK_LABELS.items():
            btn = button(name, lambda _, key=action: self.bulk_action(key),
                         "danger" if action == "delete" else "secondary")
            self.bulk_buttons[action] = btn
            row.addWidget(btn)
        row.addStretch()
        row.addWidget(button("Clear selection", lambda: self.check_visible(False), "ghost"))
        return self.bulk_bar

    def _build_table(self):
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["", "Company", "Role", "Status", "Next step", "Updated"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setAccessibleName("Applications")
        self.table.setMinimumWidth(400)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.select_all_visible = QCheckBox(header.viewport())
        self.select_all_visible.setAccessibleName("Select all visible")
        self.select_all_visible.setToolTip("Select all visible applications")
        self.select_all_visible.clicked.connect(lambda: self.check_visible(len(self._checked_ids) < self.table.rowCount()))
        def position_checkbox(*_):
            self.select_all_visible.move(header.sectionViewportPosition(0) + 8,
                                         (header.height() - self.select_all_visible.height()) // 2)
        self.select_all_visible.adjustSize()
        header.geometriesChanged.connect(position_checkbox)
        self.table.horizontalScrollBar().valueChanged.connect(position_checkbox)
        for column, width in ((0, 40), (1, 148), (2, 164), (3, 178), (5, 80)):
            self.table.setColumnWidth(column, width)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setSortingEnabled(True)
        self.table.viewport().installEventFilter(self)
        self.table.sortByColumn(5, Qt.DescendingOrder)
        self.table.itemSelectionChanged.connect(self.show_selected)
        self.table.itemChanged.connect(self.check_row)
        self.table.doubleClicked.connect(lambda index: self.primary_action() if index.column() else None)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.table)
        empty, empty_layout = card()
        empty_layout.addStretch()
        self.list_empty_title = label("No matching applications", "section")
        empty_layout.addWidget(self.list_empty_title)
        self.list_empty_hint = label(role="muted")
        empty_layout.addWidget(self.list_empty_hint)
        self.reset_filters = button("Show all applications", lambda: (self.show_all(), self.render()))
        empty_layout.addWidget(self.reset_filters, 0, Qt.AlignLeft)
        empty_layout.addStretch()
        self.table_stack.addWidget(empty)
        return self.table_stack

    def _build_detail(self):
        frame, box = card(10)
        frame.setObjectName("inspector")
        self.detail_empty = label("Select an application to see what it needs.", "muted")
        self.detail_empty.setAlignment(Qt.AlignCenter)
        box.addWidget(self.detail_empty, 1)
        self.detail_body = QWidget()
        body = QVBoxLayout(self.detail_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        box.addWidget(self.detail_body, 1)

        self.d_title = label(role="inspectorTitle")
        self.d_role = label(role="muted")
        body.addWidget(self.d_title)
        body.addWidget(self.d_role)
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.d_dot, self.d_status = QLabel(), QLabel()
        self.d_platform = label(role="muted", wrap=False)
        for widget in (self.d_dot, self.d_status):
            status_row.addWidget(widget)
        status_row.addStretch(0)
        self.d_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        body.addLayout(status_row)
        body.addWidget(self.d_platform)
        for widget in (self.d_title, self.d_role, self.d_platform, self.d_status):
            widget.setMinimumWidth(0)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            widget.setWordWrap(True)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.replace_btn = button("Replace link…", self.replace_link, tip="Use a different job or application link")
        self.answer_btn = button("Answer questions", self.details)
        self.review_btn = button("Review application", self.review, tip="See exactly what was filled, then approve and send it")
        self.start_btn = button("Start", self.start_selected, tip="Start or resume (⌘R)")
        self.recheck_btn = button("Recheck", self.start_selected, tip="Read the draft again after you edit it, and refresh the review")
        self.pause_btn = button("Pause", self.pause, tip="Stop adapter writes and pending waits")
        self.submitted_btn = button("I submitted it", self.mark_submitted)
        self.finish_teach_btn = button("Finish teaching", self.finish_teach, tip="Turn what you just did into a recipe for this site")
        self.recipe_btn = button("Review recipe", self.review_recipe, tip="See what the AI learned about this site, then save or discard it")
        self.teach_btn = button("Teach this site", self.teach, tip="Fill this application yourself; Intern-Bot learns the site for next time")
        self.self_teach_btn = button("Fill with AI…", self.ai_teach, tip="The AI fills this application and learns the site for next time")
        self.action_buttons = (self.finish_teach_btn, self.recipe_btn, self.replace_btn, self.answer_btn, self.review_btn, self.teach_btn,
                               self.self_teach_btn, self.start_btn, self.recheck_btn, self.pause_btn)
        self._tips = {widget: widget.toolTip() for widget in self.action_buttons}
        for widget in (*self.action_buttons, self.submitted_btn):
            actions.addWidget(widget)
        actions.addStretch()
        self.detail_menu = QMenu(self)
        self.secondary_actions = {widget: self.detail_menu.addAction(widget.text(), widget.click)
                                  for widget in (*self.action_buttons, self.submitted_btn)}
        self.detail_menu.addSeparator()
        self.detail_menu.addAction("Open job posting", self.open_posting)
        self.report_action = self.detail_menu.addAction("Field report and history…", self.details)
        self.compare_action = self.detail_menu.addAction("Compare profiles with AI…", self.compare_profiles)
        self.replace_action = self.detail_menu.addAction("Replace link…", self.replace_link)
        self.cancel_action = self.detail_menu.addAction("Stop and cancel automation", self.cancel)
        actions.addWidget(more_button(self.detail_menu))

        self.callout = QLabel()
        self.callout.setTextFormat(Qt.PlainText)
        self.callout.setObjectName("callout")
        self.callout.setWordWrap(True)
        self.callout.setMinimumWidth(0)
        self.callout.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        body.addWidget(self.callout)
        body.addLayout(actions)

        body.addSpacing(4)
        self.d_stage = QLabel()
        self.d_bar = QProgressBar()
        self.d_bar.setTextVisible(False)
        self.d_steps = Stepper()
        self.d_progress = label(role="caption")
        for widget in (self.d_stage, self.d_steps, self.d_bar, self.d_progress):
            body.addWidget(widget)

        body.addSpacing(4)
        self.tracking_toggle = QToolButton()
        self.tracking_toggle.setText("Tracking and notes")
        self.tracking_toggle.setCheckable(True)
        self.tracking_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.tracking_toggle.setArrowType(Qt.RightArrow)
        body.addWidget(self.tracking_toggle, 0, Qt.AlignLeft)
        self.tracking = QWidget()
        self.tracking.setVisible(False)
        tracking_layout = QVBoxLayout(self.tracking)
        tracking_layout.setContentsMargins(0, 0, 0, 0)
        def show_tracking(expanded):
            self.tracking.setVisible(expanded)
            self.tracking_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.tracking_toggle.toggled.connect(show_tracking)
        form = form_layout(8)
        self.stage = QComboBox()
        for value in PIPELINE:
            self.stage.addItem(value.title(), value)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Follow-ups, contacts, interview dates…")
        self.notes.setFixedHeight(80)
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("Paste the job description to compare profiles with AI")
        self.description.setMinimumHeight(100)
        form.addRow("Stage", self.stage)
        form.addRow("Notes", self.notes)
        form.addRow("Job description", self.description)
        tracking_layout.addLayout(form)
        body.addWidget(self.tracking)
        self.stage.currentIndexChanged.connect(lambda: self._save_timer.start())
        self.notes.textChanged.connect(self._save_timer.start)
        self.description.textChanged.connect(self._save_timer.start)

        self.recent_events = label(role="caption")
        self.recent_events.setTextFormat(Qt.PlainText)
        body.addWidget(self.recent_events)
        body.addStretch()
        self.d_profile = label(role="caption")
        body.addWidget(self.d_profile)
        footer = QHBoxLayout()
        self.edit_btn = button("Edit application profile…", self.edit_profile, "ghost", "Edit the profile copy this application uses")
        self.delete_btn = button("Delete…", self.delete_selected, "danger", "Delete this application (⌫)")
        footer.addWidget(self.edit_btn)
        footer.addWidget(self.delete_btn)
        footer.addStretch()
        body.addLayout(footer)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(frame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(340)
        scroll.setMaximumWidth(460)
        return scroll

    # State

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_columns()

    def eventFilter(self, source, event):
        if source is self.table.viewport() and event.type() == QEvent.Resize:
            self.fit_columns()
        return super().eventFilter(source, event)

    def fit_columns(self):
        """Keep identity and status visible; the detail pane holds longer next-step text."""
        width = self.table.viewport().width()
        compact = width < 660
        self.table.setColumnHidden(5, compact)
        self.table.setColumnHidden(4, compact)
        header = self.table.horizontalHeader()
        for column, width in ((1, 148), (2, 164)):
            new_mode = QHeaderView.Stretch if compact else QHeaderView.Interactive
            if header.sectionResizeMode(column) != new_mode:
                header.setSectionResizeMode(column, new_mode)
                if not compact:
                    header.resizeSection(column, width)
        header.setSectionResizeMode(4, QHeaderView.Stretch)

    def load_state(self):
        self.tasks = self.store.runs()
        for run in self.tasks:
            if run.status == "running" or run.approved_review:
                # An approval is for one send attempt in this session: an interrupted one never sends after a restart.
                if run.status == "running":
                    run.status = "needs_input"
                    run.interventions = [InterventionRequest(kind="browser", message="Interrupted application. Resume to inspect the saved draft.")]
                run.approved_review = {}
                self.store.save_run(run)
        self.render()

    def _run(self, run_id):
        return next((r for r in self.tasks if r.id == run_id), None)

    def selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self._run(self.table.item(rows[0].row(), 0).data(Qt.UserRole)) if rows else None

    def notify(self, text, tone="info"):
        self.notice.notify(text, tone)

    @staticmethod
    def status_label(run):
        return status_meta(run)[0]

    @staticmethod
    def next_step(run):
        if run.interventions:
            return run.interventions[0].message
        if status_meta(run)[2] == "Applied":
            return run.notes.strip().splitlines()[0] if run.notes.strip() else ""
        if run.status == "ready_for_review":
            return "Review what was filled, then approve & send"
        if run.status == "running":
            return f"{stage_text(run)} · {sum(f.disposition == 'verified' for f in run.fields.values())} fields verified"
        return ""

    def render(self, select_id=None):
        keep = select_id or self._shown_id
        query = self.search.text().strip().casefold()
        group = GROUPS[max(0, self.chips.checkedId())]
        metas = {run.id: status_meta(run) for run in self.tasks}
        visible = [r for r in self.tasks if query in f"{r.company} {r.role} {r.job_url}".casefold() and group in ("All", metas[r.id][2])]
        self._checked_ids.intersection_update(r.id for r in visible)
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(visible))
        for row, run in enumerate(visible):
            text, tone, _ = metas[run.id]
            check = Item("")
            check.setData(Qt.UserRole, run.id)
            check.setData(Qt.AccessibleTextRole, f"Select {run.company or run.job_url} — {run.role}")
            check.setCheckState(Qt.Checked if run.id in self._checked_ids else Qt.Unchecked)
            self.table.setItem(row, 0, check)
            for column, value in enumerate([run.company or site_key(run.job_url), run.role, text, self.next_step(run), ago(run.updated_at)], start=1):
                item = Item(value)
                item.setData(Qt.UserRole, run.id)
                item.setToolTip(run.job_url if column <= 2 else value)
                self.table.setItem(row, column, item)
            self.table.item(row, 3).setIcon(dot_icon(tone))
            self.table.item(row, 5).setData(Qt.UserRole + 1, run.updated_at)
        self.table.setSortingEnabled(True)
        self.table_stack.setCurrentIndex(0 if visible else 1)
        if not visible:
            self.list_empty_title.setText("No matching applications" if self.tasks else "Application queue")
            self.list_empty_hint.setText("Clear your filters or try another search." if self.tasks else "Paste a job link above to prepare your first application.")
            self.reset_filters.setVisible(bool(self.tasks))
        rows = [r for r in range(self.table.rowCount()) if self.table.item(r, 0).data(Qt.UserRole) == keep] or ([0] if visible else [])
        self.table.clearSelection()
        if rows:
            self.table.selectRow(rows[0])
        self.table.blockSignals(False)
        self.show_selected()
        self.refresh_bulk()
        counts = {name: sum(name in ("All", meta[2]) for meta in metas.values()) for name in GROUPS}
        for index, name in enumerate(GROUPS):
            self.chips.button(index).setText(f"{name}  {counts[name]}" if counts[name] else name)
        _, _, submitted, _ = activity(self.tasks)
        ready = sum(r.status == "ready_for_review" and metas[r.id][2] == "Needs you" and not receipt_unconfirmed(r) for r in self.tasks)
        attention = counts["Needs you"] - ready
        self.stats.setText(f"{ready} ready to approve · {attention} need attention" + (f" · {submitted} submitted" if submitted else ""))
        self.body.setCurrentIndex(1 if self.tasks else 0)
        if not self.tasks:
            self.refresh_empty()
        self.changed.emit()

    def refresh_empty(self):
        try:
            profile = ApplicantProfile.model_validate(self.store.get("verified_profile", {}))
        except ValueError:
            profile = ApplicantProfile()
        for mark, done in zip(self.checklist, [profile.first_name and profile.email, profile.resume_path, False]):
            mark.setText("✓" if done else "○")
            restyle(mark, tone="success" if done else "", role="" if done else "muted")

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_paste_profile()
        self.update_workshop()
        if not self.tasks:
            self.refresh_empty()

    def show_selected(self):
        run = self.selected()
        if (run.id if run else None) != self._shown_id:
            if self._save_timer.isActive():
                self.save_tracking(rerender=False)
            self._shown_id = run.id if run else None
            if run:
                self.load_tracking(run)
        self.refresh_detail()
        self.update_workshop()

    def load_tracking(self, run):
        for widget in (self.stage, self.notes, self.description):
            widget.blockSignals(True)
        self.stage.setCurrentIndex(self.stage.findData("applied" if run.is_submitted and run.pipeline == "saved" else run.pipeline))
        self.notes.setPlainText(run.notes)
        self.description.setPlainText(run.job_description)
        for widget in (self.stage, self.notes, self.description):
            widget.blockSignals(False)

    def save_tracking(self, rerender=True):
        self._save_timer.stop()
        run = self._run(self._shown_id)
        if not run or run.id == self._active_id:
            return
        run.pipeline = self.stage.currentData()
        run.notes = self.notes.toPlainText()
        run.job_description = self.description.toPlainText()
        if run.pipeline not in {"saved", "archived"} and not run.submitted_at:
            run.submitted_at = now()
        self.store.save_run(run)
        if rerender:
            self.render()

    def refresh_detail(self):
        run = self._run(self._shown_id)
        self.detail_body.setVisible(bool(run))
        self.detail_empty.setVisible(not run)
        if run:
            text, tone, _ = status_meta(run)
            recent = self.store.recent_events(run.id, 2)
            self.recent_events.setText("\n".join(f"{ago(e['at'])}  ·  {e['note'] or e['kind'].replace('_', ' ')}" for e in recent))
            self.recent_events.setVisible(bool(recent))
            self.d_title.setText(run.company or site_key(run.job_url))
            self.d_role.setText(run.role)
            self.d_dot.setPixmap(dot_icon(tone).pixmap(16, 16))
            self.d_status.setText(text)
            recipe = recipe_for(self.store, run.job_url)
            self.d_platform.setText((ats_name(run.job_url) or (recipe and "Taught site") or "Unrecognized site") + (" · Request mode" if run.mode == "request" else ""))
            messages = [request.question or request.message for request in run.interventions]
            if unsupported(run):
                messages = ["This site needs a filling guide. Teach it once, or choose Fill with AI from More actions."]
            self.callout.setText("\n".join(dict.fromkeys(messages)))
            self.callout.setVisible(bool(messages))
            total = len(run.fields)
            verified = sum(f.disposition == "verified" for f in run.fields.values())
            omitted = sum(f.disposition == "intentionally_omitted" for f in run.fields.values())
            if run.submission_confirmed:
                stage = "Employer receipt confirmed"
            elif run.submitted_by_user:
                stage = "Submission confirmed by you"
            elif receipt_unconfirmed(run):
                stage = "Check employer confirmation"
            elif run.status == "ready_for_review":
                stage = "Application prepared"
            elif run.status == "needs_input" and any(i.question for i in run.interventions):
                stage = "Waiting for your answer"
            else:
                stage = stage_text(run)
            self.d_stage.setText(stage)
            self.d_steps.set_steps(run.steps, run.step)
            self.d_steps.setVisible(bool(run.steps))
            self.d_bar.setVisible(bool(total) and not run.steps)
            self.d_bar.setRange(0, max(total, 1))
            self.d_bar.setValue(verified + omitted)
            details = [f"{verified} of {total} fields verified" if total else "No fields checked yet"]
            if omitted:
                details = [f"{verified + omitted} of {total} fields resolved", f"{verified} verified",
                           f"{omitted} optional {'field' if omitted == 1 else 'fields'} left blank"]
            if run.completed_sections and not run.steps:
                details.append(f"{len(run.completed_sections)} sections done")
            if run.elapsed_seconds:
                details.append(duration(run.elapsed_seconds) + " active")
            self.d_progress.setText(" · ".join(details))
            self.d_bar.setAccessibleName(self.d_progress.text())
            self.d_profile.setText(f"Prepared with profile: {run.profile_name}")
            for widget in (self.stage, self.notes, self.description):
                widget.setEnabled(run.id != self._active_id)
        self.update_actions()

    def update_actions(self):
        run = self._run(self._shown_id)
        busy = bool(self._active_id)
        active = bool(run) and run.id == self._active_id
        done = bool(run) and (run.is_submitted or bool(run.submitted_at) or run.pipeline != "saved")
        idle = bool(run) and not active and not done
        status = run.status if run else ""
        self.pause_btn.setVisible(active)
        sent = bool(run) and receipt_unconfirmed(run)
        ready = idle and status == "ready_for_review" and not sent
        self.start_btn.setText("Check receipt" if sent else "I've verified my account" if run and awaiting_verification(run) else {"needs_input": "Resume", "failed": "Retry", "cancelled": "Restart"}.get(status, "Start"))
        self.start_btn.setVisible(idle and (sent or status in {"queued", "needs_input", "failed", "cancelled"}))
        self.replace_btn.setVisible(idle and not sent and any(i.kind == "link" for i in run.interventions))
        self.answer_btn.setVisible(idle and any(i.question for i in run.interventions))
        self.review_btn.setVisible(ready)
        self.recheck_btn.setVisible(ready)
        teaching = bool(run) and self.service.is_teaching(run.id)
        draft = recipe_for(self.store, run.job_url, approved=False) if run else None
        teachable = idle and not teaching and (unsupported(run) or bool(draft) and status == "needs_input")
        self.finish_teach_btn.setVisible(teaching)
        self.recipe_btn.setVisible(idle and not teaching and bool(draft) and not draft.approved)
        self.teach_btn.setVisible(teachable)
        self.self_teach_btn.setVisible(teachable)
        if teaching:
            for widget in (self.replace_btn, self.answer_btn, self.start_btn, self.recheck_btn, self.review_btn):
                widget.setVisible(False)
        self.submitted_btn.setText("Record employer confirmation" if sent else "I submitted it")
        # After teaching, you submit on a recipe site yourself until it knows the confirmation page.
        self.submitted_btn.setVisible(ready or (idle and sent) or (idle and bool(draft) and status == "needs_input"))
        # The last verified review stays readable while another application runs; only sending waits.
        for widget in (self.replace_btn, self.answer_btn, self.start_btn, self.recheck_btn, self.teach_btn, self.self_teach_btn):
            widget.setEnabled(not busy)
            widget.setToolTip("Another application is running. Pause it or wait." if busy else self._tips[widget])
        primary = next((b for b in self.action_buttons if not b.isHidden()), None)
        self._available_actions = [b for b in (*self.action_buttons, self.submitted_btn) if not b.isHidden()]
        for widget, action in self.secondary_actions.items():
            action.setText(widget.text())
            action.setVisible(widget in self._available_actions and widget is not primary)
            action.setEnabled(widget.isEnabled())
            widget.setVisible(widget is primary)
        for widget in self.action_buttons:
            if widget.property("variant") != ("primary" if widget is primary else "secondary"):
                restyle(widget, variant="primary" if widget is primary else "secondary")
        self.report_action.setEnabled(bool(run) and not busy)
        self.compare_action.setEnabled(bool(run) and not busy)
        self.cancel_action.setEnabled(bool(run) and not done and status != "cancelled")
        self.replace_action.setEnabled(idle and not busy and not sent)
        self.edit_btn.setEnabled(idle and not busy and not run.submission_attempted)
        self.delete_btn.setEnabled(bool(run) and self.eligible(run, "delete"))
        queueable = len(self._queueable())
        self.run_queue.setText(f"Run queue ({queueable})" if queueable else "Run queue")
        self.run_queue.setEnabled(bool(queueable))

    def primary_action(self):
        for widget in self.action_buttons:
            if not widget.isHidden() and widget.isEnabled():
                widget.click()
                return

    def context_menu(self, position):
        menu = QMenu(self)
        for widget in self._available_actions:
            menu.addAction(widget.text(), widget.click).setEnabled(widget.isEnabled())
        menu.addSeparator()
        menu.addActions([action for action in self.detail_menu.actions() if action not in self.secondary_actions.values()])
        menu.addSeparator()
        menu.addAction("Delete application…", self.delete_selected).setEnabled(self.delete_btn.isEnabled())
        menu.exec(self.table.viewport().mapToGlobal(position))

    # Actions

    def focus_paste(self):
        self.paste.setFocus()
        self.paste.selectAll()

    def prepare_pasted(self):
        """Paste → Enter: add the job with the active profile and start exactly that run."""
        url = self.paste.text().strip()
        if not url:
            self.notify("Paste a job link first.", "warning")
            return
        run = ApplicationRun(job_url=url, **{**self.store.get("automation_options", {}), "browser": "chromium"})
        if self.add_task(run):
            self.paste.clear()
            self._start_task(run)

    def add_dialog(self):
        dialog = TaskDialog(self, self.paste.text().strip())
        if dialog.exec() == QDialog.Accepted:
            run = dialog.application()
            if self.add_task(run):
                self.paste.clear()
                if dialog.start_after:
                    self._start_task(run)  # The new run itself, whatever row a search or filter left selected.

    def show_all(self):
        """Clear the search and filter, so the application about to be selected is in the list."""
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.chips.button(0).setChecked(True)

    def add_task(self, run):
        try:
            run.job_url = canonical_url(run.job_url, supported_only=False)
        except ValueError as exc:
            self.notify(str(exc), "danger")
            return False
        identity = job_identity(run.job_url)
        existing = next((r for r in self.tasks if identity in {job_identity(r.job_url), r.listing_url and job_identity(r.listing_url)}), None)
        if existing:
            self.show_all()
            self.render(select_id=existing.id)
            self.notify("This job is already in your list, so the existing application is open.", "warning")
            return False
        # Missing metadata is never a match: two link-only jobs share a blank company and the default role.
        if run.company and any(r.company.casefold() == run.company.casefold() and r.role.casefold() == run.role.casefold() for r in self.tasks):
            if QMessageBox.question(self, "Possible duplicate", "An application with this company and role already exists. Add this different URL as a separate application?") != QMessageBox.Yes:
                return False
        if run.profile_snapshot is None:
            run.profile_name = self.store.get("active_profile", "Default")
            run.profile_snapshot = self.store.profiles()[run.profile_name]
        self.store.save_run(run)
        self.tasks.append(run)
        self.show_all()
        self.render(select_id=run.id)
        return True

    def start_selected(self):
        run = self.selected()
        if run:
            self._start_task(run)
        else:
            self.notify("Select an application first.", "warning")

    def prepare_opportunity(self, opportunity):
        run = ApplicationRun(job_url=opportunity.url, listing_url=opportunity.url,
            company=opportunity.organisation, role=opportunity.title,
            profile_name=opportunity.profile_name, profile_snapshot=opportunity.profile_snapshot.model_copy(deep=True),
            job_description=opportunity.description or opportunity.reason,
            **{**self.store.get("automation_options", {}), "browser": "chromium"})
        if not self.add_task(run):
            return
        if self._active_id:
            self._queue.append(run.id)
            self.notify("Application queued. It will prepare when the current application finishes.")
        else:
            self._start_task(run)

    def check_row(self, item):
        if item.column() == 0:
            run_id = item.data(Qt.UserRole)
            if item.checkState() == Qt.Checked:
                self._checked_ids.add(run_id)
            else:
                self._checked_ids.discard(run_id)
            self.refresh_bulk()

    def check_visible(self, checked):
        self._checked_ids = {self.table.item(row, 0).data(Qt.UserRole)
                             for row in range(self.table.rowCount())} if checked else set()
        self.render()

    def eligible(self, run, action):
        active = run.id == self._active_id or run.status == "running"
        if self.service.is_teaching(run.id):
            return False
        if action == "delete":
            return not active
        if action == "cancel" and active:
            return True
        if run.submission_attempted or run.is_submitted or run.submitted_at or run.pipeline != "saved":
            return False
        if action == "cancel":
            return run.status == "queued" or run.id in self._queue
        if active or awaiting_verification(run):
            return False
        return action == "restart" or run.status == "failed"

    def refresh_bulk(self):
        checked = [r for r in self.tasks if r.id in self._checked_ids]
        self.bulk_bar.setVisible(bool(checked))
        self.selection_count.setText(f"{len(checked)} selected")
        state = Qt.Unchecked if not checked else Qt.Checked if len(checked) == self.table.rowCount() else Qt.PartiallyChecked
        self.select_all_visible.setCheckState(state)
        for action, btn in self.bulk_buttons.items():
            name = BULK_LABELS[action]
            count = sum(self.eligible(r, action) for r in checked)
            suffix = "…" if action in {"restart", "delete"} else ""
            btn.setText(f"{name} ({count}){suffix}")
            btn.setEnabled(count > 0)

    def bulk_action(self, action):
        if self._save_timer.isActive():
            self.save_tracking(rerender=False)
            self.render()
        runs = [r for r in self.tasks if r.id in self._checked_ids and self.eligible(r, action)]
        if not runs:
            return
        if action == "delete":
            self.delete_runs(runs, checked_only=True)
            return
        if action == "restart":
            if QMessageBox.question(self, "Restart from beginning?",
                    f"Restart the selected tasks ({len(runs)}) from their job postings and clear local progress and send approvals? "
                    "Your notes and answers are kept. The employer may restore its own draft.",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        ids = {r.id for r in runs}
        affected = 0
        for run in self.tasks:
            # A modal confirmation can process progress signals and change eligibility.
            if run.id not in ids or run.id not in self._checked_ids or not self.eligible(run, action):
                continue
            if action == "cancel":
                self.cancel_run(run)
            else:
                run.approved_review = {}
                if action == "restart":
                    run.status, run.stage = "queued", "start"
                    run.fields, run.interventions, run.completed_sections = {}, [], []
                    run.steps, run.step = [], -1
                    run.profile_revision = run.resume_digest = run.documents_digest = run.engine_version = ""
                    run.elapsed_seconds = run.intervention_count = run.ai_requests = 0
                    self.store.record_event(run.id, "restart", run.stage, "Restarted from the job posting.")
                self.store.save_run(run)
                if run.id not in self._queue:
                    self._queue.append(run.id)
            self._checked_ids.discard(run.id)
            affected += 1
        self.render()
        result = {"retry": "Queued for retry", "restart": "Queued to restart", "cancel": "Cancellation requested"}
        self.notify(f"{result[action]}: {affected} selected.")
        self._start_next()

    def _queueable(self):
        return [r for r in self.tasks if r.status in {"queued", "failed"} and self.eligible(r, "restart")]

    def start_all_tasks(self):
        self._queue = [r.id for r in self._queueable()]
        self._start_next()

    def _start_next(self):
        if self._closing or self._active_id:
            return
        while self._queue and not self._active_id:
            run_id = self._queue.pop(0)
            run = self._run(run_id)
            if run and run.status in {"queued", "failed"} and self.eligible(run, "restart"):
                run.approved_review = {}
                self._start_task(run)

    def _start_task(self, run, inspect_only=False):
        if inspect_only and self.service.show_browser(run.id):
            return
        if self._active_id:
            self.notify("Another application is running. Pause it or wait before starting this one.", "warning")
            return
        if run.is_submitted or run.submitted_at or run.pipeline != "saved":
            self.notify("This application is already in your pipeline and won't restart.", "warning")
            return
        try:
            profile = run.profile_snapshot or ApplicantProfile.model_validate(self.store.get("verified_profile", {}))
            credential = None
            if ats_name(run.job_url) == "Workday":
                vault = self.store._vault()
                if awaiting_verification(run):
                    # The user confirmed the emailed link, so the new account gets exactly one sign-in attempt.
                    vault.set_account_state(run.job_url, "verified")
                    run.authentication_attempted = False
                    self.store.save_run(run)
                # ponytail: op runs on the GUI thread (about a second of network), move to a worker if it gets noticeable.
                credential = vault.credential(run.job_url)
                # Request mode only signs in; it never creates accounts.
                if not credential and run.mode == "classic" and self.store.get("auto_create_workday_accounts", False):
                    # 1Password generates and stores the password before the browser sees it, so it can never be lost.
                    username = login_address(site_key(run.job_url), profile.email, self.store.get("catchall_domain", ""), self.store.get("catchall_format", ""))
                    vault.save_credential(run.job_url, username, None, "new")
                    credential = vault.credential(run.job_url)
            if self.service.start(run.model_copy(deep=True), profile, credential, inspect_only=inspect_only):
                self._active_id = run.id
                run.work_phase = "intake"
                self._queue = [i for i in self._queue if i != run.id]
                run.status = "running"
                run.interventions = []
                self.render()
                self.notify("Rechecking the draft, then sending it if it still matches what you approved." if run.approved_review else
                            "Preparing the application in Chromium. The employer may ask you to sign in again. Nothing is sent until you approve it.")
        except Exception as exc:
            run.status = "failed"
            # RuntimeErrors carry 1Password or keychain setup steps and never contain secrets.
            message = str(exc) if isinstance(exc, RuntimeError) else f"Check the profile, URL and operating-system keychain ({type(exc).__name__})."
            run.interventions = [InterventionRequest(kind="browser", message=message)]
            self.store.save_run(run)
            self.render()

    def on_progress(self, run):
        for index, previous in enumerate(self.tasks):
            if previous.id == run.id:
                self.tasks[index] = run
                break
        self.render()

    def on_finished(self, run):
        self.on_progress(run)
        self._active_id = None
        self.render()
        stopped, self._stopped_id = run.id == self._stopped_id, None
        if run.status in FINISHED and not self._closing:
            message, tone = FINISHED[run.status]
            name = run.company or "The application"
            title = {"needs_input": "Intern-Bot needs your input", "ready_for_review": "Ready to approve"}.get(run.status)
            text = message.format(run.company or site_key(run.job_url))
            if run.is_submitted:
                message, tone, title = "{} was submitted. The employer's confirmation was recognized.", "success", "Application submitted"
                text = message.format(run.company or site_key(run.job_url))
            elif receipt_unconfirmed(run):
                message, tone, title = "{} was sent once, but no employer receipt was recognized. Check it in the browser; Intern-Bot won't send it again.", "warning", "Check the employer receipt"
                text = message.format(run.company or site_key(run.job_url))
            elif awaiting_verification(run):
                name = run.company or site_key(run.job_url)
                message, title = "Verify the Workday email for {}, then click I've verified my account.", "Verify your Workday email"
                text = f"{name}: open the verification link, then click I've verified my account in Intern-Bot."
            self.notify(message.format(name), tone)
            if title and not stopped:
                desktop_notification(title, text)  # Once per finish, so a job waiting on you reaches you away from the window.
            QApplication.alert(self.window())
        self._start_next()

    def pause(self):
        self._queue = []
        if self._active_id:
            self._stopped_id = self._active_id
            self.service.pause(self._active_id)
            self.notify("Pausing: stopping adapter writes and pending waits.")

    def cancel(self):
        run = self.selected()
        if run:
            self.cancel_run(run)
            self.render()

    def cancel_run(self, run):
        self._queue = [i for i in self._queue if i != run.id]
        if run.id == self._active_id:
            self._stopped_id = run.id
            self.service.pause(run.id, cancel=True)
        else:
            run.status = "cancelled"
            run.approved_review = {}
            self.store.save_run(run)

    def details(self):
        run = self.selected()
        if not run or self._active_id:
            self.notify("Select an application and pause any active one before editing answers.", "warning")
            return
        if RunDetailsDialog(self.store, run, self).exec() == QDialog.Accepted:
            self._start_task(run)

    def review(self):
        """The application exactly as filled; Approve & send is the only way it gets sent."""
        run = self.selected()
        if not run or run.status != "ready_for_review" or receipt_unconfirmed(run):
            return
        dialog = ReviewDialog(self.store, run, can_send=not self._active_id, parent=self)
        result = dialog.exec()
        if result == ReviewDialog.EDIT:
            if self.service.show_browser(run.id):
                self.notify("Edit the form in Chromium, then click Recheck to refresh the review.")
            else:
                self._start_task(run, inspect_only=True)  # The browser closed (or the app restarted): reopen the draft.
        elif result == QDialog.Accepted:
            self.approve_and_send(run, dialog.ai_ids)

    def approve_and_send(self, run, ai_ids=()):
        if self._active_id or run.submission_attempted or run.is_submitted:
            self.notify("This application can't be sent from here now." if run.submission_attempted else "Another application is running. Send this one when it finishes.", "warning")
            return
        for answer in self.store.answers():
            if answer.id in ai_ids and answer.origin == "ai":
                answer.origin = "you"  # You saw it in the review and approved it.
                self.store.save_answer(answer)
        run.approved_review = review_values(run)
        self.store.record_event(run.id, "approved", run.stage, f"You approved {len(run.approved_review) - 1} reviewed fields for sending.")
        self.store.save_run(run)
        self._start_task(run)

    def replace_link(self):
        run = self.selected()
        if not run or run.id == self._active_id or receipt_unconfirmed(run) or run.is_submitted:
            return
        options = next((i.options for i in run.interventions if i.kind == "link" and i.options), []) or [run.job_url]
        url, ok = QInputDialog.getItem(self, "Replace link", "Job posting or application link:", options, 0, True)
        if not ok or not url.strip():
            return
        try:
            url = canonical_url(url.strip(), supported_only=False)
        except ValueError as exc:
            self.notify(str(exc), "danger")
            return
        other = next((r for r in self.tasks if r.id != run.id and job_identity(url) in {job_identity(r.job_url), r.listing_url and job_identity(r.listing_url)}), None)
        if other:
            self.render(select_id=other.id)
            self.notify("That job is already in your list, so the existing application is open.", "warning")
            return
        run.listing_url = run.listing_url or (run.job_url if job_identity(url) != job_identity(run.job_url) else "")
        run.job_url, run.fields, run.completed_sections, run.steps, run.step, run.stage = url, {}, [], [], -1, "start"
        run.status, run.interventions, run.approved_review = "queued", [], {}
        self.store.record_event(run.id, "link_replaced", run.stage, f"Now applying through {site_key(url)}.")
        self.store.save_run(run)
        self._start_task(run)

    def compare_profiles(self):
        from gui.views.assistant_dialog import AssistantDialog
        run = self.selected()
        if not run or self._active_id:
            self.notify("Select an inactive application. Paste its job description first for a useful comparison.", "warning")
            return
        AssistantDialog(self.store, run, mode="compare", parent=self).exec()

    def edit_profile(self):
        run = self.selected()
        if not run or self._active_id or run.is_submitted or run.submission_attempted or run.pipeline != "saved":
            self.notify("Select an inactive application to edit its profile.", "warning")
            return
        profile = run.profile_snapshot or ApplicantProfile.model_validate(self.store.get("verified_profile", {}))
        dialog = ProfileDialog(profile, self)
        if dialog.exec() == QDialog.Accepted:
            run.profile_snapshot = dialog.profile()
            run.status = "needs_input"
            self.store.save_run(run)
            self.render()
            self.notify("Profile snapshot saved. Intern-Bot rechecks the first section when you resume.", "success")

    def mark_submitted(self):
        run = self.selected()
        if not run or run.id == self._active_id:
            return
        if QMessageBox.question(self, "Record manual submission", "Have you submitted this application yourself and seen confirmation from the employer?") != QMessageBox.Yes:
            return
        run.submitted_by_user = True
        run.submitted_at = run.submitted_at or now()
        run.pipeline = "applied"
        self._queue = [i for i in self._queue if i != run.id]
        self.store.record_event(run.id, "submitted_by_user", run.stage, "User confirmed employer submission receipt.")
        self.store.save_run(run)
        try:
            heading = self.service.capture_receipt(run.id)
        except Exception:
            heading = ""  # The tab closed or moved on; the recipe learns its confirmation page next time.
        if heading:
            self.store.record_event(run.id, "recipe_receipt", run.stage, f"This site's recipe now recognizes its confirmation page (“{heading}”).")
        self._shown_id = None  # reload the tracking fields with the new stage
        self.render(select_id=run.id)
        self.notify("Recorded as submitted. Track its stage and notes here.", "success")

    # Site recipes

    def _profile(self, run):
        return run.profile_snapshot or ApplicantProfile.model_validate(self.store.get("verified_profile", {}))

    def teach(self):
        run = self.selected()
        if not run or self._active_id:
            self.notify("Pause the running application before teaching a site.", "warning")
            return
        if not self.service.teach_start(run.id):
            self.notify("Resume the application first so it's open in Chromium, then teach it.", "warning")
            return
        self.render()
        self.notify("Teaching: fill in the application in Chromium and click through it as usual (submitting is up to you). Then click Finish teaching.")

    def finish_teach(self):
        run = self.selected()
        if not run:
            return
        result = self.service.teach_finish(run.id)
        self.render()
        if not result or not result[0]:
            self.notify("Nothing was learned: the Chromium tab closed or no button was clicked while teaching.", "warning")
            return
        captures, final = result
        recipe, proposals = build_from_capture(site_key(final["url"]), captures, final, self._profile(run), run, self.store.answers())
        previous = recipe_for(self.store, final["url"], approved=False)
        recipe = previous.merged(recipe) if previous else recipe
        if RecipeReviewDialog(self.store, recipe, proposals, self).exec() == QDialog.Accepted:
            self.notify(f"Recipe saved. New applications on {recipe.host} fill from it. If you submitted this one, press I submitted it.", "success")
        self.render()

    def ai_teach(self):
        run = self.selected()
        if not run or self._active_id:
            self.notify("Pause the running application before letting AI teach itself.", "warning")
            return
        try:
            cfg = ai_config(self.store)
        except Exception:
            cfg = None
        if not cfg:
            self.notify("Set up an AI provider in Settings first.", "warning")
            return
        host = site_key(run.job_url)
        consented = self.store.get("self_teach_consent", [])
        if host not in consented:
            if QMessageBox.question(self, f"Let AI teach itself — {host}", consent_text(cfg)) != QMessageBox.Yes:
                return
            self.store.put("self_teach_consent", consented + [host])
        if not self.service.self_teach(run.model_copy(deep=True), self._profile(run), cfg):
            self.notify("Resume the application first so it's open in Chromium, then let AI teach itself.", "warning")
            return
        self._active_id = run.id
        run.status, run.interventions = "running", []
        self.render()
        self.notify("The AI is filling the application in Chromium. It stops at the review page and never submits.")

    def review_recipe(self):
        run = self.selected()
        draft = run and recipe_for(self.store, run.job_url, approved=False)
        if draft and not draft.approved and RecipeReviewDialog(self.store, draft, (), self).exec() == QDialog.Accepted:
            self.notify(f"Recipe saved. New applications on {draft.host} fill from it.", "success")
        self.render()

    def delete_selected(self):
        run = self.selected()
        if not run or run.id == self._active_id:
            self.notify("Select an inactive application to delete.", "warning")
            return
        self.delete_runs([run])

    def delete_runs(self, runs, checked_only=False):
        names = "\n".join(f"• {r.company or site_key(r.job_url)} — {r.role} ({r.job_url})" for r in runs)
        prompt = QMessageBox(QMessageBox.Question, "Delete selected tasks?",
                             f"Delete the selected local records ({len(runs)}) and their history? Saved answers are kept.",
                             QMessageBox.Yes | QMessageBox.No, self)
        prompt.setTextFormat(Qt.PlainText)
        prompt.setDefaultButton(QMessageBox.No)
        if len(runs) > 6:
            prompt.setDetailedText(names)
        else:
            prompt.setInformativeText(names)
        if prompt.exec() != QMessageBox.Yes:
            return
        if self._save_timer.isActive():
            self.save_tracking(rerender=False)
        ids = {r.id for r in runs}
        if checked_only:
            ids.intersection_update(self._checked_ids)
        ids = {r.id for r in self.tasks if r.id in ids and self.eligible(r, "delete")}
        self.store.delete_runs(ids)
        self._queue = [i for i in self._queue if i not in ids]
        self.tasks = [r for r in self.tasks if r.id not in ids]
        self.render()
        self.notify(f"Local tasks deleted: {len(ids)}.", "success")

    def open_posting(self):
        run = self.selected()
        if run:
            QDesktopServices.openUrl(QUrl(run.listing_url or run.job_url))

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import applications", "", "CSV (*.csv)")
        if path:
            try:
                added, skipped = import_csv(self.store, path)
            except (ValueError, OSError) as exc:
                self.notify(str(exc), "danger")
                return
            self.load_state()
            self.notify(f"Imported {added} and skipped {skipped} duplicate URLs. Imports never start an application.", "success")

    def export_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export applications", "applications.csv", "CSV (*.csv)")
        if path:
            try:
                export_csv(self.store.runs(), path)
                self.notify("Applications exported.", "success")
            except OSError:
                self.notify("Couldn't write the CSV. Check file access.", "danger")

    def shutdown(self):
        self._closing = True
        self._queue = []
        if self._save_timer.isActive():
            self.save_tracking(rerender=False)
        self.service.shutdown()
