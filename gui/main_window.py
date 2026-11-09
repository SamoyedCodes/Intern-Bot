from core.automation.assistant import DEFAULT_PROVIDER, PROVIDERS, ai_config, endpoint, is_local, check_connection
from core.automation.models import site_key
from core.storage.local_store import LocalStore

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.theme import form_layout, MessageBar, button, card, dot_icon, label, shortcut, station_heading
from gui.shortcuts import install_edit_shortcuts
from gui.views.application_dialogs import AnswersView
from gui.views.assistant_dialog import AssistWorker
from gui.views.profile_view import ProfileView
from gui.views.tasks_view import TasksView, status_meta
from gui.views.scout_view import ScoutView

SAFETY_FACTS = [
    "Browser: bundled Chromium with local adapters, always visible.",
    "Final submission is yours by default. Automatic submission needs your authorization for each application and stops if anything can't be verified.",
    "Applications run in a separate, visible Chromium window. Employers may ask you to sign in again.",
    "Profiles, answers and history stay in a local database on this Mac. Employer logins and API keys are kept only in the system keychain.",
    "AI autofill receives question wording and permitted career facts. Scout sends its previewed search context and public postings to your selected provider. Contact details, documents, credentials and application pages stay private.",
    "Preview: adapters are tested against fictional forms. Live employer acceptance testing is still pending.",
]


