"""Structured profile editing, guided answer approval and the approved-answer bank."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QCompleter, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView, QLineEdit, QListWidget,
    QMessageBox, QPlainTextEdit, QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.automation.models import ApplicantProfile, ApprovedAnswer, Education, Experience, Language, employer_key, normalized, site_key
from gui.theme import form_layout, MessageBar, button, card, dot_icon, label, restyle, shortcut

BOOLEAN_FIELDS = {"work_authorized_us", "requires_sponsorship", "hispanic_or_latino"}
ROW_BOOLEANS = {"current", "fluent"}
LONG_FIELDS = {"summary", "cover_letter"}
FILE_FIELDS = {"resume_path": "Choose resume", "cover_letter_path": "Choose cover letter"}
TABLES = {"education": (Education, "Add education"), "experience": (Experience, "Add experience"), "language_proficiency": (Language, "Add language")}
DATE_HINT = "Use dates in the format your target forms expect, such as 2026-05."
SECTIONS = [
    ("Name", "", ["first_name", "last_name", "middle_name", "preferred_name", "preferred_middle_name", "preferred_last_name", "name_prefix", "name_suffix", "pronouns"]),
    ("Contact", "Where employers should reach you.", ["email", "phone", "phone_country_code", "phone_number", "phone_device_type", "address_line1", "address_line2", "city", "region", "postal_code", "country"]),
    ("Documents", "Uploaded with their original bytes and file type.", ["resume_path", "cover_letter_path", "cover_letter"]),
    ("Links", "", ["linkedin_url", "github_url", "portfolio_url"]),
    ("Work eligibility", "Leave a question as Unknown to be asked for each application.", ["work_authorized_us", "requires_sponsorship", "employment_age"]),
    ("About you", "", ["summary", "skills", "languages"]),
    ("Education", DATE_HINT, "education"),
    ("Experience", DATE_HINT, "experience"),
    ("Language proficiency", "", "language_proficiency"),
    ("Voluntary self-identification", "Optional. Used only when a form asks. Leave blank or Unknown to decide each time.", ["gender", "race_ethnicity", "hispanic_or_latino", "veteran_status", "disability_status"]),
]
LABELS = {
    "first_name": ("First name", ""), "last_name": ("Last name", ""), "middle_name": ("Middle name", ""),
    "preferred_name": ("Preferred first name", ""), "preferred_middle_name": ("Preferred middle name", ""),
    "preferred_last_name": ("Preferred last name", ""), "name_prefix": ("Prefix", "Mr., Ms., Dr."),
    "name_suffix": ("Suffix", "Jr., III"), "pronouns": ("Pronouns", "she/her, they/them"),
    "email": ("Email", "you@example.com"), "phone": ("Phone", "+1 555 010 0000"),
    "phone_country_code": ("Phone country code", "+1"), "phone_number": ("Phone number", "Without the country code"),
    "phone_device_type": ("Phone type", "Mobile"), "address_line1": ("Address line 1", ""), "address_line2": ("Address line 2", ""),
    "city": ("City", ""), "region": ("State or province", ""), "postal_code": ("Postal code", ""), "country": ("Country", ""),
    "resume_path": ("Resume", "PDF, Word, RTF or text file"), "cover_letter_path": ("Cover letter file", "Optional"),
    "cover_letter": ("Cover letter text", "Used where a form asks for text instead of a file"),
    "linkedin_url": ("LinkedIn", "https://www.linkedin.com/in/…"), "github_url": ("GitHub", "https://github.com/…"),
    "portfolio_url": ("Portfolio or website", "https://…"),
    "work_authorized_us": ("Authorized to work in the US", ""), "requires_sponsorship": ("Will require visa sponsorship", ""),
    "employment_age": ("Age", "Only if a form requires it"),
    "summary": ("Summary", ""), "skills": ("Skills", "Python, SQL, Figma"), "languages": ("Languages spoken", "English, Spanish"),
    "gender": ("Gender", ""), "race_ethnicity": ("Race or ethnicity", ""), "hispanic_or_latino": ("Hispanic or Latino", ""),
    "veteran_status": ("Veteran status", ""), "disability_status": ("Disability status", ""),
}
COLUMNS = {"job_title": "Job title", "start_date": "Start", "end_date": "End", "gpa": "GPA"}
RESULTS = {"verified": ("Verified", "success"), "needs_input": ("Needs input", "warning"),
           "blocked": ("Blocked", "danger"), "intentionally_omitted": ("Left blank", "neutral")}


def bool_combo(value=None):
    combo = QComboBox()
    for text, choice in (("Unknown", None), ("Yes", True), ("No", False)):
        combo.addItem(text, choice)
    combo.setCurrentIndex(0 if value is None else 1 if value else 2)
    return combo


def table(headers, row_height=34):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.verticalHeader().setVisible(False)
    widget.verticalHeader().setDefaultSectionSize(row_height)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    widget.horizontalHeader().setHighlightSections(False)
    widget.setShowGrid(False)
    widget.setSelectionBehavior(QTableWidget.SelectRows)
    widget.setSelectionMode(QTableWidget.SingleSelection)
    return widget


class ProfileEditor(QWidget):
    changed = Signal()

    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.inputs, self.tables = {}, {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self.nav = QListWidget()
        self.nav.setObjectName("sectionNav")
        self.nav.setFixedWidth(210)
        self.nav.setAccessibleName("Profile sections")
        self.pages = QStackedWidget()
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        layout.addWidget(self.nav)
        layout.addWidget(self.pages, 1)
        covered = {key for _, _, keys in SECTIONS if isinstance(keys, list) for key in keys}
        # A field added to the model later still gets an editor instead of silently disappearing.
        other = [k for k in ApplicantProfile.model_fields if k not in covered and k not in TABLES and k != "schema_version"]
        for title, hint, keys in SECTIONS + ([("Other", "", other)] if other else []):
            frame, box = card()
            box.addWidget(label(title, "section"))
            if hint:
                box.addWidget(label(hint, "muted"))
            if isinstance(keys, str):
                box.addLayout(self._table_section(keys, getattr(profile, keys)), 1)
                self.add_section(title, frame, scroll=False)
                continue
            form = form_layout(10)
            for key in keys:
                text, placeholder = LABELS.get(key, (key.replace("_", " ").capitalize(), ""))
                form.addRow(text, self._field(key, getattr(profile, key), placeholder))
            box.addLayout(form)
            box.addStretch()
            self.add_section(title, frame)
        self.nav.setCurrentRow(0)

    def _field(self, name, value, placeholder):
        if name in BOOLEAN_FIELDS:
            widget = bool_combo(value)
            widget.currentIndexChanged.connect(self.changed)
        elif name in LONG_FIELDS:
            widget = QPlainTextEdit(value or "")
            widget.setFixedHeight(110)
            widget.setPlaceholderText(placeholder)
            widget.textChanged.connect(self.changed)
        else:
            widget = QLineEdit("" if value is None else str(value))
            widget.setPlaceholderText(placeholder)
            widget.textChanged.connect(self.changed)
        self.inputs[name] = widget
        if name not in FILE_FIELDS:
            return widget
        row = QHBoxLayout()
        row.addWidget(widget, 1)
        row.addWidget(button("Choose…", lambda checked=False, key=name: self.pick_resume(key), tip=FILE_FIELDS[name]))
        return row

    def _table_section(self, group, entries):
        model, add_text = TABLES[group]
        keys = list(model.model_fields)
        widget = table([COLUMNS.get(k, k.replace("_", " ").capitalize()) for k in keys])
        widget.itemChanged.connect(self.changed)
        self.tables[group] = (widget, keys)
        for entry in entries:
            self.add_row(widget, keys, entry.model_dump())
        box = QVBoxLayout()
        box.addWidget(widget, 1)
        actions = QHBoxLayout()
        actions.addWidget(button(add_text, lambda: self.add_row(widget, keys, {})))
        actions.addWidget(button("Remove selected", lambda: self.remove_row(widget), "danger"))
        actions.addStretch()
        box.addLayout(actions)
        return box

    def add_section(self, title, widget, scroll=True):
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            content = QWidget()
            content.setObjectName("scrollContent")
            QVBoxLayout(content).addWidget(widget)
            content.layout().setContentsMargins(0, 0, 0, 0)
            area.setWidget(content)
            widget = area
        self.pages.addWidget(widget)
        self.nav.addItem(title)

    def show_section(self, title):
        matches = self.nav.findItems(title, Qt.MatchExactly)
        if matches:
            self.nav.setCurrentItem(matches[0])

    def pick_resume(self, key="resume_path"):
        path, _ = QFileDialog.getOpenFileName(self, FILE_FIELDS[key], "", "Documents (*.pdf *.doc *.docx *.txt *.rtf)")
        if path:
            self.inputs[key].setText(path)

    def add_row(self, table, keys, values):
        row = table.rowCount()
        table.insertRow(row)
        for col, key in enumerate(keys):
            value = values.get(key)
            if key in ROW_BOOLEANS:
                combo = bool_combo(value)
                combo.currentIndexChanged.connect(self.changed)
                table.setCellWidget(row, col, combo)
            else:
                table.setItem(row, col, QTableWidgetItem("" if value is None else str(value)))
        self.changed.emit()

    def remove_row(self, table):
        if table.currentRow() >= 0:
            table.removeRow(table.currentRow())
            self.changed.emit()

    def profile(self):
        data = {k: w.currentData() if isinstance(w, QComboBox) else (w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text()).strip()
                for k, w in self.inputs.items()}
        if not data["employment_age"]:
            data["employment_age"] = None
        for group, (table, keys) in self.tables.items():
            rows = []
            for row in range(table.rowCount()):
                entry = {key: table.cellWidget(row, col).currentData() if key in ROW_BOOLEANS
                         else (table.item(row, col).text().strip() if table.item(row, col) else "") for col, key in enumerate(keys)}
                if any(entry.values()):
                    rows.append(entry)
            data[group] = rows
        return ApplicantProfile.model_validate(data)

    def load_profile(self, profile):
        for name, widget in self.inputs.items():
            value = getattr(profile, name)
            if isinstance(widget, QPlainTextEdit):
                widget.setPlainText(value)
            elif isinstance(widget, QComboBox):
                widget.setCurrentIndex(0 if value is None else 1 if value else 2)
            else:
                widget.setText("" if value is None else str(value))
        for group, (table, keys) in self.tables.items():
            table.setRowCount(0)
            for entry in getattr(profile, group):
                self.add_row(table, keys, entry.model_dump())


class ProfileDialog(QDialog):
    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Application profile snapshot")
        self.resize(940, 680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label("Application profile snapshot", "section"))
        layout.addWidget(label("Changes apply only to this application. Your saved profile stays as it is.", "muted"))
        self.editor = ProfileEditor(profile, self)
        layout.addWidget(self.editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        restyle(buttons.button(QDialogButtonBox.Save), variant="primary")
        buttons.accepted.connect(self.validate_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def profile(self):
        return self.editor.profile()

    def validate_accept(self):
        try:
            self.profile()
        except ValueError:
            QMessageBox.warning(self, "Check profile", "Age must be a whole number or blank.")
            return
        self.accept()


class RunDetailsDialog(QDialog):
    """Answer the questions an application is blocked on, one after another, then resume it."""

    def __init__(self, store, run, parent=None):
        super().__init__(parent)
        self.store, self.run = store, run
        name = run.company or site_key(run.job_url)
        self.setWindowTitle(f"Answer questions — {name}")
        self.resize(800, 740)
        self.pending = list(dict.fromkeys(i.question for i in run.interventions if i.question))
        self.answered = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label(f"{name} · {run.role}", "section"))
        self.progress = label(role="muted")
        layout.addWidget(self.progress)

        frame, box = card(10)
        self.form = form_layout(10)
        self.questions = QComboBox()
        self.questions.setEditable(True)
        self.questions.addItems(self.pending)
        self.questions.setToolTip("Use the form's exact wording. Approvals match the normalized question text.")
        self.form.addRow("Question", self.questions)
        self.kind = QComboBox()
        self.kind.addItems(["Text answer", "Yes", "No", "Leave blank (optional questions only)"])
        self.form.addRow("Answer type", self.kind)
        # Type to filter long lists; only picking an actual option fills the answer.
        self.choices = QComboBox()
        self.choices.setEditable(True)
        self.choices.setInsertPolicy(QComboBox.NoInsert)
        self.choices.lineEdit().setPlaceholderText("Type to filter the form's options")
        self.choices.completer().setFilterMode(Qt.MatchContains)
        self.choices.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.choices.activated.connect(lambda: self.answer.setPlainText(self.choices.currentText()))
        self.form.addRow("Form choices", self.choices)
        self.answer = QPlainTextEdit()
        self.answer.setFixedHeight(90)
        self.answer.setPlaceholderText("The exact answer to fill in")
        self.answer_box = QVBoxLayout()
        self.answer_box.setSpacing(4)
        self.answer_box.addWidget(self.answer)
        self.answer_box.addWidget(button("Draft with AI…", self.draft_answer, "ghost"), 0, Qt.AlignLeft)
        self.form.addRow("Answer", self.answer_box)
        self.scope = QComboBox()
        self.scope.addItems(["Only this application", f"All applications to {name}", "Any application asking exactly this question"])
        self.form.addRow("Remember for", self.scope)
        box.addLayout(self.form)
        save_row = QHBoxLayout()
        save_row.addStretch()
        save_row.addWidget(button("Save approved answer", self.save_answer, "primary"))
        box.addLayout(save_row)
        layout.addWidget(frame)
        self.notice = MessageBar()
        layout.addWidget(self.notice)

        tabs = QTabWidget()
        fields = QTreeWidget()
        fields.setHeaderLabels(["Field", "Result", "Detail"])
        fields.setColumnWidth(0, 240)
        fields.setColumnWidth(1, 120)
        sections = {}
        for assessment in run.fields.values():
            section = assessment.section or "Form"
            if section not in sections:
                sections[section] = QTreeWidgetItem(fields, [section])
            text, tone = RESULTS[assessment.disposition]
            detail = assessment.reason or assessment.evidence
            item = QTreeWidgetItem(sections[section], [assessment.label, text, detail])
            item.setIcon(1, dot_icon(tone))
            item.setToolTip(2, detail)
        fields.expandAll()
        tabs.addTab(fields, f"Fields ({len(run.fields)})")
        history = QTreeWidget()
        history.setHeaderLabels(["When", "Event", "Note"])
        history.setRootIsDecorated(False)
        history.setColumnWidth(0, 140)
        history.setColumnWidth(1, 170)
        for event in store.events(run.id)[-20:]:
            QTreeWidgetItem(history, [event["at"][:16].replace("T", " "), event["kind"].replace("_", " "), event["note"]]).setToolTip(2, event["note"])
        tabs.addTab(history, "History")
        layout.addWidget(tabs, 1)
        layout.addWidget(label(f"Profile {run.profile_name} · Automatic submit {'authorized' if run.auto_submit else 'off'} · "
                               f"{run.elapsed_seconds:.0f} s active · {run.intervention_count} interventions · {run.ai_requests} AI requests", "caption"))

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.resume_btn = buttons.addButton("Resume application", QDialogButtonBox.AcceptRole)
        restyle(self.resume_btn, variant="primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.questions.currentTextChanged.connect(self.question_changed)
        self.kind.currentIndexChanged.connect(self.kind_changed)
        self.question_changed()
        self.update_progress()

    def request(self):
        question = normalized(self.questions.currentText())
        return next((i for i in self.run.interventions if i.question and normalized(i.question) == question), None)

    def question_changed(self):
        request = self.request()
        self.choices.clear()
        self.choices.addItems(request.options if request else [])
        self.choices.setCurrentIndex(-1)
        required = bool(request and request.required)
        # Required questions can't be omitted, so the option is unavailable rather than an error after saving.
        self.kind.model().item(3).setEnabled(not required)
        if required and self.kind.currentIndex() == 3:
            self.kind.setCurrentIndex(0)
        self.kind_changed()

    def kind_changed(self):
        text = self.kind.currentIndex() == 0
        self.form.setRowVisible(self.answer_box, text)
        self.form.setRowVisible(self.choices, text and self.choices.count() > 0)

    def update_progress(self):
        done = sum(normalized(q) in self.answered for q in self.pending)
        self.progress.setText(f"{done} of {len(self.pending)} questions answered" if self.pending
                              else "No open questions. You can still approve an answer to a question you expect.")
        required_left = any(i.required and i.question and normalized(i.question) not in self.answered for i in self.run.interventions)
        self.resume_btn.setVisible(bool(self.answered) and not required_left)

    def draft_answer(self):
        from gui.views.assistant_dialog import AssistantDialog
        question = self.questions.currentText().strip()
        if not question:
            self.notice.notify("Choose or enter the exact question first.", "warning")
            return
        dialog = AssistantDialog(self.store, self.run, question, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.answer.setPlainText(dialog.output.toPlainText())
            self.kind.setCurrentIndex(0)
            self.notice.notify("Draft inserted. Review it, then save it as your approved answer.", "warning")

    def save_answer(self):
        question = self.questions.currentText().strip()
        if not question:
            self.notice.notify("Enter the exact question first.", "warning")
            return
        omit = self.kind.currentIndex() == 3
        if omit and any(i.required and i.question == question for i in self.run.interventions):
            self.notice.notify("Required questions can't be left blank.", "warning")
            return
        value = self.answer.toPlainText().strip() if self.kind.currentIndex() == 0 else self.kind.currentIndex() == 1
        if not omit and value == "":
            self.notice.notify("Enter an answer, or choose Yes, No or Leave blank.", "warning")
            return
        scope = ["application", "employer", "global"][self.scope.currentIndex()]
        key = self.run.id if scope == "application" else employer_key(self.run.job_url) if scope == "employer" else ""
        country = self.run.profile_snapshot.country if self.run.profile_snapshot else ""
        answer = ApprovedAnswer(question=question, profile_name=self.run.profile_name, value=value, scope=scope, scope_key=key, country=country, omit=omit)
        # Editing the same scoped answer replaces it instead of creating a conflict.
        existing = [a for a in self.store.answers() if normalized(a.question) == normalized(question) and a.profile_name == self.run.profile_name and a.scope == scope and a.scope_key == key and a.country == country]
        if existing:
            answer.id = existing[-1].id
        self.store.save_answer(answer)
        self.answered.add(normalized(question))
        self.update_progress()
        remaining = [q for q in self.pending if normalized(q) not in self.answered]
        if remaining:
            self.questions.setCurrentText(remaining[0])
            self.answer.clear()
            self.kind.setCurrentIndex(0)
            self.notice.notify(f"Answer saved. Next: {remaining[0]}", "success")
        else:
            self.notice.notify("Answer saved. Resume the application when you're ready.", "success")


class AnswersView(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.answers = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("Answers", "pageTitle"))
        titles.addWidget(label("Answers you've approved. They're reused only for the exact question, within their scope, profile and country.", "muted"))
        header.addLayout(titles, 1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search questions and answers")
        self.search.setAccessibleName("Search answers")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self.refresh)
        header.addWidget(self.search)
        layout.addLayout(header)
        self.notice = MessageBar()
        layout.addWidget(self.notice)
        self.table = table(["Question", "Answer", "Applies to", "Profile", "Country"], 36)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setWordWrap(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.Interactive)
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 160), (2, 240), (3, 110), (4, 100)):
            self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self.update_actions)
        layout.addWidget(self.table, 1)
        self.empty = label("Answers you approve while resolving an application's questions appear here.", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty, 1)
        row = QHBoxLayout()
        row.addStretch()
        self.remove_btn = button("Delete answer…", self.remove, "danger")
        row.addWidget(self.remove_btn)
        layout.addLayout(row)
        for keys in ("Delete", "Backspace"):
            shortcut(keys, self.table, self.remove, Qt.WidgetShortcut)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        self.answers = self.store.answers()
        companies = {run.id: run.company or site_key(run.job_url) for run in self.store.runs()}
        query = self.search.text().strip().casefold()
        rows = [a for a in self.answers if query in f"{a.question} {a.value}".casefold()]
        self.table.setRowCount(len(rows))
        for row, answer in enumerate(rows):
            applies = {"application": f"Only the {companies.get(answer.scope_key, 'deleted')} application",
                       "employer": f"All applications at {answer.scope_key}", "global": "Any application"}[answer.scope]
            value = "Leave blank" if answer.omit else {True: "Yes", False: "No"}.get(answer.value, str(answer.value))
            for col, text in enumerate([answer.question, value, applies, answer.profile_name, answer.country or "—"]):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                item.setData(Qt.UserRole, answer.id)
                self.table.setItem(row, col, item)
        self.table.setVisible(bool(self.answers))
        self.empty.setVisible(not self.answers)
        self.update_actions()

    def update_actions(self):
        self.remove_btn.setEnabled(bool(self.table.selectedItems()))

    def remove(self):
        items = self.table.selectedItems()
        if not items:
            return
        answer = next(a for a in self.answers if a.id == items[0].data(Qt.UserRole))
        if QMessageBox.question(self, "Delete approved answer?", f"Delete your answer to “{answer.question}”? Intern-Bot will ask again the next time this question appears.") != QMessageBox.Yes:
            return
        self.store.delete_answer(answer.id)
        self.refresh()
        self.notice.notify("Answer deleted.", "success")
