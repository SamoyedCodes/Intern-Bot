"""Applications workspace: one list, one detail panel, one sequential queue."""
import subprocess
import sys
from datetime import datetime, timezone

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QScrollArea,
    QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.automation.accounts import generate_login
from core.automation.models import ApplicantProfile, ApplicationRun, InterventionRequest, ats_name, canonical_url, job_identity, now, site_key
from core.automation.service import AutomationService
from core.storage.local_store import LocalStore
from core.tracker import PIPELINE, activity, export_csv, import_csv
from gui.theme import form_layout, MessageBar, button, card, dot_icon, label, more_button, restyle, shortcut
from gui.views.application_dialogs import ProfileDialog, RunDetailsDialog

GROUPS = ("All", "Needs you", "In progress", "Applied", "Closed")
STATUS = {
    "queued": ("Queued", "neutral", "In progress"),
    "running": ("Running…", "info", "In progress"),
    "ready_for_review": ("Ready for review", "accent", "Needs you"),
    "failed": ("Failed", "danger", "Needs you"),
    "cancelled": ("Cancelled", "neutral", "Closed"),
}
FINISHED = {
    "needs_input": ("{} needs your input.", "warning"),
    "ready_for_review": ("{} is ready for review in the browser. Submitting stays with you.", "success"),
    "failed": ("{} stopped with an error. Open it to see why.", "danger"),
}


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
    if run.stage == "start":
        return "Not started"
    stage = "Application form" if run.stage.startswith("form_") else run.stage.replace("_", " ")
    return stage[:1].upper() + stage[1:]


def duration(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes} min {seconds} s" if minutes else f"{seconds} s"


class Item(QTableWidgetItem):
    """Sorts by its UserRole + 1 key when present (timestamps), otherwise by text."""

    def __lt__(self, other):
        mine, theirs = self.data(Qt.UserRole + 1), other.data(Qt.UserRole + 1)
        return mine < theirs if mine is not None and theirs is not None else super().__lt__(other)


class TaskDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = parent.store if parent else LocalStore()
        self.start_after = False
        self.setWindowTitle("New application")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label("New application", "section"))
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
        layout.addLayout(form)
        layout.addSpacing(4)
        layout.addWidget(label("Advanced", "overline"))
        self.auto_submit = QCheckBox("Submit automatically once every field and the review are verified")
        layout.addWidget(self.auto_submit)
        layout.addWidget(label("Off by default. If you turn it on, you'll be asked to authorize this one application, and Intern-Bot stops if anything can't be verified.", "caption"))
        self.error = label()
        self.error.setProperty("tone", "danger")
        layout.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(button("Cancel", self.reject, "ghost"))
        buttons.addWidget(button("Add", lambda: self.validate(False)))
        add_and_start = button("Add and start", lambda: self.validate(True), "primary")
        add_and_start.setDefault(True)
        buttons.addWidget(add_and_start)
        layout.addLayout(buttons)
        clipboard = QGuiApplication.clipboard().text().strip()
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
        if self.auto_submit.isChecked() and QMessageBox.question(self, "Authorize this application", "Allow Intern-Bot to submit this specific application using the selected profile and approved answers? It will stop if anything cannot be verified.") != QMessageBox.Yes:
            return
        self.start_after = start
        self.accept()

    def application(self):
        return ApplicationRun(job_url=canonical_url(self.url.text().strip(), supported_only=False),
                              company=self.company.text().strip(), role=self.role.text().strip() or "Internship",
                              profile_name=self.profile.currentText(), profile_snapshot=self.store.profiles()[self.profile.currentText()],
                              auto_submit=self.auto_submit.isChecked(), **{**self.store.get("automation_options", {}), "browser": "chromium"})


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
        self._queue = []
        self._active_id = None
        self._closing = False
        self._shown_id = None
        self._save_timer = QTimer(self, singleShot=True, interval=600, timeout=self.save_tracking)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addLayout(self._build_header())
        layout.addLayout(self._build_chips())
        self.notice = MessageBar()
        layout.addWidget(self.notice)
        self.body = QStackedWidget()
        self.body.addWidget(self._build_empty())
        splitter = QSplitter()
        splitter.setHandleWidth(12)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_detail())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([640, 400])
        self.body.addWidget(splitter)
        layout.addWidget(self.body, 1)
        for keys in (QKeySequence(Qt.Key_Return), QKeySequence(Qt.Key_Enter)):
            shortcut(keys, self.table, self.primary_action, Qt.WidgetShortcut)
        for keys in (QKeySequence.Delete, QKeySequence(Qt.Key_Backspace)):
            shortcut(keys, self.table, self.delete_selected, Qt.WidgetShortcut)
        self.load_state()

    # Layout

    def _build_header(self):
        row = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("Applications", "pageTitle"))
        self.stats = label(role="muted")
        titles.addWidget(self.stats)
        row.addLayout(titles, 1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search company, role or URL")
        self.search.setAccessibleName("Search applications")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(lambda: self.render())
        row.addWidget(self.search)
        self.run_queue = button("Run queue", self.start_all_tasks, tip="Start every queued or failed application, one at a time")
        row.addWidget(self.run_queue)
        row.addWidget(button("New application", self.add_dialog, "primary", "New application (⌘N)"))
        menu = QMenu(self)
        menu.addAction("Import CSV…", self.import_file)
        menu.addAction("Export CSV…", self.export_file)
        row.addWidget(more_button(menu, "Import and export"))
        return row

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
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.addStretch()
        frame, box = card(10)
        frame.setMaximumWidth(520)
        box.addWidget(label("Get set up", "section"))
        box.addWidget(label("Intern-Bot fills in applications from your profile, asks you about anything it can't verify, and leaves the final submission to you.", "muted"))
        self.checklist = []
        for text, go, action in [("Add your name and email", "Edit profile", lambda: self.open_profile.emit("Name")),
                                 ("Choose your resume", "Choose resume", lambda: self.open_profile.emit("Documents")),
                                 ("Add your first job", "Add job", self.add_dialog)]:
            row = QHBoxLayout()
            mark = QLabel()
            mark.setFixedWidth(18)
            row.addWidget(mark)
            row.addWidget(QLabel(text), 1)
            row.addWidget(button(go, action, "ghost"))
            box.addLayout(row)
            self.checklist.append(mark)
        center = QHBoxLayout()
        center.addStretch()
        center.addWidget(frame, 1)
        center.addStretch()
        outer.addLayout(center)
        outer.addStretch()
        return page

    def _build_table(self):
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Company", "Role", "Status", "Next step", "Updated"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        for column, width in ((0, 120), (1, 130), (2, 150), (4, 80)):
            self.table.setColumnWidth(column, width)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(4, Qt.DescendingOrder)
        self.table.itemSelectionChanged.connect(self.show_selected)
        self.table.doubleClicked.connect(lambda _: self.primary_action())
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        return self.table

    def _build_detail(self):
        frame, box = card(10)
        self.detail_empty = label("Select an application to see what it needs.", "muted")
        self.detail_empty.setAlignment(Qt.AlignCenter)
        box.addWidget(self.detail_empty, 1)
        self.detail_body = QWidget()
        body = QVBoxLayout(self.detail_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        box.addWidget(self.detail_body, 1)

        self.d_title = label(role="section")
        self.d_role = label(role="muted")
        body.addWidget(self.d_title)
        body.addWidget(self.d_role)
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.d_dot, self.d_status = QLabel(), QLabel()
        self.d_platform = label(role="muted", wrap=False)
        for widget in (self.d_dot, self.d_status, self.d_platform):
            status_row.addWidget(widget)
        status_row.addStretch()
        status_row.addWidget(button("Open posting ↗", self.open_posting, "ghost", "Open the job posting in your default browser"))
        body.addLayout(status_row)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.answer_btn = button("Answer questions", self.details)
        self.review_btn = button("Review in browser", self.start_selected, tip="Bring the prepared form to the front. Final submission stays with you.")
        self.start_btn = button("Start", self.start_selected, tip="Start or resume (⌘R)")
        self.pause_btn = button("Pause", self.pause, tip="Stop adapter writes and pending waits")
        self.submitted_btn = button("I submitted it", self.mark_submitted)
        self.action_buttons = (self.answer_btn, self.review_btn, self.start_btn, self.pause_btn)
        self._tips = {widget: widget.toolTip() for widget in self.action_buttons}
        for widget in (*self.action_buttons, self.submitted_btn):
            actions.addWidget(widget)
        actions.addStretch()
        self.detail_menu = QMenu(self)
        self.report_action = self.detail_menu.addAction("Field report and history…", self.details)
        self.compare_action = self.detail_menu.addAction("Compare profiles with AI…", self.compare_profiles)
        self.cancel_action = self.detail_menu.addAction("Stop and cancel automation", self.cancel)
        actions.addWidget(more_button(self.detail_menu))
        body.addLayout(actions)

        self.callout = QLabel()
        self.callout.setObjectName("callout")
        self.callout.setWordWrap(True)
        body.addWidget(self.callout)

        body.addSpacing(4)
        body.addWidget(label("Progress", "overline"))
        self.d_stage = QLabel()
        self.d_bar = QProgressBar()
        self.d_bar.setTextVisible(False)
        self.d_progress = label(role="caption")
        for widget in (self.d_stage, self.d_bar, self.d_progress):
            body.addWidget(widget)

        body.addSpacing(4)
        body.addWidget(label("Tracking", "overline"))
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
        body.addLayout(form)
        self.stage.currentIndexChanged.connect(lambda: self._save_timer.start())
        self.notes.textChanged.connect(self._save_timer.start)
        self.description.textChanged.connect(self._save_timer.start)

        footer = QHBoxLayout()
        self.d_profile = label(role="caption")
        footer.addWidget(self.d_profile, 1)
        self.edit_btn = button("Edit snapshot…", self.edit_profile, "ghost", "Edit the profile copy this application uses")
        self.delete_btn = button("Delete…", self.delete_selected, "danger", "Delete this application (⌫)")
        footer.addWidget(self.edit_btn)
        footer.addWidget(self.delete_btn)
        body.addLayout(footer)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(frame)
        scroll.setMinimumWidth(340)
        scroll.setMaximumWidth(460)
        return scroll

    # State

    def load_state(self):
        self.tasks = self.store.runs()
        for run in self.tasks:
            if run.status == "running":
                run.status = "needs_input"
                run.interventions = [InterventionRequest(kind="browser", message="Interrupted application. Resume to inspect the saved draft.")]
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
            return "Check the form in the browser, then submit it yourself"
        if run.status == "running":
            return f"{stage_text(run)} · {sum(f.disposition == 'verified' for f in run.fields.values())} fields verified"
        return ""

    def render(self, select_id=None):
        keep = select_id or self._shown_id
        query = self.search.text().strip().casefold()
        group = GROUPS[max(0, self.chips.checkedId())]
        metas = {run.id: status_meta(run) for run in self.tasks}
        visible = [r for r in self.tasks if query in f"{r.company} {r.role} {r.job_url}".casefold() and group in ("All", metas[r.id][2])]
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(visible))
        for row, run in enumerate(visible):
            text, tone, _ = metas[run.id]
            for column, value in enumerate([run.company or site_key(run.job_url), run.role, text, self.next_step(run), ago(run.updated_at)]):
                item = Item(value)
                item.setData(Qt.UserRole, run.id)
                item.setToolTip(run.job_url if column < 2 else value)
                self.table.setItem(row, column, item)
            self.table.item(row, 2).setIcon(dot_icon(tone))
            self.table.item(row, 4).setData(Qt.UserRole + 1, run.updated_at)
        self.table.setSortingEnabled(True)
        rows = [r for r in range(self.table.rowCount()) if self.table.item(r, 0).data(Qt.UserRole) == keep] or ([0] if visible else [])
        self.table.clearSelection()
        if rows:
            self.table.selectRow(rows[0])
        self.table.blockSignals(False)
        self.show_selected()
        counts = {name: sum(name in ("All", meta[2]) for meta in metas.values()) for name in GROUPS}
        for index, name in enumerate(GROUPS):
            self.chips.button(index).setText(f"{name}  {counts[name]}" if counts[name] else name)
        _, _, submitted, interviews = activity(self.tasks)
        self.stats.setText(f"{submitted} submitted · {interviews} interviewing or offer ({interviews / submitted:.0%})" if submitted else "Nothing submitted yet")
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
            self.d_title.setText(run.company or site_key(run.job_url))
            self.d_role.setText(run.role)
            self.d_dot.setPixmap(dot_icon(tone).pixmap(16, 16))
            self.d_status.setText(text)
            self.d_platform.setText("· " + (ats_name(run.job_url) or "Unrecognized site"))
            messages = [request.message for request in run.interventions]
            self.callout.setText("\n".join(messages))
            self.callout.setVisible(bool(messages))
            total = len(run.fields)
            verified = sum(f.disposition == "verified" for f in run.fields.values())
            self.d_stage.setText(stage_text(run))
            self.d_bar.setVisible(bool(total))
            self.d_bar.setRange(0, max(total, 1))
            self.d_bar.setValue(verified)
            details = [f"{verified} of {total} fields verified" if total else "No fields checked yet"]
            if run.completed_sections:
                details.append("Done: " + ", ".join(run.completed_sections))
            if run.elapsed_seconds:
                details.append(duration(run.elapsed_seconds) + " active")
            self.d_progress.setText(" · ".join(details))
            self.d_profile.setText(f"Profile snapshot: {run.profile_name}")
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
        self.start_btn.setText("I've verified my account" if run and awaiting_verification(run) else {"needs_input": "Resume", "failed": "Retry", "cancelled": "Restart"}.get(status, "Start"))
        self.start_btn.setVisible(idle and status in {"queued", "needs_input", "failed", "cancelled"})
        self.answer_btn.setVisible(idle and any(i.question for i in run.interventions))
        self.review_btn.setVisible(idle and status == "ready_for_review")
        self.submitted_btn.setVisible(idle and status == "ready_for_review")
        for widget in (self.answer_btn, self.review_btn, self.start_btn):
            widget.setEnabled(not busy)
            widget.setToolTip("Another application is running. Pause it or wait." if busy else self._tips[widget])
        primary = next((b for b in self.action_buttons if not b.isHidden()), None)
        for widget in self.action_buttons:
            if widget.property("variant") != ("primary" if widget is primary else "secondary"):
                restyle(widget, variant="primary" if widget is primary else "secondary")
        self.report_action.setEnabled(bool(run) and not busy)
        self.compare_action.setEnabled(bool(run) and not busy)
        self.cancel_action.setEnabled(bool(run) and not done and status != "cancelled")
        self.edit_btn.setEnabled(idle and not busy and not run.submission_attempted)
        self.delete_btn.setEnabled(bool(run) and not active)
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
        for widget in (*self.action_buttons, self.submitted_btn):
            if not widget.isHidden():
                menu.addAction(widget.text(), widget.click).setEnabled(widget.isEnabled())
        menu.addSeparator()
        menu.addActions(self.detail_menu.actions())
        menu.addSeparator()
        menu.addAction("Delete application…", self.delete_selected).setEnabled(self.delete_btn.isEnabled())
        menu.exec(self.table.viewport().mapToGlobal(position))

    # Actions

    def add_dialog(self):
        dialog = TaskDialog(self)
        if dialog.exec() == QDialog.Accepted and self.add_task(dialog.application()) and dialog.start_after:
            self.start_selected()

    def add_task(self, run):
        try:
            run.job_url = canonical_url(run.job_url, supported_only=False)
        except ValueError as exc:
            self.notify(str(exc), "danger")
            return False
        existing = next((r for r in self.tasks if job_identity(r.job_url) == job_identity(run.job_url)), None)
        if existing:
            self.render(select_id=existing.id)
            self.notify("This job is already in your list, so the existing application is selected.", "warning")
            return False
        if any(r.company.casefold() == run.company.casefold() and r.role.casefold() == run.role.casefold() for r in self.tasks):
            if QMessageBox.question(self, "Possible duplicate", "An application with this company and role already exists. Add this different URL as a separate application?") != QMessageBox.Yes:
                return False
        if run.profile_snapshot is None:
            run.profile_name = self.store.get("active_profile", "Default")
            run.profile_snapshot = self.store.profiles()[run.profile_name]
        self.store.save_run(run)
        self.tasks.append(run)
        self.render(select_id=run.id)
        return True

    def start_selected(self):
        run = self.selected()
        if run:
            self._start_task(run)
        else:
            self.notify("Select an application first.", "warning")

    def _queueable(self):
        return [r for r in self.tasks if r.status in {"queued", "failed"} and not r.is_submitted and not r.submitted_at and r.pipeline == "saved" and r.id != self._active_id]

    def start_all_tasks(self):
        self._queue = [r.id for r in self._queueable()]
        self._start_next()

    def _start_next(self):
        if self._closing or self._active_id:
            return
        while self._queue and not self._active_id:
            run_id = self._queue.pop(0)
            run = self._run(run_id)
            if run:
                self._start_task(run)

    def _start_task(self, run):
        if self._active_id:
            self.notify("Another application is running. Pause it or wait before starting this one.", "warning")
            return
        if run.is_submitted or run.submitted_at or run.pipeline != "saved":
            self.notify("This application is already in your pipeline and won't restart.", "warning")
            return
        inspect_only = run.status == "ready_for_review"
        if inspect_only and self.service.show_browser(run.id):
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
                credential = vault.credential(run.job_url)
                if not credential and self.store.get("auto_create_workday_accounts", False):
                    # Saved before the browser sees it, so a generated password can never be lost.
                    username, password = generate_login(site_key(run.job_url), profile.email, self.store.get("catchall_domain", ""), self.store.get("catchall_format", ""))
                    vault.save_credential(run.job_url, username, password, "new")
                    credential = vault.credential(run.job_url)
            if self.service.start(run.model_copy(deep=True), profile, credential, inspect_only=inspect_only):
                self._active_id = run.id
                self._queue = [i for i in self._queue if i != run.id]
                run.status = "running"
                run.interventions = []
                self.render()
                self.notify("Preparing the application in Chromium. The employer may ask you to sign in again. " + ("Automatic submission is authorized for this job." if run.auto_submit else "Final submission stays with you."))
        except Exception as exc:
            run.status = "failed"
            run.interventions = [InterventionRequest(kind="browser", message=f"Check the profile, URL and operating-system keychain ({type(exc).__name__}).")]
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
        if run.status in FINISHED and not self._closing:
            message, tone = FINISHED[run.status]
            name = run.company or "The application"
            if awaiting_verification(run):
                name = run.company or site_key(run.job_url)
                message = "Verify the Workday email for {}, then click I've verified my account."
                desktop_notification("Verify your Workday email", f"{name}: open the verification link, then click I've verified my account in Intern-Bot.")
            self.notify(message.format(name), tone)
            QApplication.alert(self.window())
        self._start_next()

    def pause(self):
        self._queue = []
        if self._active_id:
            self.service.pause(self._active_id)
            self.notify("Pausing: stopping adapter writes and pending waits.")

    def cancel(self):
        run = self.selected()
        if not run:
            return
        self._queue = [i for i in self._queue if i != run.id]
        if run.id == self._active_id:
            self.service.pause(run.id, cancel=True)
        else:
            run.status = "cancelled"
            self.store.save_run(run)
            self.render()

    def details(self):
        run = self.selected()
        if not run or self._active_id:
            self.notify("Select an application and pause any active one before editing answers.", "warning")
            return
        if RunDetailsDialog(self.store, run, self).exec() == QDialog.Accepted:
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
        self._shown_id = None  # reload the tracking fields with the new stage
        self.render(select_id=run.id)
        self.notify("Recorded as submitted. Track its stage and notes here.", "success")

    def delete_selected(self):
        run = self.selected()
        if not run or run.id == self._active_id:
            self.notify("Select an inactive application to delete.", "warning")
            return
        name = " — ".join(filter(None, [run.company, run.role])) or run.job_url
        if QMessageBox.question(self, "Delete application?", f"Delete {name}? Its local history is removed too. Approved answers are kept.") != QMessageBox.Yes:
            return
        self._save_timer.stop()
        self._queue = [i for i in self._queue if i != run.id]
        self.store.delete_run(run.id)
        self.tasks = [r for r in self.tasks if r.id != run.id]
        self._shown_id = None
        self.render()
        self.notify("Application deleted.", "success")

    def open_posting(self):
        run = self.selected()
        if run:
            QDesktopServices.openUrl(QUrl(run.job_url))

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
