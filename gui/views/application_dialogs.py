"""Structured profile and explicit answer approval for the verified engine."""
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from core.automation.models import ApplicantProfile, ApprovedAnswer, Education, Experience, employer_key, normalized


class ProfileEditor(QWidget):
    def __init__(self, profile, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Enter facts explicitly. Unknown answers will be requested during the application."))
        tabs = QTabWidget()
        layout.addWidget(tabs)
        fields = QWidget()
        form = QFormLayout(fields)
        optional_fields = QWidget()
        optional_form = QFormLayout(optional_fields)
        optional_keys = {"preferred_name", "pronouns", "gender", "race_ethnicity", "veteran_status", "disability_status", "skills", "languages", "summary"}
        self.inputs = {}
        for name in ApplicantProfile.model_fields:
            if name in {"schema_version", "education", "experience"}:
                continue
            widget = QPlainTextEdit(getattr(profile, name)) if name in {"summary", "cover_letter"} else QLineEdit(str(getattr(profile, name)))
            if isinstance(widget, QPlainTextEdit):
                widget.setMaximumHeight(110)
            self.inputs[name] = widget
            if name in {"resume_path", "cover_letter_path"}:
                row = QHBoxLayout()
                row.addWidget(widget)
                browse = QPushButton("Choose file")
                browse.clicked.connect(lambda checked=False, key=name: self.pick_resume(key))
                row.addWidget(browse)
                form.addRow("Resume" if name == "resume_path" else "Cover letter file", row)
            else:
                (optional_form if name in optional_keys else form).addRow(name.replace("_", " ").title(), widget)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(fields)
        tabs.addTab(scroll, "Contact and resume")
        optional_scroll = QScrollArea()
        optional_scroll.setWidgetResizable(True)
        optional_scroll.setWidget(optional_fields)
        tabs.addTab(optional_scroll, "Skills and optional details")
        self.tables = {}
        for group, model in (("education", Education), ("experience", Experience)):
            page = QWidget()
            section = QVBoxLayout(page)
            keys = list(model.model_fields)
            table = QTableWidget(0, len(keys))
            table.setHorizontalHeaderLabels([k.replace("_", " ").title() for k in keys])
            self.tables[group] = (table, keys)
            for entry in getattr(profile, group):
                self.add_row(table, keys, entry.model_dump())
            section.addWidget(table)
            actions = QHBoxLayout()
            add = QPushButton("Add row")
            add.clicked.connect(lambda checked=False, t=table, k=keys: self.add_row(t, k, {}))
            remove = QPushButton("Remove selected row")
            remove.clicked.connect(lambda checked=False, t=table: t.removeRow(t.currentRow()) if t.currentRow() >= 0 else None)
            actions.addWidget(add)
            actions.addWidget(remove)
            section.addLayout(actions)
            section.addWidget(QLabel("Use dates as required by your target form. Current: true / false, or leave unknown blank."))
            tabs.addTab(page, group.title())
    def pick_resume(self, key="resume_path"):
        path, _ = QFileDialog.getOpenFileName(self, "Choose resume", "", "Resumes (*.pdf *.doc *.docx)")
        if path:
            self.inputs[key].setText(path)

    @staticmethod
    def add_row(table, keys, values):
        row = table.rowCount()
        table.insertRow(row)
        for col, key in enumerate(keys):
            value = values.get(key)
            table.setItem(row, col, QTableWidgetItem("" if value is None else str(value)))

    def profile(self):
        data = {k: (w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text()).strip() for k, w in self.inputs.items()}
        for group, (table, keys) in self.tables.items():
            rows = []
            for row in range(table.rowCount()):
                entry = {key: table.item(row, col).text().strip() if table.item(row, col) else "" for col, key in enumerate(keys)}
                if not any(entry.values()):
                    continue
                if "current" in entry and not entry["current"]:
                    entry["current"] = None
                rows.append(entry)
            data[group] = rows
        return ApplicantProfile.model_validate(data)

    def load_profile(self, profile):
        for name, widget in self.inputs.items():
            if isinstance(widget, QPlainTextEdit):
                widget.setPlainText(getattr(profile, name))
            else:
                widget.setText(getattr(profile, name))
        for group, (table, keys) in self.tables.items():
            table.setRowCount(0)
            for entry in getattr(profile, group):
                self.add_row(table, keys, entry.model_dump())

class ProfileDialog(QDialog):
    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Application profile and resume")
        self.resize(850, 650)
        layout = QVBoxLayout(self)
        self.editor = ProfileEditor(profile, self)
        layout.addWidget(self.editor)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def profile(self):
        return self.editor.profile()

    def validate_accept(self):
        try:
            self.profile()
        except ValueError:
            QMessageBox.warning(self, "Check profile", "Current must be true, false, or blank.")
            return
        self.accept()


class RunDetailsDialog(QDialog):
    def __init__(self, store, run, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Application completeness and answers")
        self.resize(850, 650)
        self.store, self.run = store, run
        layout = QVBoxLayout(self)
        report = QPlainTextEdit()
        report.setReadOnly(True)
        lines = [f"Status: {run.status} | Stage: {run.stage}",
                 f"Profile: {run.profile_name} | Browser: {run.browser} | Automatic submit: {'authorized' if run.auto_submit else 'off'}",
                 f"Active time: {run.elapsed_seconds:.1f}s | Interventions: {run.intervention_count} | AI requests: {run.ai_requests}", ""]
        for a in run.fields.values():
            lines.append(f"{a.section} / {a.label}: {a.disposition}\n  {a.reason or a.evidence}")
        lines.extend("\n" + i.message for i in run.interventions)
        lines.append("\nRecent local history:")
        lines.extend(f"{event['at']}: {event['kind']} / {event['stage']} — {event['note']}" for event in store.events(run.id)[-20:])
        report.setPlainText("\n".join(lines))
        layout.addWidget(report)
        self.questions = QComboBox()
        self.questions.setEditable(True)
        for request in run.interventions:
            if request.question and self.questions.findText(request.question) < 0:
                self.questions.addItem(request.question)
        layout.addWidget(QLabel("Question to answer (exact wording)"))
        layout.addWidget(self.questions)
        self.answer = QPlainTextEdit()
        self.answer.setMaximumHeight(110)
        self.answer.setPlaceholderText("Approved answer; select Boolean for checkbox values")
        layout.addWidget(self.answer)
        draft = QPushButton("Draft answer with Gemini…")
        draft.clicked.connect(self.draft_answer)
        layout.addWidget(draft)
        self.kind = QComboBox()
        self.kind.addItems(["Text", "Boolean true", "Boolean false", "Omit optional field"])
        layout.addWidget(self.kind)
        self.scope = QComboBox()
        self.scope.addItems(["This application", "This employer", "Future matching questions"])
        layout.addWidget(self.scope)
        approve = QPushButton("Save approved answer")
        approve.clicked.connect(self.save_answer)
        layout.addWidget(approve)
        self.notice = QLabel("")
        layout.addWidget(self.notice)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def draft_answer(self):
        from gui.views.assistant_dialog import AssistantDialog
        question = self.questions.currentText().strip()
        if not question:
            self.notice.setText("Choose or enter the exact question first.")
            return
        dialog = AssistantDialog(self.store, self.run, question, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.answer.setPlainText(dialog.output.toPlainText())
            self.kind.setCurrentIndex(0)
            self.notice.setText("Draft inserted. Review it, then explicitly save the approved answer.")

    def save_answer(self):
        question = self.questions.currentText().strip()
        if not question:
            self.notice.setText("Enter the exact question first.")
            return
        omit = self.kind.currentIndex() == 3
        if omit and any(i.required and i.question == question for i in self.run.interventions):
            self.notice.setText("Required questions cannot be omitted.")
            return
        value = self.answer.toPlainText().strip() if self.kind.currentIndex() == 0 else self.kind.currentIndex() == 1
        if not omit and value == "":
            self.notice.setText("Enter an answer or explicitly choose an omission.")
            return
        scope = ["application", "employer", "global"][self.scope.currentIndex()]
        key = self.run.id if scope == "application" else employer_key(self.run.job_url) if scope == "employer" else ""
        country = self.run.profile_snapshot.country if self.run.profile_snapshot else ""
        answer = ApprovedAnswer(question=question, profile_name=self.run.profile_name, value=value, scope=scope, scope_key=key, country=country, omit=omit)
        # Editing the same scoped answer replaces it instead of creating a conflict.
        existing = [a for a in self.store.answers() if normalized(a.question) == normalized(question) and a.profile_name == self.run.profile_name and a.scope == scope and a.scope_key == key and a.country == country]
        if existing:
            answer.id = existing[-1].id
        self.store.save_answer(answer)
        self.notice.setText("Approved answer saved. Close this window and resume the task.")


class AnswerBankDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Approved answers")
        self.resize(850, 450)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Remove an outdated approval here. Approve a replacement from the application's Details / Answers window."))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Question", "Answer", "Scope", "Employer / application", "Country", "Profile"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)
        remove = QPushButton("Remove selected approval")
        remove.clicked.connect(self.remove)
        layout.addWidget(remove)
        self.refresh()

    def refresh(self):
        self.answers = self.store.answers()
        self.table.setRowCount(len(self.answers))
        for row, answer in enumerate(self.answers):
            for col, value in enumerate([answer.question, "Omit" if answer.omit else str(answer.value), answer.scope, answer.scope_key, answer.country, answer.profile_name]):
                self.table.setItem(row, col, QTableWidgetItem(value))

    def remove(self):
        row = self.table.currentRow()
        if row >= 0:
            self.store.delete_answer(self.answers[row].id)
            self.refresh()
