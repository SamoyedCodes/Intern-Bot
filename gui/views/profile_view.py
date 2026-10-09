"""Single structured applicant profile and explicit employer credential editor."""
import secrets
import string
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from core.automation.models import ApplicantProfile, ats_name, canonical_url, site_key
from core.storage.local_store import LocalStore
from gui.views.application_dialogs import AnswerBankDialog, ProfileEditor


class ProfileView(QWidget):
    def __init__(self, store=None):
        super().__init__()
        self.store = store or LocalStore()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        title = QLabel("Applicant Profile")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        profile_row = QHBoxLayout()
        self.profile_names = QComboBox()
        self.profile_names.addItems(self.store.profiles())
        self.profile_names.setCurrentText(self.store.get("active_profile", "Default"))
        self.profile_names.currentTextChanged.connect(self.switch_profile)
        profile_row.addWidget(QLabel("Active profile"))
        profile_row.addWidget(self.profile_names)
        for label, callback in [("Save as new profile", self.copy_profile), ("Import JSON", self.import_profile), ("Export JSON", self.export_profile)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            profile_row.addWidget(button)
        layout.addLayout(profile_row)
        actions = QHBoxLayout()
        save = QPushButton("Save profile")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_profile)
        answers = QPushButton("Approved answers")
        answers.clicked.connect(lambda: AnswerBankDialog(self.store, self).exec())
        actions.addWidget(save)
        actions.addWidget(answers)
        actions.addStretch()
        layout.addLayout(actions)
        tabs = QTabWidget()
        self.editor = ProfileEditor(ApplicantProfile.model_validate(self.store.get("verified_profile", {})))
        tabs.addTab(self.editor, "Applicant details")
        tabs.addTab(self._credentials_page(), "Workday credentials")
        layout.addWidget(tabs)
        self.notice = QLabel("Save changes before starting a new application. Existing applications retain their own profile snapshot.")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)

    def save_profile(self):
        try:
            self.store.save_profile(self.profile_names.currentText(), self.editor.profile())
        except ValueError:
            self.notice.setText("Check the profile values. Current must be true, false, or blank.")
            return False
        except Exception:
            self.notice.setText("Could not save the profile. Check local data access and retry.")
            return False
        self.notice.setText("Profile saved locally.")
        return True

    def switch_profile(self, name):
        old_name = self.store.get("active_profile", "Default")
        try:
            self.store.save_profile(old_name, self.editor.profile())
            profile = self.store.profiles()[name]
            self.store.save_profile(name, profile)
            self.editor.load_profile(profile)
            self.notice.setText(f"Active profile: {name}. Previous edits saved locally.")
        except (ValueError, KeyError):
            self.profile_names.blockSignals(True)
            self.profile_names.setCurrentText(old_name)
            self.profile_names.blockSignals(False)
            self.notice.setText("Fix the current profile before switching.")

    def copy_profile(self):
        name, ok = QInputDialog.getText(self, "New profile", "Profile name")
        if ok:
            self.save_named(name)

    def save_named(self, name, profile=None):
        try:
            if name.strip() in self.store.profiles():
                raise ValueError("That profile name already exists.")
            self.store.save_profile(name, profile or self.editor.profile())
            self.profile_names.blockSignals(True)
            self.profile_names.addItem(name.strip())
            self.profile_names.setCurrentText(name.strip())
            self.profile_names.blockSignals(False)
            self.editor.load_profile(self.store.profiles()[name.strip()])
            self.notice.setText("Profile saved locally.")
        except ValueError as exc:
            self.notice.setText(str(exc))

    def import_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import applicant profile", "", "JSON (*.json)")
        if not path:
            return
        try:
            profile = ApplicantProfile.model_validate_json(Path(path).read_text(encoding="utf-8"))
            name, ok = QInputDialog.getText(self, "Imported profile", "New profile name", text=Path(path).stem)
            if ok:
                self.save_named(name, profile)
        except (ValueError, OSError):
            self.notice.setText("Could not import a valid Intern-Bot profile JSON file.")

    def export_profile(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export profile (contains personal information)", "profile.json", "JSON (*.json)")
        if path:
            try:
                Path(path).write_text(self.editor.profile().model_dump_json(indent=2), encoding="utf-8")
                self.notice.setText("Profile exported. Resume and cover letter paths are included; files and credentials are not.")
            except (ValueError, OSError):
                self.notice.setText("Could not export profile. Check values and file access.")

    def _credentials_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel("Credentials are stored in the operating-system keychain. Enter an employer site to load or save its login.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.site = QLineEdit()
        self.site.setPlaceholderText("company.wd1.myworkdayjobs.com")
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.catchall = QLineEdit(self.store.get("catchall_domain", ""))
        self.catchall.setPlaceholderText("applications.example.com (optional)")
        for label, widget in [("Employer site", self.site), ("Username / email", self.username), ("Password", self.password), ("Catchall domain", self.catchall)]:
            form.addRow(label, widget)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        for label, callback in [("Load login", self.load_credential), ("Generate login", self.generate_credential), ("Save login", self.save_credential)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        layout.addStretch()
        return page

    def credential_site(self):
        value = self.site.text().strip()
        if ats_name(value) != "Workday":
            raise ValueError("Use a Workday employer site for saved credentials.")
        return site_key(canonical_url(value if "://" in value else "https://" + value))

    def load_credential(self):
        try:
            value = self.store._vault().credential(self.credential_site())
            self.username.setText(value.get("username", ""))
            self.password.setText(value.get("password", ""))
            self.notice.setText("Login loaded from keychain." if value else "No saved login for this employer.")
        except Exception:
            self.notice.setText("Could not load login. Check the employer site and keychain access.")

    def generate_credential(self):
        try:
            site = self.credential_site()
            domain = self.catchall.text().strip().lstrip("@")
            email = self.editor.profile().email
            if domain:
                if any(c.isspace() for c in domain) or "/" in domain or "@" in domain or "." not in domain:
                    raise ValueError("Invalid catchall domain")
                email = site.split('.')[0].replace('-', '_') + "_intern@" + domain
            if not email or "@" not in email:
                raise ValueError("An email is required")
            chars = [secrets.choice(pool) for pool in (string.ascii_lowercase, string.ascii_uppercase, string.digits, "!@#$%^&*")]
            chars += [secrets.choice(string.ascii_letters + string.digits + "!@#$%^&*") for _ in range(14)]
            secrets.SystemRandom().shuffle(chars)
            self.username.setText(email)
            self.password.setText("".join(chars))
            self.notice.setText("Login generated locally. Save it before starting this employer's application.")
        except ValueError:
            self.notice.setText("Enter a valid Workday employer site and your email or catchall domain first.")

    def save_credential(self):
        try:
            site = self.credential_site()
            username, password = self.username.text().strip(), self.password.text()
            if not username or not password:
                raise ValueError("Missing login")
            self.store._vault().save_credential(site, username, password)
            self.store.put("catchall_domain", self.catchall.text().strip().lstrip("@"))
            self.password.clear()
            self.notice.setText("Login saved to the operating-system keychain.")
        except Exception:
            self.notice.setText("Could not save login. Check the site, username, password and keychain access.")