class SettingsView(QWidget):
    def __init__(self, store=None):
        super().__init__()
        self.store = store or LocalStore()
        self._key_checked = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(station_heading("Settings", "dispatch", "Choose how the crew prepares applications and which services it can use."))
        self.notice = MessageBar()
        layout.addWidget(self.notice)
        tabs = self.categories = QTabWidget()
        tabs.setAccessibleName("Settings categories")
        layout.addWidget(tabs)
        def add_page(name, frame):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(frame)
            tabs.addTab(scroll, name)

        options = self.store.get("automation_options", {})
        frame, box = card()
        box.addWidget(label("Automation", "section"))
        self.auto_advance = QCheckBox("Continue automatically after each section is verified")
        self.auto_advance.setChecked(options.get("auto_advance", True))
        box.addWidget(self.auto_advance)
        box.addWidget(label("When off, Intern-Bot pauses after every section so you can check it.", "caption"))
        self.reuse_answers = QCheckBox("Reuse answers you've approved")
        self.reuse_answers.setChecked(options.get("reuse_answers", True))
        box.addWidget(self.reuse_answers)
        box.addWidget(label("Reused for the question and every wording matched to it, within the answer's scope, profile and country.", "caption"))
        for checkbox in (self.auto_advance, self.reuse_answers):
            checkbox.toggled.connect(self.save_options)
        box.addWidget(label("Workshop display", "section"))
        self.crew_motion = QCheckBox("Animate workers during an active application")
        self.crew_motion.setChecked(bool(self.store.get("crew_motion", True)))
        self.crew_motion.toggled.connect(lambda value: self.store.put("crew_motion", value))
        box.addWidget(self.crew_motion)
        box.addStretch()
        add_page("Automation", frame)

        frame, box = card()
        box.addWidget(label("AI assistance (optional)", "section"))
        box.addWidget(label("AI fills factual questions your profile and answers don't cover by name, and drafts answers or compares profiles when you ask. A model running on this Mac (LM Studio, Ollama) keeps everything local.", "muted"))
        form = self.ai_form = form_layout(10)
        self.provider = QComboBox()
        for key, spec in PROVIDERS.items():
            self.provider.addItem(spec["name"], key)
        self.provider.setCurrentIndex(max(0, self.provider.findData(self.store.get("ai_provider", DEFAULT_PROVIDER))))
        form.addRow("Provider", self.provider)
        self.ai_url = QLineEdit()
        self.ai_url.setPlaceholderText(PROVIDERS["compatible"]["url"])
        self.ai_url.editingFinished.connect(self.save_url)
        form.addRow("Server URL", self.ai_url)
        self.ai_model = QLineEdit()
        self.ai_model.editingFinished.connect(self.save_model)
        form.addRow("Model", self.ai_model)
        self.ai_key = QLineEdit()
        self.ai_key.setEchoMode(QLineEdit.Password)
        self.save_api_key_btn = button("Save key", self.save_api_key, "primary")
        key_row = QHBoxLayout()
        key_row.addWidget(self.ai_key, 1)
        key_row.addWidget(self.save_api_key_btn)
        form.addRow("API key", key_row)
        self.key_status = label(role="caption")
        self.test_btn = button("Test connection", self.test_connection)
        status_row = QHBoxLayout()
        status_row.addWidget(self.key_status, 1)
        status_row.addWidget(self.test_btn)
        form.addRow("", status_row)
        box.addLayout(form)
        self.ai_privacy = label(role="caption")
        box.addWidget(self.ai_privacy)
        self.ai_facts = QCheckBox()
        self.ai_facts.toggled.connect(self.save_facts)
        box.addWidget(self.ai_facts)
        self.ai_match = QCheckBox("Fill unknown and reworded questions with AI")
        self.ai_match.setChecked(options.get("ai_match", True))
        self.ai_match.toggled.connect(self.save_options)
        box.addWidget(self.ai_match)
        box.addWidget(label("Factual questions only: essays, demographics, health, legal status, pay and consent questions are always left to you. "
                            "AI answers fill the form and appear under Answers; automatic submission waits until you confirm them.", "caption"))
        box.addStretch()
        add_page("AI assistance", frame)
        self.show_provider()
        self.provider.currentIndexChanged.connect(self.change_provider)

        frame, box = card(6)
        box.addWidget(label("Safety and privacy", "section"))
        for fact in SAFETY_FACTS:
            box.addWidget(label(fact, "fact"))
        box.addStretch()
        add_page("Safety and privacy", frame)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._key_checked:
            self._key_checked = True
            self.check_key()

    def check_key(self):
        if self.provider.currentData() == "compatible" and is_local(self.ai_url.text()):
            self.key_status.setText("No key needed for a server on this Mac.")
            return
        try:
            saved = bool(self.store._vault().get(f"{self.provider.currentData()}-api-key"))
            self.key_status.setText("A key is stored in the system keychain." if saved else "No key saved yet.")
        except Exception:
            self.key_status.setText("Couldn't read the system keychain.")

    def test_connection(self):
        self.save_model()
        cfg = ai_config(self.store)
        if not cfg:
            self.notice.notify(f"Save a model{'' if self.provider.currentData() == 'compatible' else ' and API key'} first.", "warning")
            return
        self.test_btn.setEnabled(False)
        self.test_btn.setText("Testing…")
        self.tester = AssistWorker(self, cfg, func=check_connection)
        self.tester.completed.connect(lambda text: self.notice.notify(text, "success"))
        self.tester.failed.connect(lambda text: self.notice.notify(text, "danger"))
        self.tester.finished.connect(lambda: (self.test_btn.setEnabled(True), self.test_btn.setText("Test connection")))
        self.tester.start()

    def show_provider(self):
        provider = self.provider.currentData()
        spec = PROVIDERS[provider]
        self.ai_form.setRowVisible(self.ai_url, provider == "compatible")
        self.ai_url.setText(self.store.get(f"{provider}_url", spec.get("url", "")))
        self.ai_model.setText(self.store.get(f"{provider}_model", spec["model"]))
        self.ai_model.setPlaceholderText("The model's name on your server, e.g. qwen3-8b" if provider == "compatible" else "")
        self.ai_key.clear()
        self.ai_key.setPlaceholderText("Only for a server that asks for one" if provider == "compatible" else f"Paste a {spec['name']} API key")
        self.ai_facts.blockSignals(True)
        self.ai_facts.setText(f"Also let {spec['name']} see your career facts (education, experience, skills) to pick answers like your degree level")
        self.ai_facts.setChecked(bool(self.store.get(f"{provider}_facts", False)))
        self.ai_facts.blockSignals(False)
        self.show_privacy()

    def show_privacy(self):
        provider = self.provider.currentData()
        name = PROVIDERS[provider]["name"]
        local = provider == "compatible" and is_local(self.ai_url.text())
        self.ai_facts.setVisible(not local)
        if local:
            text = "On this Mac: questions and your career facts go only to the local server, never over the internet."
        elif self.ai_facts.isChecked():
            text = f"{name} receives question wording, form options, your profile field names and your career facts, with names and contact details masked."
        else:
            text = f"{name} receives only question wording, form options and the names of your profile fields, never their values."
        if provider == "deepseek":
            text += " DeepSeek processes requests on servers in China."
        self.ai_privacy.setText(text)

    def save_url(self):
        provider, url = self.provider.currentData(), self.ai_url.text().strip()
        try:
            endpoint(url)
        except ValueError as exc:
            self.notice.notify(str(exc), "warning")
            return
        if url != self.store.get(f"{provider}_url", PROVIDERS[provider].get("url", "")):
            self.store.put(f"{provider}_url", url)
            self.notice.notify("Server URL saved.", "success")
        self.show_privacy()
        self.check_key()

    def save_facts(self, allowed):
        self.store.put(f"{self.provider.currentData()}_facts", allowed)
        self.show_privacy()
        self.notice.notify("Saved.", "success")

    def change_provider(self):
        self.store.put("ai_provider", self.provider.currentData())
        self.show_provider()
        self.check_key()
        self.notice.notify(f"AI requests now use {self.provider.currentText()}.", "success")

    def save_options(self):
        self.store.put("automation_options", {"browser": "chromium",
                       "auto_advance": self.auto_advance.isChecked(), "reuse_answers": self.reuse_answers.isChecked(),
                       "ai_match": self.ai_match.isChecked()})
        self.notice.notify("Saved. New applications use these defaults.", "success")

    def save_model(self):
        provider = self.provider.currentData()
        model = self.ai_model.text().strip()
        if model and model != self.store.get(f"{provider}_model", PROVIDERS[provider]["model"]):
            self.store.put(f"{provider}_model", model)
            self.notice.notify("Model saved.", "success")

    def save_api_key(self):
        api_key = self.ai_key.text().strip()
        if not api_key:
            self.notice.notify(f"Paste a {self.provider.currentText()} API key before saving.", "warning")
            return
        try:
            self.store._vault().set(f"{self.provider.currentData()}-api-key", api_key)
            self.save_model()
        except Exception:
            self.notice.notify("Couldn't save the key to the system keychain. Nothing was written to disk.", "danger")
            return
        self.ai_key.clear()
        self.key_status.setText("A key is stored in the system keychain.")
        self.notice.notify("Key saved to the system keychain.", "success")


