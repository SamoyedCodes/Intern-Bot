from core.automation.assistant import DEFAULT_MODEL
from core.automation.models import site_key
from core.storage.local_store import LocalStore

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.theme import form_layout, MessageBar, button, card, dot_icon, label, shortcut
from gui.views.application_dialogs import AnswersView
from gui.views.profile_view import ProfileView
from gui.views.tasks_view import TasksView, status_meta

SAFETY_FACTS = [
    "Browser: bundled Chromium with local adapters, always visible.",
    "Final submission is yours by default. Automatic submission needs your authorization for each application and stops if anything can't be verified.",
    "Applications run in a separate, visible Chromium window. Employers may ask you to sign in again.",
    "Profiles, answers and history stay in a local database on this Mac. Employer logins and API keys are kept only in the system keychain.",
    "Browser observations are never sent to AI.",
    "Preview: adapters are tested against fictional forms. Live employer acceptance testing is still pending.",
]


class SettingsView(QWidget):
    def __init__(self, store=None):
        super().__init__()
        self.store = store or LocalStore()
        self._key_checked = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        page = QWidget()
        page.setObjectName("scrollContent")
        scroll.setWidget(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(label("Settings", "pageTitle"))
        layout.addWidget(label("Changes save automatically and apply to new applications. Existing applications keep the settings they started with.", "muted"))
        self.notice = MessageBar()
        layout.addWidget(self.notice)

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
        box.addWidget(label("Only exact question matches within an answer's scope, profile and country are reused.", "caption"))
        for checkbox in (self.auto_advance, self.reuse_answers):
            checkbox.toggled.connect(self.save_options)
        layout.addWidget(frame)

        frame, box = card()
        box.addWidget(label("AI assistance (optional)", "section"))
        box.addWidget(label("Gemini drafts answers and compares profiles only when you ask. Every request shows its full context and needs your consent.", "muted"))
        form = form_layout(10)
        self.gemini_model = QLineEdit(self.store.get("gemini_model", DEFAULT_MODEL))
        self.gemini_model.editingFinished.connect(self.save_model)
        form.addRow("Model", self.gemini_model)
        self.gemini_key = QLineEdit()
        self.gemini_key.setEchoMode(QLineEdit.Password)
        self.gemini_key.setPlaceholderText("Paste a Gemini API key")
        self.save_api_key_btn = button("Save key", self.save_api_key, "primary")
        key_row = QHBoxLayout()
        key_row.addWidget(self.gemini_key, 1)
        key_row.addWidget(self.save_api_key_btn)
        form.addRow("API key", key_row)
        self.key_status = label(role="caption")
        form.addRow("", self.key_status)
        box.addLayout(form)
        layout.addWidget(frame)

        frame, box = card(6)
        box.addWidget(label("Safety and privacy", "section"))
        for fact in SAFETY_FACTS:
            box.addWidget(label("✓  " + fact, "fact"))
        layout.addWidget(frame)
        layout.addStretch()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._key_checked:
            self._key_checked = True
            try:
                saved = bool(self.store._vault().get("gemini-api-key"))
                self.key_status.setText("A key is stored in the system keychain." if saved else "No key saved yet.")
            except Exception:
                self.key_status.setText("Couldn't read the system keychain.")

    def save_options(self):
        self.store.put("automation_options", {"browser": "chromium",
                       "auto_advance": self.auto_advance.isChecked(), "reuse_answers": self.reuse_answers.isChecked()})
        self.notice.notify("Saved. New applications use these defaults.", "success")

    def save_model(self):
        model = self.gemini_model.text().strip()
        if model and model != self.store.get("gemini_model", DEFAULT_MODEL):
            self.store.put("gemini_model", model)
            self.notice.notify("Model saved.", "success")

    def save_api_key(self):
        api_key = self.gemini_key.text().strip()
        if not api_key:
            self.notice.notify("Paste a Gemini API key before saving.", "warning")
            return
        try:
            self.store._vault().set("gemini-api-key", api_key)
            self.save_model()
        except Exception:
            self.notice.notify("Couldn't save the key to the system keychain. Nothing was written to disk.", "danger")
            return
        self.gemini_key.clear()
        self.key_status.setText("A key is stored in the system keychain.")
        self.notice.notify("Key saved to the system keychain.", "success")


class MainWindow(QMainWindow):
    PAGES = ("Applications", "Profile", "Answers", "Settings")

    def __init__(self, store=None):
        super().__init__()
        self.setWindowTitle("Intern-Bot")
        self.resize(1280, 780)
        self.setMinimumSize(1040, 660)
        self.store = store or LocalStore()
        self.nav_buttons = []

        shell = QWidget()
        shell.setObjectName("appShell")
        self.setCentralWidget(shell)
        root = QHBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.tasks_view = TasksView(self.store)
        self.profile_view = ProfileView(self.store)
        self.answers_view = AnswersView(self.store)
        self.settings_view = SettingsView(self.store)
        root.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        for view in (self.tasks_view, self.profile_view, self.answers_view, self.settings_view):
            self.stack.addWidget(view)
        root.addWidget(self.stack, 1)

        self.tasks_view.changed.connect(self.update_status)
        self.tasks_view.open_profile.connect(self.open_profile_section)
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: self.tasks_view.render())
        for index in range(len(self.PAGES)):
            shortcut(f"Ctrl+{index + 1}", self, lambda i=index: self._select_nav(i))
        shortcut(QKeySequence.New, self, lambda: (self._select_nav(0), self.tasks_view.add_dialog()))
        shortcut(QKeySequence.Find, self, lambda: (self._select_nav(0), self.tasks_view.search.setFocus()))
        shortcut("Ctrl+R", self, lambda: (self._select_nav(0), self.tasks_view.primary_action()))
        self._select_nav(0)
        self.update_status()
        self.tasks_view.table.setFocus()

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(208)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 18, 12, 14)
        layout.setSpacing(2)
        brand = QLabel("Intern-Bot")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        layout.addWidget(label("Local application desk", "caption"))
        layout.addSpacing(18)
        for index, text in enumerate(self.PAGES):
            nav = QPushButton(text)
            nav.setObjectName("navButton")
            nav.setCheckable(True)
            nav.setCursor(Qt.PointingHandCursor)
            nav.setToolTip(f"{text} (⌘{index + 1})")
            nav.clicked.connect(lambda checked=False, i=index: self._select_nav(i))
            if index == 0:
                row = QHBoxLayout(nav)
                row.setContentsMargins(0, 0, 8, 0)
                row.addStretch()
                self.badge = QLabel()
                self.badge.setObjectName("navBadge")
                self.badge.setAlignment(Qt.AlignCenter)
                self.badge.setAttribute(Qt.WA_TransparentForMouseEvents)
                row.addWidget(self.badge)
            layout.addWidget(nav)
            self.nav_buttons.append(nav)
        layout.addStretch()
        status = QFrame()
        status.setObjectName("engineStatus")
        row = QHBoxLayout(status)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(6)
        self.status_dot = QLabel()
        self.status_text = label()
        row.addWidget(self.status_dot, 0, Qt.AlignTop)
        row.addWidget(self.status_text, 1)
        layout.addWidget(status)
        return sidebar

    def update_status(self):
        view = self.tasks_view
        needs = sum(status_meta(run)[2] == "Needs you" for run in view.tasks)
        self.badge.setText(str(needs))
        self.badge.setVisible(bool(needs))
        self.nav_buttons[0].setAccessibleName(f"Applications, {needs} need you" if needs else "Applications")
        active = next((run for run in view.tasks if run.id == view._active_id), None)
        if active:
            tone = "info"
            text = f"Running · {active.company or site_key(active.job_url)}" + (f"\n{len(view._queue)} more queued" if view._queue else "")
        elif needs:
            tone, text = "warning", f"{needs} {'needs' if needs == 1 else 'need'} you"
        else:
            tone, text = "neutral", "Idle"
        self.status_dot.setPixmap(dot_icon(tone).pixmap(16, 16))
        self.status_text.setText(text)

    def _select_nav(self, index: int):
        self.stack.setCurrentIndex(index)
        for button_index, nav in enumerate(self.nav_buttons):
            nav.setChecked(button_index == index)

    def open_profile_section(self, section):
        self._select_nav(1)
        self.profile_view.editor.show_section(section)

    def closeEvent(self, event):
        self.tasks_view.shutdown()
        super().closeEvent(event)
