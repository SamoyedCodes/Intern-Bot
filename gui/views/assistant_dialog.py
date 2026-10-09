import json

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from core.automation.assistant import DEFAULT_MODEL, career_facts, generate_text


class AssistWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, key, model, mode, context, parent):
        super().__init__(parent)
        self.args = key, model, mode, context

    def run(self):
        try:
            self.completed.emit(generate_text(*self.args))
        except ValueError as exc:
            self.failed.emit(str(exc))
        finally:
            self.args = None


class AssistantDialog(QDialog):
    def __init__(self, store, run, question="", mode="draft", parent=None):
        super().__init__(parent)
        self.store, self.application, self.mode = store, run, mode
        self.worker = None
        self.setWindowTitle("Draft answer" if mode == "draft" else "Compare profiles")
        self.resize(760, 700)
        layout = QVBoxLayout(self)
        hint = QLabel("Review and edit the exact context below before sending it to Google's Gemini API. Contact details, file contents and credentials are excluded automatically; free-text career facts may still contain personal information.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        profiles = store.profiles() if mode == "compare" else {run.profile_name: run.profile_snapshot or store.profiles()[store.get("active_profile", "Default")]}
        context = {"question": question, "company": run.company, "role": run.role,
                   "job_description": run.job_description, "profiles": {name: career_facts(p) for name, p in profiles.items()}}
        self.context = QPlainTextEdit(json.dumps(context, indent=2, ensure_ascii=False))
        layout.addWidget(self.context)
        self.consent = QCheckBox("Send this context to Gemini for this request")
        layout.addWidget(self.consent)
        self.generate = QPushButton("Generate draft" if mode == "draft" else "Compare profiles")
        self.generate.clicked.connect(self.start)
        layout.addWidget(self.generate)
        self.output = QPlainTextEdit()
        layout.addWidget(self.output)
        self.notice = QLabel("AI output needs your review. Nothing is filled or approved automatically.")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Use draft" if mode == "draft" else "Close")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(mode == "compare")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def start(self):
        if not self.consent.isChecked():
            self.notice.setText("Review the context and select the consent checkbox first.")
            return
        try:
            key = self.store._vault().get("gemini-api-key")
        except Exception:
            self.notice.setText("Could not read the Gemini key from the operating-system keychain.")
            return
        if not key:
            self.notice.setText("Save a Gemini API key in Settings first.")
            return
        self.generate.setEnabled(False)
        self.buttons.setEnabled(False)
        self.output.clear()
        self.worker = AssistWorker(key, self.store.get("gemini_model", DEFAULT_MODEL), self.mode, self.context.toPlainText(), self)
        self.worker.completed.connect(self.complete)
        self.worker.failed.connect(self.notice.setText)
        self.worker.finished.connect(self.finished_request)
        self.application.ai_requests += 1
        self.store.save_run(self.application)
        self.notice.setText("Waiting for Gemini…")
        self.worker.start()

    def complete(self, text):
        self.output.setPlainText(text)
        self.notice.setText("Review the output. Using a draft does not approve it; save the answer separately.")

    def finished_request(self):
        self.generate.setEnabled(True)
        self.buttons.setEnabled(True)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(self.mode == "compare" or bool(self.output.toPlainText().strip()))
        self.consent.setChecked(False)

    def done(self, result):
        if self.worker and self.worker.isRunning():
            self.notice.setText("Wait for this request to finish before closing.")
            return
        super().done(result)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)
