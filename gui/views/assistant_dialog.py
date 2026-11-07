import json

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QPlainTextEdit, QVBoxLayout

from core.automation.assistant import DEFAULT_PROVIDER, PROVIDERS, ai_config, career_facts, generate_text
from core.automation.privacy import redact
from gui.theme import button, label, restyle


class AssistWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, cfg, mode, context, parent):
        super().__init__(parent)
        self.args = cfg, mode, context

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
        try:
            self.cfg = ai_config(store)
        except Exception:
            self.cfg = None  # Reported when you try to send.
        name = self.cfg["name"] if self.cfg else PROVIDERS.get(store.get("ai_provider", DEFAULT_PROVIDER), PROVIDERS[DEFAULT_PROVIDER])["name"]
        local = bool(self.cfg and self.cfg["local"])
        self.setWindowTitle("Draft answer" if mode == "draft" else "Compare profiles")
        self.resize(760, 700)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(label(f"Draft an answer with {name}" if mode == "draft" else f"Compare profiles with {name}", "section"))
        layout.addWidget(label("Review and edit exactly what will be sent to your local model; nothing leaves this Mac." if local else
                               f"Review and edit exactly what will be sent to the {name} API. Contact details, file contents and credentials are left out, and names, "
                               "emails, phone numbers and links in your career facts are masked, but other free text may still be personal.", "muted"))
        profiles = store.profiles() if mode == "compare" else {run.profile_name: run.profile_snapshot or store.profiles()[store.get("active_profile", "Default")]}
        context = {"question": question, "company": run.company, "role": run.role,
                   "job_description": run.job_description, "profiles": {name: career_facts(p) for name, p in profiles.items()}}
        layout.addWidget(label("Context to send", "overline"))
        text = json.dumps(context, indent=2, ensure_ascii=False)
        for profile in profiles.values():
            text = redact(text, profile)
        self.context = QPlainTextEdit(text)
        layout.addWidget(self.context, 1)
        send = QHBoxLayout()
        self.consent = QCheckBox(f"Send this context to {name} for this request")
        self.generate = button("Generate draft" if mode == "draft" else "Compare profiles", self.start, "primary")
        self.generate.setEnabled(False)
        self.consent.toggled.connect(self.generate.setEnabled)
        send.addWidget(self.consent, 1)
        send.addWidget(self.generate)
        layout.addLayout(send)
        layout.addWidget(label(f"{name} output", "overline"))
        self.output = QPlainTextEdit()
        self.output.setPlaceholderText("The response appears here for you to review and edit.")
        layout.addWidget(self.output, 1)
        self.notice = label("AI output needs your review. Nothing is filled in or approved automatically.", "caption")
        layout.addWidget(self.notice)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Use draft" if mode == "draft" else "Close")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(mode == "compare")
        restyle(self.buttons.button(QDialogButtonBox.Ok), variant="primary")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def start(self):
        if not self.consent.isChecked():
            self.notice.setText("Review the context and select the consent checkbox first.")
            return
        if not self.cfg:
            self.notice.setText("Set up an AI provider in Settings first: a model name, and an API key for cloud providers.")
            return
        self.generate.setEnabled(False)
        self.consent.setEnabled(False)
        self.buttons.setEnabled(False)
        self.output.clear()
        self.worker = AssistWorker(self.cfg, self.mode, self.context.toPlainText(), self)
        self.worker.completed.connect(self.complete)
        self.worker.failed.connect(self.notice.setText)
        self.worker.finished.connect(self.finished_request)
        self.application.ai_requests += 1
        self.store.save_run(self.application)
        self.notice.setText(f"Waiting for {self.cfg['name']}…")
        self.worker.start()

    def complete(self, text):
        self.output.setPlainText(text)
        self.notice.setText("Review the output. Using a draft does not approve it; save the answer separately.")

    def finished_request(self):
        self.buttons.setEnabled(True)
        self.consent.setEnabled(True)
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
