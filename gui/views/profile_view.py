import secrets
import string
from urllib.parse import urlparse

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.storage import JsonStore


class ProfileView(QWidget):
    """Applicant profile editor used by automation plugins."""

    def __init__(self):
        super().__init__()
        self.setObjectName("profileView")
        self.store = JsonStore()
        self._loading_state = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(18)

        header = QLabel("Applicant Profile")
        header.setObjectName("pageTitle")
        layout.addWidget(header)

        subtitle = QLabel("This profile is converted into the payload used by Workday form automation.")
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("profileTabs")
        self.tabs.addTab(self._build_applicant_tab(), "Applicant")
        self.tabs.addTab(self._build_credentials_tab(), "Workday Credentials")
        layout.addWidget(self.tabs)
        layout.addStretch()

        self._connect_persistence_signals()
        self.load_state()

    def _build_applicant_tab(self):
        tab = QWidget()
        tab.setObjectName("profileTabPage")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 18, 0, 0)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(18)

        self.identity_group = self._build_identity_group()
        self.links_group = self._build_links_group()
        self.education_group = self._build_education_group()
        self.answers_group = self._build_answers_group()

        grid.addWidget(self.identity_group, 0, 0)
        grid.addWidget(self.links_group, 0, 1)
        grid.addWidget(self.education_group, 1, 0)
        grid.addWidget(self.answers_group, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        layout.addLayout(grid)
        layout.addStretch()
        return tab

    def _build_credentials_tab(self):
        tab = QWidget()
        tab.setObjectName("profileTabPage")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 18, 0, 0)
        layout.setSpacing(14)

        controls = QHBoxLayout()
        self.catchall_domain = QLineEdit()
        self.catchall_domain.setPlaceholderText("Catchall domain, for example applications.yourdomain.com")

        self.add_credential_btn = QPushButton("Add Row")
        self.add_credential_btn.clicked.connect(lambda: self._upsert_credential_row("", "", "", save=True))

        self.delete_credentials_btn = QPushButton("Delete Selected")
        self.delete_credentials_btn.setObjectName("dangerButton")
        self.delete_credentials_btn.clicked.connect(self.delete_selected_credentials)

        controls.addWidget(QLabel("Catchall"))
        controls.addWidget(self.catchall_domain)
        controls.addWidget(self.add_credential_btn)
        controls.addWidget(self.delete_credentials_btn)
        layout.addLayout(controls)

        self.credentials_table = QTableWidget(0, 4)
        self.credentials_table.setHorizontalHeaderLabels(["", "Workday Site", "Username", "Password"])
        self.credentials_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.credentials_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.credentials_table.verticalHeader().setVisible(False)
        self.credentials_table.verticalHeader().setDefaultSectionSize(44)
        self.credentials_table.setShowGrid(False)
        self.credentials_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.credentials_table.horizontalHeader().resizeSection(0, 44)
        self.credentials_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.credentials_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.credentials_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.credentials_table.setWordWrap(False)
        layout.addWidget(self.credentials_table)

        hint = QLabel("When a Workday task starts, Intern-Bot will reuse a row for that site or generate one here.")
        hint.setObjectName("pageSubtitle")
        layout.addWidget(hint)
        return tab

    def _build_identity_group(self):
        box = QGroupBox("Identity")
        grid = self._new_form_grid(box)

        self.first_name = QLineEdit()
        self.last_name = QLineEdit()
        self.email = QLineEdit()
        self.phone = QLineEdit()
        self.address = QLineEdit()
        self.resume_path = QLineEdit()

        self.first_name.setPlaceholderText("Jane")
        self.last_name.setPlaceholderText("Applicant")
        self.email.setPlaceholderText("jane@example.com")
        self.phone.setPlaceholderText("+65 9000 0000")
        self.address.setPlaceholderText("City, Country")
        self.resume_path.setPlaceholderText("C:\\Users\\Albino\\Documents\\resume.pdf")

        self._add_form_row(grid, 0, "First name", self.first_name)
        self._add_form_row(grid, 1, "Last name", self.last_name)
        self._add_form_row(grid, 2, "Email", self.email)
        self._add_form_row(grid, 3, "Phone", self.phone)
        self._add_form_row(grid, 4, "Location", self.address)
        self._add_form_row(grid, 5, "Resume", self.resume_path)
        return box

    def _profile_fields(self):
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "resume_path": self.resume_path,
            "linkedin_url": self.linkedin_url,
            "github_url": self.github_url,
            "portfolio_url": self.portfolio_url,
            "school": self.school,
            "degree": self.degree,
            "major": self.major,
            "graduation": self.graduation,
            "catchall_domain": self.catchall_domain,
        }

    def _connect_persistence_signals(self):
        for widget in self._profile_fields().values():
            widget.editingFinished.connect(self.save_state)
        self.default_answers.textChanged.connect(self.save_state)
        self.credentials_table.itemChanged.connect(self._on_credential_item_changed)

    def _on_credential_item_changed(self, item):
        if item.column() == 0:
            return
        self.save_state()

    def _build_links_group(self):
        box = QGroupBox("Links")
        grid = self._new_form_grid(box)

        self.linkedin_url = QLineEdit()
        self.github_url = QLineEdit()
        self.portfolio_url = QLineEdit()

        self.linkedin_url.setPlaceholderText("https://linkedin.com/in/...")
        self.github_url.setPlaceholderText("https://github.com/...")
        self.portfolio_url.setPlaceholderText("https://...")

        self._add_form_row(grid, 0, "LinkedIn", self.linkedin_url)
        self._add_form_row(grid, 1, "GitHub", self.github_url)
        self._add_form_row(grid, 2, "Portfolio", self.portfolio_url)
        return box

    def _build_education_group(self):
        box = QGroupBox("Education")
        grid = self._new_form_grid(box)

        self.school = QLineEdit()
        self.degree = QLineEdit()
        self.major = QLineEdit()
        self.graduation = QLineEdit()

        self.school.setPlaceholderText("University")
        self.degree.setPlaceholderText("Bachelor")
        self.major.setPlaceholderText("Computer Science")
        self.graduation.setPlaceholderText("May 2027")

        self._add_form_row(grid, 0, "School", self.school)
        self._add_form_row(grid, 1, "Degree", self.degree)
        self._add_form_row(grid, 2, "Major", self.major)
        self._add_form_row(grid, 3, "Graduation", self.graduation)
        return box

    def _build_answers_group(self):
        box = QGroupBox("Default Answers")
        layout = QVBoxLayout(box)

        self.default_answers = QPlainTextEdit()
        self.default_answers.setMinimumHeight(150)
        self.default_answers.setPlaceholderText(
            "Example:\n"
            "Authorized to work: Yes\n"
            "Require sponsorship: No\n"
            "Preferred internship period: Summer 2026"
        )
        layout.addWidget(self.default_answers)
        return box

    def _new_form_grid(self, parent):
        grid = QGridLayout(parent)
        grid.setContentsMargins(18, 22, 18, 18)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnMinimumWidth(0, 86)
        grid.setColumnStretch(1, 1)
        return grid

    def _add_form_row(self, grid, row, label_text, widget):
        label = QLabel(label_text)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setMinimumWidth(84)
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        widget.setMinimumHeight(38)
        widget.setMinimumWidth(240)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        grid.addWidget(label, row, 0)
        grid.addWidget(widget, row, 1)

    def to_profile_dict(self, job_url=None):
        workday_credential = None
        workday_site = ""
        workday_credential_existed = False
        if job_url:
            workday_site = self._workday_site_key(job_url)
            workday_credential_existed = workday_site in self.get_workday_credentials()
            workday_credential = self.ensure_workday_credential(job_url)
        workday_company_slug = self.company_slug_from_workday_url(job_url) if job_url else ""

        return {
            "first_name": self.first_name.text().strip(),
            "last_name": self.last_name.text().strip(),
            "email": self.email.text().strip(),
            "phone": self.phone.text().strip(),
            "address": self.address.text().strip(),
            "resume_path": self.resume_path.text().strip(),
            "linkedin_url": self.linkedin_url.text().strip(),
            "github_url": self.github_url.text().strip(),
            "portfolio_url": self.portfolio_url.text().strip(),
            "school": self.school.text().strip(),
            "degree": self.degree.text().strip(),
            "major": self.major.text().strip(),
            "graduation": self.graduation.text().strip(),
            "default_answers": self.default_answers.toPlainText().strip(),
            "workday_credentials": self.get_workday_credentials(),
            "workday_credential": workday_credential or {},
            "workday_credential_existed": workday_credential_existed,
            "workday_site": workday_site,
            "workday_company_slug": workday_company_slug,
        }

    def ensure_workday_credential(self, job_url):
        site = self._workday_site_key(job_url)
        if not site:
            return None

        credentials = self.get_workday_credentials()
        if site in credentials:
            return credentials[site]

        username = self._build_catchall_username(self.company_slug_from_workday_url(job_url))
        password = self._generate_secure_password()
        self._upsert_credential_row(site, username, password, save=True)
        return {"username": username, "password": password}

    def get_workday_credentials(self):
        credentials = {}
        for row in range(self.credentials_table.rowCount()):
            site = self._workday_site_key(self._item_text(row, 1))
            username = self._item_text(row, 2)
            password = self._item_text(row, 3)
            if site and username and password:
                credentials[site] = {
                    "username": username,
                    "password": password,
                }
        return credentials

    def _upsert_credential_row(self, site, username, password, save=False):
        site = self._workday_site_key(site)
        row = self._find_credential_row(site) if site else -1
        if row < 0:
            row = self.credentials_table.rowCount()
            self.credentials_table.insertRow(row)
        self.credentials_table.setRowHeight(row, 44)

        if not self.credentials_table.item(row, 0):
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox_item.setCheckState(Qt.Unchecked)
            self.credentials_table.setItem(row, 0, checkbox_item)

        for col, value in enumerate([site, username, password], start=1):
            self.credentials_table.setItem(row, col, QTableWidgetItem(value))

        if save:
            self.save_state()

    def _find_credential_row(self, site):
        normalized_site = self._workday_site_key(site)
        for row in range(self.credentials_table.rowCount()):
            if self._workday_site_key(self._item_text(row, 1)) == normalized_site:
                return row
        return -1

    def _item_text(self, row, col):
        item = self.credentials_table.item(row, col)
        return item.text().strip() if item else ""

    def delete_selected_credentials(self):
        rows_to_delete = []
        for row in range(self.credentials_table.rowCount()):
            checkbox = self.credentials_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                rows_to_delete.append(row)

        for row in reversed(rows_to_delete):
            self.credentials_table.removeRow(row)

        if rows_to_delete:
            self.save_state()

    def _build_catchall_username(self, company_slug):
        domain = self.catchall_domain.text().strip().lstrip("@")
        if domain:
            return f"{company_slug}_intern@{domain}"

        email = self.email.text().strip()
        if email:
            return email

        return f"{company_slug}_intern@example.com"

    def _generate_secure_password(self, length=18):
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        required = [
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.digits),
            secrets.choice("!@#$%^&*"),
        ]
        remaining = [secrets.choice(alphabet) for _ in range(length - len(required))]
        chars = required + remaining
        secrets.SystemRandom().shuffle(chars)
        return "".join(chars)

    def _workday_site_key(self, job_url):
        if not job_url:
            return ""

        value = job_url.strip()
        if "://" not in value:
            value = f"https://{value}"

        parsed = urlparse(value)
        host = parsed.netloc.lower()
        if not host:
            host = value.lower().split("/")[0]
        return host.replace("www.", "")

    def company_slug_from_workday_url(self, job_url):
        site = self._workday_site_key(job_url)
        if not site:
            return "workday"
        return site.split(".", 1)[0].replace("-", "_")

    def load_state(self):
        self._loading_state = True
        data = self.store.load()
        profile = data.get("profile", {})

        for key, widget in self._profile_fields().items():
            widget.setText(profile.get(key, ""))

        self.default_answers.setPlainText(profile.get("default_answers", ""))

        credentials = data.get("workday_credentials", {})
        self.credentials_table.setRowCount(0)
        for site, credential in credentials.items():
            self._upsert_credential_row(
                site,
                credential.get("username", ""),
                credential.get("password", ""),
                save=False,
            )
        self._loading_state = False

    def save_state(self):
        if self._loading_state:
            return

        profile = {
            key: widget.text().strip()
            for key, widget in self._profile_fields().items()
        }
        profile["default_answers"] = self.default_answers.toPlainText().strip()

        data = self.store.load()
        data["profile"] = profile
        data["workday_credentials"] = self.get_workday_credentials()
        self.store.save(data)
