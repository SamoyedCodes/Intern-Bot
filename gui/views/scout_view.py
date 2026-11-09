"""Opportunity Scout UI and the in-process daily scheduler."""
import html
from datetime import datetime
from threading import Event

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLineEdit,
    QPlainTextEdit, QSplitter, QTextBrowser, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.automation.assistant import ai_config
from core.scout import SG, Scout, ScoutSettings, consent_key, daily_due, deadline_expired, search_context, sort_key, source_rows, timestamp
from gui.theme import MessageBar, ReadableTree, button, form_layout, label


class ScoutWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, store, cfg, brave_key, profile_name, profile, settings, parent=None):
        super().__init__(parent)
        self.stop = Event()
        self.args = store, cfg, brave_key, profile_name, profile, settings

    def run(self):
        store, cfg, brave_key, name, profile, settings = self.args
        try:
            self.completed.emit(Scout(store, cfg, brave_key, self.stop, self.progress.emit).scan(name, profile, settings))
        except Exception:
            self.failed.emit("Scout could not start. Check the AI settings and local data access.")
        finally:
            self.args = None


class ScoutView(QWidget):
    prepare_requested = Signal(object)
    # Text for the sidebar badge tooltip; empty clears it.
    attention = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store, self.worker = store, None
        self._loading = True
        self._closing = False
        self._paused = set()
        self.profile_name = store.get("active_profile", "Default")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(label("Scout", "pageTitle"), 1)
        self.profiles = QComboBox()
        self.profiles.setAccessibleName("Scout profile")
        header.addWidget(self.profiles)
        self.scan_btn = button("Scan now", self.scan_now, "primary")
        header.addWidget(self.scan_btn)
        self.settings_btn = button("Search settings")
        self.settings_btn.setCheckable(True)
        self.settings_btn.setChecked(True)
        header.addWidget(self.settings_btn)
        self.stop_btn = button("Stop scan", self.stop_scan)
        self.stop_btn.hide()
        header.addWidget(self.stop_btn)
        layout.addLayout(header)
        self.notice = MessageBar()
        layout.addWidget(self.notice)

        self.settings_panel = QWidget()
        form = form_layout()
        self.mode = QComboBox()
        for name, key in (("Internships", "internships"), ("Jobs", "jobs"), ("Both", "both")):
            self.mode.addItem(name, key)
        form.addRow("Find", self.mode)
        self.brief = QPlainTextEdit()
        self.brief.setAccessibleName("Search brief")
        self.brief.setMaximumHeight(95)
        form.addRow("Search brief", self.brief)
        self.sources = QPlainTextEdit()
        self.sources.setAccessibleName("Priority sources")
        self.sources.setPlaceholderText("Organisation | https://employer.example/careers")
        self.sources.setMaximumHeight(72)
        form.addRow("Priority sources", self.sources)
        self.daily = QCheckBox("Scan daily at 8:00 a.m. Singapore time, with catch-up while the app is open")
        form.addRow("", self.daily)
        actions = QHBoxLayout()
        actions.addWidget(button("Save search", self.save_search))
        actions.addWidget(button("Preview AI context…", self.preview))
        actions.addStretch()
        form.addRow("", actions)
        self.settings_panel.setLayout(form)
        layout.addWidget(self.settings_panel)

        search_key_row = QHBoxLayout()
        self.brave_key = QLineEdit()
        self.brave_key.setEchoMode(QLineEdit.Password)
        self.brave_key.setPlaceholderText("Optional Brave Search API key")
        self.brave_key.setAccessibleName("Brave Search API key")
        search_key_row.addWidget(self.brave_key, 1)
        search_key_row.addWidget(button("Save search key", self.save_key))
        self.key_panel = QWidget()
        self.key_panel.setLayout(search_key_row)
        layout.addWidget(self.key_panel)
        self.settings_btn.toggled.connect(self.settings_panel.setVisible)
        self.settings_btn.toggled.connect(self.key_panel.setVisible)
        status_row = QHBoxLayout()
        self.status = label("Set up an AI provider in Settings, then scan for opportunities.", "caption")
        status_row.addWidget(self.status, 1)
        self.history = QComboBox()
        self.history.addItems(["Latest scan", "All saved"])
        self.history.setAccessibleName("Scout results")
        self.history.currentIndexChanged.connect(self.render)
        status_row.addWidget(self.history)
        layout.addLayout(status_row)
        self.coverage = QPlainTextEdit()
        self.coverage.setReadOnly(True)
        self.coverage.setAccessibleName("Scan coverage")
        self.coverage.setMaximumHeight(85)
        self.coverage.hide()
        layout.addWidget(self.coverage)
        split = QSplitter(Qt.Vertical)
        self.results = ReadableTree()
        self.results.setHeaderLabels(["Opportunity", "Organisation", "Type", "Hours", "Deadline"])
        self.results.setRootIsDecorated(True)
        self.results.setColumnWidth(0, 290)
        self.results.setColumnWidth(1, 170)
        self.results.setColumnWidth(2, 85)
        self.results.setColumnWidth(3, 130)
        self.results.itemSelectionChanged.connect(self.show_selected)
        split.addWidget(self.results)
        self.detail = QTextBrowser()
        self.detail.setAccessibleName("Posting evidence")
        self.detail.setOpenExternalLinks(True)
        split.addWidget(self.detail)
        split.setSizes([250, 150])
        layout.addWidget(split, 1)
        bottom = QHBoxLayout()
        self.open_btn = button("Open posting", self.open_posting)
        self.prepare_btn = button("Prepare application", self.prepare, "primary")
        bottom.addWidget(self.open_btn)
        bottom.addStretch()
        bottom.addWidget(self.prepare_btn)
        layout.addLayout(bottom)

        self.profiles.currentTextChanged.connect(self.switch_profile)
        self.daily.toggled.connect(self.daily_toggled)
        self._loading = False
        self.refresh_profiles()
        self.timer = QTimer(self, interval=30000, timeout=self.check_daily)
        self.timer.start()
        QTimer.singleShot(0, self.check_daily)

    def refresh_profiles(self):
        names = list(self.store.profiles())
        self.profiles.blockSignals(True)
        self.profiles.clear()
        self.profiles.addItems(names)
        self.profiles.setCurrentText(self.profile_name if self.profile_name in names else names[0])
        self.profiles.blockSignals(False)
        self.switch_profile(self.profiles.currentText())

    def showEvent(self, event):
        super().showEvent(event)
        # Reloading on every tab switch would discard an unsaved brief; reload only when profiles were added or removed.
        if not self.worker and list(self.store.profiles()) != [self.profiles.itemText(i) for i in range(self.profiles.count())]:
            self.refresh_profiles()

    def switch_profile(self, name):
        if not name:
            return
        self.profile_name = name
        settings = self.saved_settings(name)
        self._loading = True
        self.mode.setCurrentIndex(self.mode.findData(settings.mode))
        self.brief.setPlainText(settings.brief)
        self.sources.setPlainText(settings.sources)
        self.daily.setChecked(settings.enabled)
        self._loading = False
        self.render()

    def saved_settings(self, name):
        return ScoutSettings.model_validate(self.store.get("scout:" + name, {}))

    def settings(self):
        saved = self.saved_settings(self.profile_name)
        return ScoutSettings(enabled=self.daily.isChecked(), mode=self.mode.currentData(),
                             brief=self.brief.toPlainText().strip(), sources=self.sources.toPlainText().strip(), consent=saved.consent)

    def save_search(self):
        try:
            settings = self.settings()
            source_rows(settings)
            self.store.put("scout:" + self.profile_name, settings.model_dump())
            self.notice.notify("Search saved.", "success")
            return settings
        except Exception:
            self.notice.notify("Use a brief of 1–5,000 characters and at most 60 public HTTPS source URLs.", "warning")
            return None

    def daily_toggled(self, enabled):
        if self._loading:
            return
        if enabled and not self.preview():
            self.daily.blockSignals(True)
            self.daily.setChecked(False)
            self.daily.blockSignals(False)
        self.save_search()
        if self.daily.isChecked():
            self.check_daily()
        else:
            self._paused.discard(self.profile_name)
            self._flag()

    def configuration(self):
        cfg = ai_config(self.store)
        if cfg is None:
            raise ValueError("Choose an AI provider and model in Settings before scanning.")
        return cfg

    def preview(self):
        try:
            cfg = self.configuration()
            settings = self.settings()
            source_rows(settings)
            profile = self.store.profiles()[self.profile_name]
        except Exception as exc:
            self.notice.notify(str(exc) if isinstance(exc, ValueError) else "Check AI settings and keychain access.", "warning")
            return False
        dialog = QDialog(self)
        dialog.setWindowTitle("Scout AI context")
        dialog.resize(650, 470)
        box = QVBoxLayout(dialog)
        box.addWidget(label(f"{cfg['name']} · {cfg['model']}", "section"))
        box.addWidget(label("Scout shares this context and public posting text with the selected provider. Search services receive the search criteria. Daily scans can incur API charges.", "muted"))
        outgoing = QPlainTextEdit(search_context(settings, profile))
        outgoing.setReadOnly(True)
        box.addWidget(outgoing)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Allow Scout requests")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return False
        settings.consent = consent_key(cfg, settings, profile)
        self.store.put("scout:" + self.profile_name, settings.model_dump())
        self._paused.discard(self.profile_name)
        self._flag()
        return True

    def _flag(self):
        self.attention.emit(f"Daily scouting is paused for {', '.join(sorted(self._paused))}. Open Scout and preview the AI context to resume." if self._paused else "")

    def save_key(self):
        if not self.brave_key.text().strip():
            self.notice.notify("Paste a Brave Search API key first.", "warning")
            return
        try:
            self.store._vault().set("brave-search-api-key", self.brave_key.text().strip())
            self.brave_key.clear()
            self.notice.notify("Search key saved to the system keychain.", "success")
        except Exception:
            self.notice.notify("The search key could not be saved to the system keychain.", "danger")

    def check_daily(self, at=None):
        if self._closing or self.worker:
            return
        at = at or datetime.now(SG)
        for name in self.store.profiles():
            settings = self.saved_settings(name)
            if daily_due(settings, self.store.get("scout-last-attempt:" + name), at):
                if self.start_scan(name, settings, automatic=True, at=at):
                    break

    def scan_now(self):
        if self.worker:
            return
        settings = self.save_search()
        if settings:
            self.start_scan(self.profile_name, settings)

    def start_scan(self, name, settings, automatic=False, at=None):
        if self.worker or self._closing:
            return False
        try:
            cfg = self.configuration()
            profile = self.store.profiles()[name]
            if settings.consent != consent_key(cfg, settings, profile):
                if automatic:
                    # Checked every 30 seconds, so warn once per pause rather than on every tick.
                    if name not in self._paused:
                        self._paused.add(name)
                        self.notice.notify(f"{name}: preview the current AI context to resume daily scouting.", "warning")
                        self._flag()
                    return False
                if not self.preview():
                    return False
                settings = self.saved_settings(name)
            source_rows(settings)
            brave_key = self.store._vault().get("brave-search-api-key") or ""
            self.store.put("scout-last-attempt:" + name, (at or datetime.now(SG)).astimezone(SG).date().isoformat())
        except Exception:
            self.notice.notify("Check the AI provider, model, Keychain and priority source URLs before scanning.", "warning")
            return False
        self.worker = ScoutWorker(self.store, cfg, brave_key, name, profile.model_copy(deep=True), settings, self)
        self.worker.progress.connect(self.status.setText)
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(lambda text: self.notice.notify(text, "danger"))
        self.worker.finished.connect(self.finished)
        self.scan_btn.setEnabled(False)
        self.settings_panel.setEnabled(False)
        self.profiles.setEnabled(False)
        self.stop_btn.show()
        self.status.setText(f"Scanning for {name}…")
        self.worker.start()
        return True

    def completed(self, report):
        count = len(report["new_ids"])
        text = f"{report['profile_name']}: {count} new {'opportunity' if count == 1 else 'opportunities'}."
        if not count and report["status"] == "complete":
            text = "No new verified matches."
        elif report["status"] != "complete":
            text += " Scan " + report["status"] + "; see coverage."
        self.notice.notify(text, "success" if report["status"] == "complete" else "warning")
        self.settings_btn.setChecked(False)
        self.render()

    def finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.scan_btn.setEnabled(True)
        self.settings_panel.setEnabled(True)
        self.profiles.setEnabled(True)
        self.stop_btn.hide()
        if self._closing:
            QTimer.singleShot(0, self.window().close)
        else:
            self.render()

    def render(self):
        self.results.clear()
        reports = self.store.scout_reports(self.profile_name)
        latest = reports[0] if reports else None
        if latest:
            status = "Interrupted · run Scan now to retry" if latest['status'] == 'running' and not self.worker else latest['status'].title()
            self.status.setText(f"{status} · {latest['mode']} · {latest['checked']} postings checked · {latest['started_at'][:16]} SGT")
            coverage = [f"{s['name']}: {s['status']}" for s in latest.get("sources", [])] + latest["issues"]
            self.coverage.setPlainText("\n".join(coverage))
            self.coverage.setVisible(bool(coverage))
        items = self.store.opportunities(self.profile_name)
        if self.history.currentIndex() == 0:
            # Everything this scan verified as open, not only first sightings; older reports only recorded new ids.
            ids = set(latest.get("seen_ids", latest["new_ids"])) if latest else set()
            items = [i for i in items if i.id in ids and i.active]
        new = set(latest["new_ids"]) if latest else set()
        at = datetime.now(SG)
        groups = {}
        for item in sorted(items, key=lambda i: sort_key(i, at)):
            deadline = timestamp(item.deadline)
            days = (deadline.astimezone(SG).date() - at.date()).days if deadline else None
            group = "Closing within 14 days" if days is not None and 0 <= days <= 14 else {"recent": "Posted in the last 48 hours", "earlier": "Open · posted earlier", "undated": "Open leads · date unverified"}[item.freshness]
            if group not in groups:
                groups[group] = QTreeWidgetItem(self.results, [group])
                groups[group].setExpanded(True)
            row = QTreeWidgetItem(groups[group], [item.title + (" · Closed" if not item.active else " · New" if item.id in new else ""), item.organisation,
                                   item.kind.title(), item.evidence.get("hours").value if item.evidence.get("hours") and item.evidence["hours"].value else "Not stated",
                                   item.deadline or "Not stated"])
            row.setData(0, Qt.UserRole, item)
        self.detail.clear()
        if not items:
            self.detail.setPlainText("No results in this view. Run a scan, or choose All saved to see earlier opportunities.")
        elif self.results.topLevelItemCount():
            self.results.setCurrentItem(self.results.topLevelItem(0).child(0))
        self.show_selected()

    def selected(self):
        row = self.results.currentItem()
        return row.data(0, Qt.UserRole) if row else None

    def show_selected(self):
        item = self.selected()
        expired = deadline_expired(item.deadline, datetime.now(SG)) if item else False
        self.prepare_btn.setEnabled(bool(item and item.active and not expired))
        self.open_btn.setEnabled(bool(item))
        if not item:
            return
        escape = html.escape
        parts = [f"<h3>{escape(item.title)}</h3><p>{escape(item.reason)}</p>",
                 f'<p><a href="{escape(item.url, quote=True)}">{escape(item.organisation)} · Open source posting</a></p>',
                 f"<p>Verified {escape(item.verified_at)} · First seen {escape(item.first_seen)}</p>"]
        for key, title in (("opening", "Applications"), ("eligibility", "Eligibility"), ("start", "Start date"),
                           ("duration", "Duration"), ("hours", "Working hours"), ("published", "Posted or updated"), ("deadline", "Deadline")):
            fact = item.evidence.get(key)
            parts.append(f"<p><b>{title}</b> — {escape(fact.value if fact and fact.value else 'Not stated')}")
            if fact and fact.quote:
                parts.append(f"<br>{escape(fact.quote)}")
            parts.append("</p>")
        self.detail.setHtml("".join(parts))

    def prepare(self):
        item = self.selected()
        if item and self.prepare_btn.isEnabled():
            self.prepare_requested.emit(item)

    def open_posting(self):
        item = self.selected()
        if item:
            QDesktopServices.openUrl(QUrl(item.url))

    def stop_scan(self):
        if self.worker:
            self.worker.stop.set()
            self.status.setText("Stopping after the current request…")

    def shutdown(self):
        self._closing = True
        self.timer.stop()
        if self.worker:
            self.worker.stop.set()
            self.status.setText("Finishing the current Scout request before closing…")
            return False
        return True
