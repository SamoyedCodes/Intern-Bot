from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from core.automation.models import now
from core.tracker import PIPELINE, activity, export_csv, import_csv


class TrackerDialog(QDialog):
    def __init__(self, store, run=None, parent=None):
        super().__init__(parent)
        self.store, self.run = store, run
        self.setWindowTitle("Application tracker")
        self.resize(640, 650)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        chart = QWidget()
        self.chart_layout = QFormLayout(chart)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(chart)
        layout.addWidget(scroll)
        if run:
            form = QFormLayout()
            form.addRow(QLabel(f"{run.company} — {run.role}"))
            self.pipeline = QComboBox()
            self.pipeline.addItems(PIPELINE)
            self.pipeline.setCurrentText("applied" if run.is_submitted and run.pipeline == "saved" else run.pipeline)
            form.addRow("Pipeline", self.pipeline)
            self.notes = QPlainTextEdit(run.notes)
            self.description = QPlainTextEdit(run.job_description)
            form.addRow("Notes / follow-up", self.notes)
            form.addRow("Job description", self.description)
            layout.addLayout(form)
        actions = QHBoxLayout()
        for label, callback in [("Import CSV", self.import_file), ("Export CSV", self.export_file)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.notice = QLabel("CSV imports are local tracker records. Importing never starts an application.")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel if run else QDialogButtonBox.Close)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        runs = self.store.runs()
        pipeline, daily, submitted, interviews = activity(runs)
        rate = f"{interviews / submitted:.0%}" if submitted else "—"
        self.summary.setText(f"{len(runs)} tracked · {submitted} submitted · {interviews} interviewing / offer · {rate} currently interviewing / offered\n"
                             + " · ".join(f"{name}: {pipeline[name]}" for name in PIPELINE))
        while self.chart_layout.rowCount():
            self.chart_layout.removeRow(0)
        for day, count in sorted(daily.items())[-14:]:
            bar = QProgressBar()
            bar.setRange(0, max(daily.values()))
            bar.setValue(count)
            bar.setFormat(f"{count} applications")
            self.chart_layout.addRow(day, bar)

    def save(self):
        if self.run:
            self.run.pipeline = self.pipeline.currentText()
            self.run.notes = self.notes.toPlainText()
            self.run.job_description = self.description.toPlainText()
            if self.run.pipeline not in {"saved", "archived"} and not self.run.submitted_at:
                self.run.submitted_at = now()
            self.store.save_run(self.run)
        self.accept()

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import applications", "", "CSV (*.csv)")
        if path:
            try:
                added, skipped = import_csv(self.store, path)
                self.notice.setText(f"Imported {added}; skipped {skipped} duplicate URLs.")
                self.refresh()
            except (ValueError, OSError) as exc:
                self.notice.setText(str(exc))

    def export_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export applications", "applications.csv", "CSV (*.csv)")
        if path:
            try:
                export_csv(self.store.runs(), path)
                self.notice.setText("Application tracker exported.")
            except OSError:
                self.notice.setText("Could not write the CSV. Check file access.")