class MainWindow(QMainWindow):
    PAGES = ("Applications", "Profile", "Answers", "Settings", "Scout")

    def __init__(self, store=None):
        super().__init__()
        self.setWindowTitle("Intern-Bot")
        install_edit_shortcuts(QGuiApplication.instance())
        self.resize(1280, 780)
        self.setMinimumSize(1040, 660)
        self.store = store or LocalStore()
        self.nav_buttons = []

        shell = QWidget()
        shell.setObjectName("appShell")
        self.setCentralWidget(shell)
        root = QVBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.tasks_view = TasksView(self.store)
        self.profile_view = ProfileView(self.store)
        self.answers_view = AnswersView(self.store)
        self.settings_view = SettingsView(self.store)
        self.scout_view = ScoutView(self.store)
        self.scout_view.prepare_requested.connect(self.prepare_opportunity)
        self.scout_view.attention.connect(self.scout_attention)
        root.addWidget(self._build_navigation())
        self.stack = QStackedWidget()
        for view in (self.tasks_view, self.profile_view, self.answers_view, self.settings_view, self.scout_view):
            self.stack.addWidget(view)
        root.addWidget(self.stack, 1)

        self.tasks_view.changed.connect(self.update_status)
        self.tasks_view.open_profile.connect(self.open_profile_section)
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: self.tasks_view.render())
        for index in range(len(self.PAGES)):
            shortcut(f"Ctrl+{index + 1}", self, lambda i=index: self._select_nav(i))
        shortcut(QKeySequence.New, self, lambda: (self._select_nav(0), self.tasks_view.focus_paste()))
        shortcut(QKeySequence.Find, self, lambda: (self._select_nav(0), self.tasks_view.search.setFocus()))
        shortcut("Ctrl+R", self, lambda: (self._select_nav(0), self.tasks_view.primary_action()))
        self._select_nav(0)
        self.update_status()
        self.tasks_view.table.setFocus()

    def _build_navigation(self):
        strip = QFrame()
        strip.setObjectName("navigation")
        row = QHBoxLayout(strip)
        row.setContentsMargins(22, 7, 22, 7)
        row.setSpacing(5)
        brand = QLabel("Intern-Bot")
        brand.setObjectName("brand")
        row.addWidget(brand)
        row.addSpacing(20)
        for index, text in enumerate(self.PAGES):
            nav = button(text)
            nav.setObjectName("navButton")
            nav.setCheckable(True)
            nav.setToolTip(f"{text} (⌘{index + 1})")
            nav.clicked.connect(lambda checked=False, i=index: self._select_nav(i))
            row.addWidget(nav)
            self.nav_buttons.append(nav)
            if text in ("Applications", "Scout"):
                badge = QLabel()
                badge.setObjectName("navBadge")
                badge.setAlignment(Qt.AlignCenter)
                badge.hide()
                row.addWidget(badge)
                if index == 0:
                    self.badge = badge
                else:
                    self.scout_badge = badge
        row.addStretch()
        self.status_dot = QLabel()
        self.status_text = label(wrap=False)
        self.status_text.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.status_text.setMaximumWidth(250)
        row.addWidget(self.status_dot)
        row.addWidget(self.status_text)
        return strip

    def update_status(self):
        view = self.tasks_view
        needs = sum(status_meta(run)[2] == "Needs you" for run in view.tasks)
        self.badge.setText(str(needs))
        self.badge.setVisible(bool(needs))
        self.nav_buttons[0].setAccessibleName(f"Applications, {needs} need you" if needs else "Applications")
        active = next((run for run in view.tasks if run.id == view._active_id), None)
        if active:
            tone = "info"
            text = f"Running · {active.company or site_key(active.job_url)}" + (f" · {len(view._queue)} queued" if view._queue else "")
        elif needs:
            tone, text = "warning", f"{needs} {'needs' if needs == 1 else 'need'} you"
        else:
            tone, text = "neutral", "Idle"
        self.status_dot.setPixmap(dot_icon(tone).pixmap(16, 16))
        self.status_text.setToolTip(text)
        self.status_text.setText(self.status_text.fontMetrics().elidedText(text, Qt.ElideRight, 245))

    def scout_attention(self, text):
        nav = self.nav_buttons[self.PAGES.index("Scout")]
        self.scout_badge.setText("!")
        self.scout_badge.setVisible(bool(text))
        nav.setToolTip(text or f"Scout (⌘{self.PAGES.index('Scout') + 1})")
        nav.setAccessibleName(f"Scout, {text}" if text else "Scout")

    def _select_nav(self, index: int):
        self.stack.setCurrentIndex(index)
        for button_index, nav in enumerate(self.nav_buttons):
            nav.setChecked(button_index == index)

    def open_profile_section(self, section):
        self._select_nav(1)
        self.profile_view.editor.show_section(section)

    def prepare_opportunity(self, opportunity):
        self._select_nav(0)
        self.tasks_view.prepare_opportunity(opportunity)

    def closeEvent(self, event):
        if not self.scout_view.shutdown():
            event.ignore()
            return
        self.tasks_view.shutdown()
        super().closeEvent(event)
