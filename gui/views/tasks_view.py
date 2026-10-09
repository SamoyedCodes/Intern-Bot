"""One local extension engine, one persisted application model, one sequential queue."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.automation.models import ApplicantProfile, ApplicationRun, InterventionRequest, ats_name, canonical_url, job_identity, now
from core.automation.service import AutomationService
from core.storage.local_store import LocalStore
from gui.views.application_dialogs import ProfileDialog, RunDetailsDialog
from gui.views.tracker_dialog import TrackerDialog


class TaskDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = parent.store if parent else LocalStore()
        self.setWindowTitle("New application")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.company, self.role, self.url = QLineEdit(), QLineEdit(), QLineEdit()
        self.url.setPlaceholderText("https://company.wd1.myworkdayjobs.com/...")
        for label, widget in [("Company", self.company), ("Role", self.role), ("Job URL", self.url)]:
            form.addRow(label, widget)
        self.profile = QComboBox()
        self.profile.addItems(self.store.profiles())
        self.profile.setCurrentText(self.store.get("active_profile", "Default"))
        form.addRow("Applicant profile", self.profile)
        self.auto_submit = QCheckBox("Submit automatically after all fields and review are verified")
        form.addRow(self.auto_submit)
        form.addRow(QLabel("28 local adapters in Chromium. Other HTTPS pages are opened for detection; unmatched forms remain manual."))
        layout.addLayout(form)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def validate(self):
        try:
            canonical_url(self.url.text().strip(), supported_only=False)
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        if self.auto_submit.isChecked() and QMessageBox.question(self, "Authorize this application", "Allow Intern-Bot to submit this specific application using the selected profile and approved answers? It will stop if anything cannot be verified.") != QMessageBox.Yes:
            return
        self.accept()

    def application(self):
        return ApplicationRun(job_url=canonical_url(self.url.text().strip(), supported_only=False),
                              company=self.company.text().strip(), role=self.role.text().strip() or "Internship",
                              profile_name=self.profile.currentText(), profile_snapshot=self.store.profiles()[self.profile.currentText()],
                              auto_submit=self.auto_submit.isChecked(), **{**self.store.get("automation_options", {}), "browser": "chromium"})


class TasksView(QWidget):
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(14)
        title = QLabel("Applications")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel("Prepare applications with your saved profiles, resolve missing answers, and track interviews and offers.")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search applications")
        self.search.textChanged.connect(self.render)
        layout.addWidget(self.search)
        self.counts = QLabel("")
        layout.addWidget(self.counts)
        for actions in [
            [("New application", self.add_dialog), ("Start / Resume", self.start_selected), ("Start queue", self.start_all_tasks), ("Pause", self.pause), ("Cancel selected", self.cancel)],
            [("Details / Answers", self.details), ("Edit application profile", self.edit_profile), ("Mark submitted by me", self.mark_submitted), ("Delete selected", self.delete_selected)],
            [("Tracker / Notes / CSV", self.tracker), ("Compare profiles with Gemini…", self.compare_profiles)],
        ]:
            row = QHBoxLayout()
            for label, callback in actions:
                button = QPushButton(label)
                button.clicked.connect(callback)
                row.addWidget(button)
            row.addStretch()
            layout.addLayout(row)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Company", "Role", "Stage", "Status", "Progress / Action needed", "Job URL"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(72)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setWordWrap(True)
        layout.addWidget(self.table)
        self.notice = QLabel("Preview: live employer acceptance testing remains pending.")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.load_state()

    def load_state(self):
        self.tasks = self.store.runs()
        for run in self.tasks:
            if run.status == "running":
                run.status = "needs_input"
                run.interventions = [InterventionRequest(kind="browser", message="Interrupted application. Resume to inspect the saved draft.")]
                self.store.save_run(run)
        self.render()

    def filtered(self):
        query = self.search.text().strip().casefold()
        return [r for r in self.tasks if query in f"{r.company} {r.role} {r.job_url}".casefold()]

    def selected(self):
        row = self.table.currentRow()
        visible = self.filtered()
        return visible[row] if 0 <= row < len(visible) else None

    @staticmethod
    def status_label(run):
        if run.pipeline not in {"saved", "applied"}:
            return run.pipeline.title()
        if run.is_submitted or run.submitted_at:
            return "Submitted by you" if run.submitted_by_user else "Applied"
        return run.status.replace("_", " ").capitalize()

    def render(self):
        current = self.selected() if self.table.rowCount() else None
        visible = self.filtered()
        self.table.setRowCount(len(visible))
        for row, run in enumerate(visible):
            message = run.interventions[0].message if run.interventions else f"{sum(f.disposition == 'verified' for f in run.fields.values())} fields verified"
            stage = "Application form" if run.stage.startswith("form_") else run.stage.replace('_', ' ').title()
            for col, text in enumerate([run.company, run.role, stage, self.status_label(run), message, run.job_url]):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, col, item)
            if current and current.id == run.id:
                self.table.selectRow(row)
        self.counts.setText(f"{len(self.tasks)} applications   •   {sum(r.status == 'queued' and r.pipeline == 'saved' and not r.is_submitted for r in self.tasks)} queued   •   {sum(r.status == 'needs_input' and r.pipeline == 'saved' and not r.is_submitted for r in self.tasks)} need input")

    def add_dialog(self):
        dialog = TaskDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.add_task(dialog.application())

    def add_task(self, run):
        try:
            run.job_url = canonical_url(run.job_url, supported_only=False)
        except ValueError as exc:
            self.notice.setText(str(exc))
            return False
        if any(job_identity(r.job_url) == job_identity(run.job_url) for r in self.tasks):
            self.notice.setText("This job is already in the queue. Resume the existing application.")
            return False
        if any(r.company.casefold() == run.company.casefold() and r.role.casefold() == run.role.casefold() for r in self.tasks):
            if QMessageBox.question(self, "Possible duplicate", "An application with this company and role already exists. Add this different URL as a separate application?") != QMessageBox.Yes:
                return False
        if run.profile_snapshot is None:
            run.profile_name = self.store.get("active_profile", "Default")
            run.profile_snapshot = self.store.profiles()[run.profile_name]
        self.store.save_run(run)
        self.tasks.append(run)
        self.render()
        return True

    def start_selected(self):
        run = self.selected()
        if run:
            self._start_task(run)
        else:
            self.notice.setText("Select an application first.")

    def start_all_tasks(self):
        self._queue = [r.id for r in self.tasks if r.status in {"queued", "failed"} and not r.is_submitted and not r.submitted_at and r.pipeline == "saved" and r.id != self._active_id]
        self._start_next()

    def _start_next(self):
        if self._closing or self._active_id:
            return
        while self._queue and not self._active_id:
            run_id = self._queue.pop(0)
            run = next((r for r in self.tasks if r.id == run_id), None)
            if run:
                self._start_task(run)

    def _start_task(self, run):
        if self._active_id:
            self.notice.setText("Another application is running. Pause it or wait before starting this one.")
            return
        if run.is_submitted or run.submitted_at or run.pipeline != "saved":
            self.notice.setText("This application is already in your pipeline and will not restart.")
            return
        inspect_only = run.status == "ready_for_review"
        if inspect_only and self.service.show_browser(run.id):
            return
        try:
            profile = run.profile_snapshot or ApplicantProfile.model_validate(self.store.get("verified_profile", {}))
            credential = self.store._vault().credential(run.job_url) if ats_name(run.job_url) == "Workday" else None
            if self.service.start(run.model_copy(deep=True), profile, credential, inspect_only=inspect_only):
                self._active_id = run.id
                self._queue = [i for i in self._queue if i != run.id]
                run.status = "running"
                run.interventions = []
                self.render()
                self.notice.setText("Preparing application in Chromium. Employer sign-in may be required again. " + ("Automatic submission authorized for this job." if run.auto_submit else "Final submission remains manual."))
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
        self._start_next()

    def pause(self):
        self._queue = []
        if self._active_id:
            self.service.pause(self._active_id)
            self.notice.setText("Stopping adapter writes and pending waits.")

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
        if run and not self._active_id:
            RunDetailsDialog(self.store, run, self).exec()
        else:
            self.notice.setText("Select an application and pause any active queue before editing answers.")

    def compare_profiles(self):
        from gui.views.assistant_dialog import AssistantDialog
        run = self.selected()
        if not run or self._active_id:
            self.notice.setText("Select an inactive application. Add its job description in Tracker for a useful comparison.")
            return
        AssistantDialog(self.store, run, mode="compare", parent=self).exec()

    def edit_profile(self):
        run = self.selected()
        if not run or self._active_id or run.is_submitted or run.submission_attempted or run.pipeline != "saved":
            self.notice.setText("Select an inactive application to edit its profile.")
            return
        profile = run.profile_snapshot or ApplicantProfile.model_validate(self.store.get("verified_profile", {}))
        dialog = ProfileDialog(profile, self)
        if dialog.exec() == QDialog.Accepted:
            run.profile_snapshot = dialog.profile()
            run.status = "needs_input"
            self.store.save_run(run)
            self.render()
            self.notice.setText("Application profile saved. Revisit its first section before resuming verification.")

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
        self.render()

    def tracker(self):
        if self._active_id:
            self.notice.setText("Pause the active application before editing tracker records.")
            return
        TrackerDialog(self.store, self.selected(), self).exec()
        self.load_state()

    def delete_selected(self):
        run = self.selected()
        if not run or run.id == self._active_id:
            self.notice.setText("Select an inactive application to delete.")
            return
        self._queue = [i for i in self._queue if i != run.id]
        self.store.delete_run(run.id)
        self.tasks = [r for r in self.tasks if r.id != run.id]
        self.render()

    def shutdown(self):
        self._closing = True
        self._queue = []
        self.service.shutdown()
