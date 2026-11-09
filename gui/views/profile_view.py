"""Applicant profiles (sectioned editor) and explicit employer credential editor."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLineEdit, QMenu, QProgressBar, QVBoxLayout, QWidget,
)

from core.automation.accounts import DEFAULT_CATCHALL_FORMAT, login_address
from core.automation.models import ApplicantProfile, ats_name, canonical_url, site_key
from core.storage.local_store import LocalStore
from core.storage.onepassword import VAULT
from core.storage.vault import TOKEN_KEY
from gui.theme import form_layout, MessageBar, button, card, label, more_button, shortcut, station_heading
from gui.views.application_dialogs import ProfileEditor

ESSENTIALS = {"first_name": "first name", "last_name": "last name", "email": "email", "phone": "phone", "resume_path": "resume"}


class ProfileView(QWidget):
    def __init__(self, store=None):
        super().__init__()
        self.store = store or LocalStore()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(station_heading("Profile", "fill", "The facts and documents used to prepare new applications."), 1)
        self.profile_names = QComboBox()
        self.profile_names.setAccessibleName("Profile")
        self.profile_names.setMinimumWidth(160)
        self.profile_names.addItems(self.store.profiles())
        self.profile_names.setCurrentText(self.store.get("active_profile", "Default"))
        self.profile_names.currentTextChanged.connect(self.switch_profile)
        header.addWidget(self.profile_names)
        menu = QMenu(self)
        menu.addAction("New profile from this one…", self.copy_profile)
        menu.addAction("Import JSON…", self.import_profile)
        menu.addAction("Export JSON…", self.export_profile)
        header.addWidget(more_button(menu, "Profile actions"))
        self.save_btn = button("Save profile", self.save_profile, "primary", "Save profile (⌘S)")
        header.addWidget(self.save_btn)
        layout.addLayout(header)
        status = QHBoxLayout()
        self.essentials = label(role="caption")
        self.unsaved = label("Unsaved changes", "caption")
        self.unsaved.setProperty("tone", "warning")
        self.readiness = QProgressBar()
        self.readiness.setRange(0, len(ESSENTIALS))
        self.readiness.setTextVisible(False)
        self.readiness.setFixedWidth(115)
        self.readiness.setAccessibleName("Profile essentials completed")
        status.addWidget(self.readiness)
        status.addWidget(self.essentials, 1)
        status.addWidget(self.unsaved)
        layout.addLayout(status)
        self.notice = MessageBar()
        layout.addWidget(self.notice)
        self.editor = ProfileEditor(ApplicantProfile.model_validate(self.store.get("verified_profile", {})))
        self.editor.add_section("Workday logins", self._credentials_page())
        self.editor.changed.connect(lambda: self.set_dirty(True))
        layout.addWidget(self.editor, 1)
        shortcut(QKeySequence.Save, self, self.save_profile, Qt.WidgetWithChildrenShortcut)
        self.set_dirty(False)

    def set_dirty(self, dirty):
        self.unsaved.setVisible(dirty)
        self.save_btn.setEnabled(dirty)
        missing = [name for key, name in ESSENTIALS.items() if not self.editor.inputs[key].text().strip()]
        self.readiness.setValue(len(ESSENTIALS) - len(missing))
        self.essentials.setText(f"{len(ESSENTIALS) - len(missing)} of {len(ESSENTIALS)} essentials"
                                + (f" · missing {', '.join(missing)}" if missing else " · ready to apply"))

    def save_profile(self):
        try:
            self.store.save_profile(self.profile_names.currentText(), self.editor.profile())
        except ValueError:
            self.notice.notify("Check the profile values. Age must be a whole number or blank.", "danger")
            return False
        except Exception:
            self.notice.notify("Couldn't save the profile. Check local data access and try again.", "danger")
            return False
        self.set_dirty(False)
        self.notice.notify("Profile saved. New applications use it; existing ones keep their own snapshot.", "success")
        return True

    def switch_profile(self, name):
        old_name = self.store.get("active_profile", "Default")
        try:
            self.store.save_profile(old_name, self.editor.profile())
            profile = self.store.profiles()[name]
            self.store.save_profile(name, profile)
            self.editor.load_profile(profile)
            self.set_dirty(False)
            self.notice.notify(f"Switched to {name}. Your edits to {old_name} were saved.", "success")
        except (ValueError, KeyError):
            self.profile_names.blockSignals(True)
            self.profile_names.setCurrentText(old_name)
            self.profile_names.blockSignals(False)
            self.notice.notify("Fix the current profile before switching.", "danger")

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
            self.set_dirty(False)
            self.notice.notify(f"Profile {name.strip()} created and selected.", "success")
        except ValueError as exc:
            self.notice.notify(str(exc), "danger")

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
            self.notice.notify("That file isn't a valid Intern-Bot profile JSON file.", "danger")

    def export_profile(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export profile (contains personal information)", "profile.json", "JSON (*.json)")
        if path:
            try:
                Path(path).write_text(self.editor.profile().model_dump_json(indent=2), encoding="utf-8")
                self.notice.notify("Profile exported. It includes personal details and document paths, but not the files or credentials.", "success")
            except (ValueError, OSError):
                self.notice.notify("Couldn't export the profile. Check its values and file access.", "danger")

    def _credentials_page(self):
        frame, box = card()
        box.addWidget(label("Workday logins", "section"))
        box.addWidget(label(f"Stored in your 1Password “{VAULT}” vault and matched by the employer's Workday address, so you can add or edit logins in 1Password. "
                            "Each login is used only for that employer's sign-in. CAPTCHA, activation and unfamiliar sign-in steps stay manual.", "muted"))
        form = form_layout(10)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("ops_… (saved to the macOS keychain)")
        self.site = QLineEdit()
        self.site.setPlaceholderText("company.wd1.myworkdayjobs.com")
        self.catchall = QLineEdit(self.store.get("catchall_domain", ""))
        self.catchall.setPlaceholderText("applications.example.com (optional)")
        self.catchall_format = QLineEdit(self.store.get("catchall_format", ""))
        self.catchall_format.setPlaceholderText(DEFAULT_CATCHALL_FORMAT)
        for text, widget in [("Service account token", self.token), ("Employer site", self.site), ("Catch-all domain", self.catchall), ("Catch-all address", self.catchall_format)]:
            form.addRow(text, widget)
        box.addLayout(form)
        self.token_status = label(role="caption")
        box.addWidget(self.token_status)
        self.show_token_status()
        self.address_preview = label(role="caption")
        box.addWidget(self.address_preview)
        self.auto_create = QCheckBox("Create Workday accounts automatically when no login is saved")
        self.auto_create.setChecked(self.store.get("auto_create_workday_accounts", False))
        self.auto_create.setToolTip("1Password generates and stores the login, the bot creates the account, then waits for you to verify the email.")
        box.addWidget(self.auto_create)
        for widget in (self.catchall, self.catchall_format):
            widget.textChanged.connect(self.preview_address)
            widget.editingFinished.connect(self.save_account_settings)
        self.auto_create.toggled.connect(self.save_account_settings)
        self.preview_address()
        buttons = QHBoxLayout()
        buttons.addWidget(button("Save token", self.save_token))
        buttons.addWidget(button("Check login", self.check_credential))
        buttons.addWidget(button("Import keychain logins", self.import_keychain_logins))
        buttons.addStretch()
        buttons.addWidget(button("Create login in 1Password", self.create_credential, "primary"))
        box.addLayout(buttons)
        box.addStretch()
        return frame

    def credential_site(self):
        value = self.site.text().strip()
        if ats_name(value) != "Workday":
            raise ValueError("Use a Workday employer site for saved credentials.")
        return site_key(canonical_url(value if "://" in value else "https://" + value))

    def preview_address(self):
        domain = self.catchall.text().strip()
        try:
            example = login_address("company.wd1.myworkdayjobs.com", "you@example.com", domain, self.catchall_format.text())
            self.address_preview.setText(f"New accounts use addresses like {example}. {{company}} becomes the employer's Workday name." if domain
                                         else "Without a catch-all domain, new accounts use your profile email.")
        except ValueError:
            self.address_preview.setText("That catch-all domain or address isn't a valid email address.")

    def save_account_settings(self):
        self.store.put("catchall_domain", self.catchall.text().strip().lstrip("@"))
        self.store.put("catchall_format", self.catchall_format.text().strip())
        self.store.put("auto_create_workday_accounts", self.auto_create.isChecked())

    def show_token_status(self):
        saved = bool(self.store._vault().get(TOKEN_KEY))
        self.token_status.setText("Service account token saved." if saved else
                                  f"No token yet. Create a 1Password service account with access to “{VAULT}” only, then paste its token.")

    def save_token(self):
        token = self.token.text().strip()
        self.token.clear()
        if not token:
            self.notice.notify("Paste a 1Password service account token first.", "warning")
            return
        vault = self.store._vault()
        previous = vault.get(TOKEN_KEY)
        try:
            vault.set(TOKEN_KEY, token)
            vault.logins.check()
        except Exception as exc:
            vault.set(TOKEN_KEY, previous)  # Keep the last working token rather than a bad one.
            self.notice.notify(str(exc) if isinstance(exc, RuntimeError) else "Couldn't save the token to the keychain.", "danger")
            return
        self.show_token_status()
        self.notice.notify(f"Token saved. It can reach the “{VAULT}” vault.", "success")

    def check_credential(self):
        try:
            value = self.store._vault().credential(self.credential_site())
        except RuntimeError as exc:
            self.notice.notify(str(exc), "danger")
            return
        except ValueError:
            self.notice.notify("Enter a Workday employer site first.", "warning")
            return
        state = {"new": " The account hasn't been created yet.", "pending_verification": " Workday is waiting for you to verify the email."}.get(value.get("state"), "")
        self.notice.notify(f"1Password has a login for {value['username']}." + state if value else "No login for this employer in 1Password.",
                           "success" if value else "info")

    def create_credential(self):
        try:
            site = self.credential_site()
            username = login_address(site, self.editor.profile().email, self.catchall.text(), self.catchall_format.text())
            self.store._vault().save_credential(site, username, None, "new")
            self.save_account_settings()
            self.notice.notify(f"1Password generated and saved a login for {username}. The bot creates the Workday account on the next run.", "success")
        except RuntimeError as exc:
            self.notice.notify(str(exc), "danger")
        except ValueError as exc:
            self.notice.notify(str(exc) if "1Password" in str(exc) else "Enter a valid Workday employer site and your email or catch-all domain first.", "warning")

    def import_keychain_logins(self):
        vault = self.store._vault()
        # ponytail: the keychain can't list its keys, so only employers with a saved application are found.
        sites = sorted({site_key(run.job_url) for run in self.store.runs() if ats_name(run.job_url) == "Workday"})
        imported = skipped = 0
        try:
            for site in sites:
                old = vault.keychain_login(site)
                if not old:
                    continue
                if vault.credential(site):
                    skipped += 1
                    continue
                vault.save_credential(site, old["username"], old["password"], old["state"])
                imported += 1
        except RuntimeError as exc:
            self.notice.notify(f"Imported {imported} before stopping. {exc}", "danger")
            return
        self.notice.notify(f"Imported {imported} keychain login(s) into 1Password; {skipped} already there. The keychain copies stay as a backup.",
                           "success" if imported else "info")
