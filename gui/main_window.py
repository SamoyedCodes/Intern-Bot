import os
from pathlib import Path

from PySide6.QtWidgets import (
    QFormLayout,
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
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(14)

        title = QLabel("Automation Settings")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Keep final submit manual, run visible browsers, and reuse Workday sessions.")
        subtitle.setObjectName("pageSubtitle")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        panel = QFrame()
        panel.setObjectName("settingsPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 18, 18, 18)
        panel_layout.setSpacing(12)

        api_form = QFormLayout()
        self.gemini_key = QLineEdit()
        self.gemini_key.setEchoMode(QLineEdit.Password)
        self.gemini_key.setPlaceholderText("GEMINI_API_KEY")
        self.gemini_key.setText(os.environ.get("GEMINI_API_KEY", ""))

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
            "Final submit: manual review required",
            "Session storage: Playwright persistent profile",
            "LLM mapping: Gemini field mapper when deterministic selectors are not enough",
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

    def save_api_key(self):
        api_key = self.gemini_key.text().strip()
        if not api_key:
            self.status.setText("Enter a Gemini API key before saving.")
            return

        os.environ["GEMINI_API_KEY"] = api_key
        self._write_env_value("GEMINI_API_KEY", api_key)
        self.status.setText("Gemini API key saved for this session and .env.")

    def _write_env_value(self, key, value):
        env_path = Path(".env")
        lines = []
        found = False

        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()

        updated = []
        for line in lines:
            if line.startswith(f"{key}="):
                updated.append(f"{key}={value}")
                found = True
            else:
                updated.append(line)

        if not found:
            updated.append(f"{key}={value}")

        env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


class MainWindow(QMainWindow):
    def __init__(self, scheduler=None):
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
        self.profile_view = ProfileView()
        self.tasks_view = TasksView(profile_provider=self.profile_view.to_profile_dict)
        self.settings_view = SettingsView()

        self.tasks_view.status_message.connect(self.set_status)

        self.stack.addWidget(self.tasks_view)
        self.stack.addWidget(self.profile_view)
        self.stack.addWidget(self.settings_view)
        content_layout.addWidget(self.stack)

        self.status = QLabel("Ready")
        self.status.setObjectName("statusBar")
        content_layout.addWidget(self.status)

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
        tagline = QLabel("Workday application desk")
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

    def set_status(self, message: str):
        self.status.setText(message)
