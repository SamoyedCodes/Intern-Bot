from core.automation.assistant import DEFAULT_MODEL
from core.storage.local_store import LocalStore

from PySide6.QtWidgets import (
    QFormLayout,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.views.profile_view import ProfileView
from gui.views.tasks_view import TasksView


class SettingsView(QWidget):
    def __init__(self, store=None):
        super().__init__()
        self.store = store or LocalStore()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(14)

        title = QLabel("Automation Settings")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Defaults for new applications. Existing applications keep their saved settings.")
        subtitle.setObjectName("pageSubtitle")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        panel = QFrame()
        panel.setObjectName("settingsPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 18, 18, 18)
        panel_layout.setSpacing(12)
        options = self.store.get("automation_options", {})
        self.browser = QComboBox()
        for label, value in [("Chromium (bundled, local adapters)", "chromium")]:
            self.browser.addItem(label, value)
        self.browser.setCurrentIndex(max(0, self.browser.findData(options.get("browser", "chromium"))))
        panel_layout.addWidget(QLabel("Browser"))
        panel_layout.addWidget(self.browser)
        self.auto_advance = QCheckBox("Automatically continue after verifying each section")
        self.auto_advance.setChecked(options.get("auto_advance", True))
        self.reuse_answers = QCheckBox("Reuse explicitly approved answers")
        self.reuse_answers.setChecked(options.get("reuse_answers", True))
        panel_layout.addWidget(self.auto_advance)
        panel_layout.addWidget(self.reuse_answers)
        save_options = QPushButton("Save automation defaults")
        save_options.clicked.connect(self.save_options)
        panel_layout.addWidget(save_options)

        api_form = QFormLayout()
        self.gemini_model = QLineEdit(self.store.get("gemini_model", DEFAULT_MODEL))
        api_form.addRow("Gemini model", self.gemini_model)
        self.gemini_key = QLineEdit()
        self.gemini_key.setEchoMode(QLineEdit.Password)
        self.gemini_key.setPlaceholderText("GEMINI_API_KEY")


        self.save_api_key_btn = QPushButton("Save API Key")
        self.save_api_key_btn.setObjectName("primaryButton")
        self.save_api_key_btn.clicked.connect(self.save_api_key)

        api_row = QHBoxLayout()
        api_row.addWidget(self.gemini_key)
        api_row.addWidget(self.save_api_key_btn)
        api_form.addRow("Gemini API Key", api_row)
        panel_layout.addLayout(api_form)

        items = [
            "Browser mode: visible",
            "Final submit: manual by default; opt in separately for each new application",
            "Session storage: Playwright persistent profile",
            "Gemini drafts / profile comparison: explicit context preview and consent per request",
            "AI browser recovery: disabled; no browser observations are sent",
        ]
        for text in items:
            label = QLabel(text)
            label.setObjectName("settingLine")
            panel_layout.addWidget(label)

        layout.addWidget(panel)
        layout.addStretch()

        self.status = QLabel("")
        self.status.setObjectName("settingStatus")
        layout.addWidget(self.status)

    def save_options(self):
        self.store.put("automation_options", {"browser": self.browser.currentData(),
                       "auto_advance": self.auto_advance.isChecked(), "reuse_answers": self.reuse_answers.isChecked()})
        self.store.put("gemini_model", self.gemini_model.text().strip())
        self.status.setText("Defaults saved. Existing applications resume in bundled Chromium; employer sign-in may be required again.")

    def save_api_key(self):
        api_key = self.gemini_key.text().strip()
        if not api_key:
            self.status.setText("Enter a Gemini API key before saving.")
            return

        try:
            self.store._vault().set("gemini-api-key", api_key)
            self.store.put("gemini_model", self.gemini_model.text().strip())
        except Exception:
            self.status.setText("Could not save the key to the operating-system keychain. Nothing was written to disk.")
            return
        self.gemini_key.clear()
        self.status.setText("API key saved to the OS keychain. Drafts and comparisons require a separate request and context review.")



class MainWindow(QMainWindow):
    def __init__(self, store=None):
        super().__init__()
        self.setWindowTitle("Intern-Bot")
        self.resize(1280, 760)
        self.setMinimumSize(1080, 680)

        self.nav_buttons = []

        shell = QWidget()
        shell.setObjectName("appShell")
        self.setCentralWidget(shell)

        root = QHBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        content = QWidget()
        content.setObjectName("contentArea")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        content_layout.addWidget(self._build_topbar())

        self.stack = QStackedWidget()
        self.store = store or LocalStore()
        self.profile_view = ProfileView(self.store)
        self.tasks_view = TasksView(self.store)
        self.settings_view = SettingsView(self.store)


        self.stack.addWidget(self.tasks_view)
        self.stack.addWidget(self.profile_view)
        self.stack.addWidget(self.settings_view)
        content_layout.addWidget(self.stack)

        root.addWidget(content)
        self._select_nav(0)

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(10)

        brand = QLabel("Intern-Bot")
        brand.setObjectName("brand")
        tagline = QLabel("Local application desk")
        tagline.setObjectName("brandTagline")
        layout.addWidget(brand)
        layout.addWidget(tagline)
        layout.addSpacing(20)

        for index, text in enumerate(["Tasks", "Profile", "Settings"]):
            button = QPushButton(text)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self._select_nav(i))
            layout.addWidget(button)
            self.nav_buttons.append(button)

        layout.addStretch()

        footer = QLabel("Review before submit")
        footer.setObjectName("sidebarFooter")
        layout.addWidget(footer)
        return sidebar

    def _build_topbar(self):
        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(72)

        layout = QHBoxLayout(topbar)
        layout.setContentsMargins(24, 0, 24, 0)

        self.section_title = QLabel("Tasks")
        self.section_title.setObjectName("sectionTitle")
        layout.addWidget(self.section_title)
        layout.addStretch()

        status = QLabel("Local automation")
        status.setObjectName("topStatus")
        layout.addWidget(status)
        return topbar

    def _select_nav(self, index: int):
        self.stack.setCurrentIndex(index)
        names = ["Tasks", "Profile", "Settings"]
        self.section_title.setText(names[index])
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)

    def closeEvent(self, event):
        self.tasks_view.shutdown()
        super().closeEvent(event)
