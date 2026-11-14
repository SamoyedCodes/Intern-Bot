"""Structured profile editing, guided answer approval, the review you approve before sending, and the approved-answer bank."""
import re
from difflib import SequenceMatcher

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QScrollArea, QSizePolicy, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from core.automation.answers import UNANSWERED, applicable, asks, fact_name
from core.automation.models import ApplicantProfile, ApprovedAnswer, Education, Experience, Language, ats_name, employer_key, normalized, site_key
from core.automation.recipes import save_recipe
from core.automation.review import shown_value
from gui.theme import form_layout, MessageBar, ReadableTree, button, card, dot_icon, label, restyle, shortcut, station_heading

BOOLEAN_FIELDS = {"work_authorized", "requires_sponsorship", "hispanic_or_latino"}
ROW_BOOLEANS = {"current", "fluent"}
LONG_FIELDS = {"summary", "cover_letter", "standing_answers"}
FILE_FIELDS = {"resume_path": "Choose resume", "cover_letter_path": "Choose cover letter"}
TABLES = {"education": (Education, "Add education"), "experience": (Experience, "Add experience"), "language_proficiency": (Language, "Add language")}
DATE_HINT = "Use dates in the format your target forms expect, such as 2026-05."
SECTIONS = [
    ("Name", "", ["first_name", "last_name", "middle_name", "preferred_name", "preferred_middle_name", "preferred_last_name", "name_prefix", "name_suffix", "pronouns"]),
    ("Contact", "Where employers should reach you.", ["email", "phone", "phone_country_code", "phone_number", "phone_device_type", "address_line1", "address_line2", "city", "region", "postal_code", "country"]),
    ("Documents", "Uploaded with their original bytes and file type.", ["resume_path", "cover_letter_path", "cover_letter"]),
    ("Links", "", ["linkedin_url", "github_url", "portfolio_url"]),
    ("Citizenship & eligibility", "For Singapore jobs, work authorization defaults to Yes. Leave a field blank or Unknown to answer for each application.", ["work_authorized", "requires_sponsorship", "citizenship", "nationality", "employment_age"]),
    ("Standing answers", "Statements that are true for every application. The AI provider you set up reads them to answer declarations such as relatives at the employer, criminal record or citizenship. Its answers stay unconfirmed until you review them.", ["standing_answers"]),
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
    "work_authorized": ("Authorized to work in job's country", ""), "requires_sponsorship": ("Will require visa sponsorship", ""),
    "citizenship": ("Citizenship (country)", "e.g. Singapore"), "nationality": ("Nationality", "e.g. Singaporean"),
    "employment_age": ("Age", "Only if a form requires it"),
    "standing_answers": ("Statements", "I am a Singapore citizen (pink IC).\nI am not related to any employee, director or shareholder of any employer I apply to."),
    "summary": ("Summary", ""), "skills": ("Skills", "Python, SQL, Figma"), "languages": ("Languages spoken", "English, Spanish"),
    "gender": ("Gender", ""), "race_ethnicity": ("Race or ethnicity", ""), "hispanic_or_latino": ("Hispanic or Latino", ""),
    "veteran_status": ("Veteran status", ""), "disability_status": ("Disability status", ""),
}
COLUMNS = {"job_title": "Job title", "start_date": "Start", "end_date": "End", "gpa": "GPA"}
# Declarations are accepted per application and wording; stable facts are worth reusing everywhere. Anything else defaults to this application.
DECLARATION = re.compile(r"\b(agree|consent|acknowledg|certif|declar|attest|confirm|understand|privacy|terms)", re.I)
STABLE_FACT = re.compile(r"authori[sz]ed to work|sponsor|visa|citizen|nationality|degree|graduat|\bgpa\b|universit|school|major|field of study|gender|race|ethnic|veteran|disabilit|hispanic|pronoun|linkedin|github|portfolio|website|language|phone|address|country|city|postal|zip|legal name|18 years|hear about|year of study|notice period", re.I)
RESULTS = {"verified": ("Verified", "success"), "needs_input": ("Needs input", "warning"),
           "blocked": ("Blocked", "danger"), "intentionally_omitted": ("Left blank", "neutral")}


def shown(answer):
    text = ("Leave blank" if answer.omit else f"Profile: {fact_name(answer.fact)}" if answer.fact
            else {True: "Yes", False: "No"}.get(answer.value, str(answer.value)))
    return f"AI · unconfirmed · {text}" if answer.origin == "ai" else text


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
        self._profile = profile
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
        other = [k for k in ApplicantProfile.model_fields if k not in covered and k not in TABLES and k not in {"schema_version", "work_authorized_us"}]
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
        # Preserve legacy country-specific facts without reusing them for Singapore jobs.
        return ApplicantProfile.model_validate({**self._profile.model_dump(), **data})

    def load_profile(self, profile):
        self._profile = profile
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
        layout.addWidget(station_heading("Application profile snapshot", "fill", compact=True))
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


SCOPES = (("application", "This application", "Used for this application only."),
          ("employer", "This employer", "Reused for every application to {employer}."),
          ("global", "Every application", "Reused whenever a form asks this question."))
OMIT = "__omit__"


class QuestionCard(QFrame):
    """One open question: the employer's wording, an answer in the form's own control type, and how widely it is remembered."""
    changed = Signal()

    def __init__(self, question, request, members=(), known=(), employer="", draft=None, editable=False, value="", reuse=True):
        """value: what the card starts from (the form's own value, or the saved answer it didn't take); for a checklist, its ticked members."""
        super().__init__()
        self.setObjectName("card")
        self.question, self.request, self.members, self.reuse = question, request, list(members), reuse
        self.required = bool(request and request.required)
        conflict = bool(request and request.kind == "conflict")
        control = request.field_kind if request else ""
        options = list(request.options) if request else []
        self.declaration = bool(DECLARATION.search(question))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(8)
        self.wording = None
        if editable:
            # No open question: approve an answer for one you expect, in the form's exact wording.
            self.wording = QLineEdit()
            self.wording.setPlaceholderText("The form's exact question")
            self.wording.textChanged.connect(lambda *_: self.changed.emit())
            layout.addWidget(self.wording)
        else:
            title = label(question, "question")
            title.setTextFormat(Qt.PlainText)
            title.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(title)
        notes = ["Required" if self.required else "Optional"] if request else []
        if request and request.message and request.message != UNANSWERED:
            notes.append(request.message)
        if conflict and value not in ("", False):
            notes.append("Shown below: what the form holds now. Saving keeps it")
        if self.declaration:
            notes.append("Declaration: saved for this application and this exact wording only")
        if notes:
            layout.addWidget(label(" · ".join(notes), "caption"))

        self.text = self.choice = self.file = self.checklist = self.blank = None
        if self.members:
            self.checklist = QListWidget()
            for member in self.members:
                item = QListWidgetItem(member.rsplit(" — ", 1)[1])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if member in (value or ()) else Qt.Unchecked)
                item.setData(Qt.UserRole, member)
                self.checklist.addItem(item)
            self.checklist.setFixedHeight(self.checklist.sizeHintForRow(0) * self.checklist.count() + 2 * self.checklist.frameWidth())
            self.checklist.itemChanged.connect(lambda *_: self.changed.emit())
            layout.addWidget(self.checklist)
        elif control == "file":
            self.file = QLineEdit()
            self.file.setReadOnly(True)
            self.file.setPlaceholderText("The document to upload")
            self.file.setText(str(value or ""))
            self.file.textChanged.connect(lambda *_: self.changed.emit())
            row = QHBoxLayout()
            row.addWidget(self.file, 1)
            row.addWidget(button("Choose…", self.pick_file, "ghost"))
            layout.addLayout(row)
        elif options or control == "checkbox":
            self.choice = QComboBox()
            if options:
                # Type to filter long lists; only an actual option is accepted.
                self.choice.setEditable(True)
                self.choice.setInsertPolicy(QComboBox.NoInsert)
                self.choice.lineEdit().setPlaceholderText("Choose one of the form's options")
                self.choice.completer().setFilterMode(Qt.MatchContains)
                self.choice.completer().setCompletionMode(QCompleter.PopupCompletion)
                for option in options:
                    self.choice.addItem(option, option)
            else:
                self.choice.addItem("Choose…", None)
                self.choice.addItem("Yes", True)
                self.choice.addItem("No", False)
            if not self.required:
                self.choice.addItem("Leave blank", OMIT)
            held = {True: "yes", False: "no"}.get(value, normalized(str(value)))
            start = next((i for i in range(self.choice.count()) if value != "" and normalized(self.choice.itemText(i)) == held), None)
            self.choice.setCurrentIndex(start if start is not None else -1 if options else 0)
            self.choice.currentTextChanged.connect(lambda *_: self.changed.emit())
            layout.addWidget(self.choice)
        else:
            self.text = QPlainTextEdit()
            self.text.setFixedHeight(64)
            self.text.setPlaceholderText("The exact answer to fill in")
            self.text.setPlainText({True: "Yes", False: "No"}.get(value, str(value)))
            self.text.textChanged.connect(lambda *_: self.changed.emit())
            layout.addWidget(self.text)
            if draft:
                layout.addWidget(button("Draft with AI…", lambda: draft(self), "ghost"), 0, Qt.AlignLeft)
        if not self.required and request and (self.text or self.file):
            self.blank = QCheckBox("Leave blank")
            self.blank.toggled.connect(lambda *_: self.changed.emit())
            layout.addWidget(self.blank)

        # A reworded question can reuse an answer you already gave; only close matches are offered.
        wording = normalized(question)
        close = sorted(((SequenceMatcher(None, wording, normalized(a.question)).ratio(), a) for a in known if not asks(a, question)),
                       key=lambda pair: -pair[0])
        close = [a for ratio, a in close if ratio >= .55][:8]
        self.same = None
        if close and not self.members and not editable:
            self.same = QComboBox()
            self.same.setToolTip("This wording is added to the chosen answer.")
            self.same.addItem("Not the same as a saved answer", "")
            for answer in close:
                self.same.addItem(f"Same as “{answer.question}” → {shown(answer)}", answer.id)
            self.same.currentIndexChanged.connect(lambda *_: self.changed.emit())
            layout.addWidget(self.same)

        # Reuse what stays true (eligibility, education, links); keep one job's specifics, and every declaration, to this job.
        self.scopes = QButtonGroup(self)
        self.scope_row = QWidget()
        row = QHBoxLayout(self.scope_row)
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(8)
        row.addWidget(label("Remember for", "caption", wrap=False))
        segments = QFrame()
        segments.setObjectName("segments")
        segments.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        segment_row = QHBoxLayout(segments)
        segment_row.setContentsMargins(3, 3, 3, 3)
        segment_row.setSpacing(2)
        for index, (_, text, tip) in enumerate(SCOPES):
            choice = button(text, variant="segment", tip=tip.format(employer=employer))
            choice.setCheckable(True)
            self.scopes.addButton(choice, index)
            segment_row.addWidget(choice)
        row.addWidget(segments)
        row.addStretch()
        # A question asked again because this form wouldn't take (or already holds something other than) your saved answer
        # wants this form's own wording, so the correction starts with this application and leaves the saved answer for other forms.
        revision = bool(request and request.message not in ("", UNANSWERED) and value not in ("", False, []))
        self.scopes.button(0 if self.declaration or revision or not STABLE_FACT.search(question) else 2).setChecked(True)
        # With answer reuse off, only this application's own answers are used; any wider scope would be saved and then ignored.
        self.scope_row.setVisible(not self.declaration and reuse)
        layout.addWidget(self.scope_row)
        self.changed.connect(self.sync)
        self.sync()

    def sync(self):
        reused = bool(self.same and self.same.currentData())
        for widget in (self.text, self.choice, self.file, self.checklist):
            if widget:
                widget.setEnabled(not reused and not (self.blank and self.blank.isChecked()))
        if self.blank:
            self.blank.setEnabled(not reused)
        self.scope_row.setEnabled(not reused)

    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose file", "", "Documents (*.pdf *.doc *.docx *.txt *.rtf)")
        if path:
            self.file.setText(path)

    def scope(self):
        return "application" if self.declaration or not self.reuse else SCOPES[max(self.scopes.checkedId(), 0)][0]

    def answer(self):
        """("same", id), ("checklist", {question: ticked}), ("value", value, omit), ("invalid", reason), or None while unanswered."""
        if self.same and self.same.currentData():
            return ("same", self.same.currentData())
        if self.blank and self.blank.isChecked():
            return ("value", "", True)
        if self.checklist:
            ticks = {self.checklist.item(r).data(Qt.UserRole): self.checklist.item(r).checkState() == Qt.Checked for r in range(self.checklist.count())}
            return ("checklist", ticks) if any(ticks.values()) else None
        if self.choice:
            text = self.choice.currentText().strip()
            index = self.choice.findText(text)
            data = self.choice.itemData(index) if index >= 0 else None
            if not text or data is None:
                return ("invalid", "Pick one of the form's options.") if text and index < 0 else None
            return ("value", "", True) if data == OMIT else ("value", data, False)
        value = (self.file.text() if self.file else self.text.toPlainText()).strip()
        return ("value", value, False) if value else None


class RunDetailsDialog(QDialog):
    """Every question an application is blocked on, in one scrolling form; saving them resumes it."""

    def __init__(self, store, run, parent=None):
        super().__init__(parent)
        self.store, self.run = store, run
        name = run.company or site_key(run.job_url)
        self.setWindowTitle(f"Answer questions — {name}")
        self.resize(820, 760)
        # A form's tick-all-that-apply list arrives as one checkbox per option ("Question — Option"); ask it as one checklist.
        prefix = lambda q: q.rsplit(" — ", 1)[0]
        boxes = [i.question for i in run.interventions if i.field_kind == "checkbox" and " — " in i.question]
        self.groups = {}
        for q in dict.fromkeys(boxes):
            self.groups.setdefault(prefix(q), []).append(q)
        self.groups = {k: v for k, v in self.groups.items() if len(v) > 1}
        self.pending = list(dict.fromkeys(prefix(q) if " — " in q and prefix(q) in self.groups else q
                                          for i in run.interventions if (q := i.question)))
        self.answered = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(station_heading("Application questions", "verify", f"{name} · {run.role}", compact=True))
        self.progress = label(role="muted")
        layout.addWidget(self.progress)
        layout.addWidget(label("Answer everything here, then save once. “Remember for” sets how widely each answer is reused: "
                               "stable facts start at every application, this job's specifics at this application. "
                               "Optional questions you leave empty are left blank on the form.", "caption"))

        known = applicable(store.answers(), run.profile_snapshot or ApplicantProfile(), run)
        cards = QWidget()
        column = QVBoxLayout(cards)
        column.setContentsMargins(0, 0, 6, 0)
        column.setSpacing(12)
        self.cards = []
        for question in self.pending or [""]:
            members = self.groups.get(question, [])
            card = QuestionCard(question, self.request(members[0] if members else question), members, known, name,
                                self.draft_answer, editable=not self.pending, reuse=run.reuse_answers,
                                value=[m for m in members if self.held(m) is True] if members else self.held(question))
            card.changed.connect(self.update_progress)
            column.addWidget(card)
            self.cards.append(card)
        column.addStretch()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(cards)
        layout.addWidget(self.scroll, 1)
        self.notice = MessageBar()
        layout.addWidget(self.notice)

        self.report_toggle = QToolButton()
        self.report_toggle.setText(f"Field report ({len(run.fields)}) and history")
        self.report_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.report_toggle.setArrowType(Qt.RightArrow)
        self.report_toggle.setCheckable(True)
        layout.addWidget(self.report_toggle, 0, Qt.AlignLeft)
        tabs = self.report_tabs = QTabWidget()
        tabs.hide()
        self.report_toggle.toggled.connect(tabs.setVisible)
        self.report_toggle.toggled.connect(lambda expanded: self.report_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow))
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
        layout.addWidget(label(f"Profile {run.profile_name} · "
                               f"{run.elapsed_seconds:.0f} s active · {run.intervention_count} interventions · {run.ai_requests} AI requests", "caption"))

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.save_btn = buttons.addButton("Save answers", QDialogButtonBox.ActionRole)
        restyle(self.save_btn, variant="primary")
        self.save_btn.clicked.connect(self.save_answers)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # Saved answers can be paragraphs; size the lists by a short width, not their longest item, or the dialog outgrows the screen.
        for combo in self.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(30)
        self.update_progress()

    def request(self, question):
        question = normalized(question)
        asked = [i for i in self.run.interventions if i.question and normalized(i.question) == question]
        # A radio group asks once per button; the one the form holds against your answer describes the question.
        return next((i for i in asked if i.kind == "conflict"), asked[0] if asked else None)

    def held(self, question):
        """What the form holds for this question, else the saved answer it didn't take; a radio group reports it on any of its buttons."""
        question = normalized(question)
        return next((i.value for i in self.run.interventions if i.question and normalized(i.question) == question and i.value not in ("", False)), "")

    def unanswered_required(self):
        return [c for c in self.cards if c.required and c.answer() is None]

    def update_progress(self):
        if not self.pending:
            self.progress.setText("No open questions. You can still approve an answer to a question you expect.")
            return
        done = sum(c.answer() is not None for c in self.cards)
        left = len(self.unanswered_required())
        self.progress.setText(f"{done} of {len(self.cards)} questions answered" + (f" · {left} required still open" if left else ""))
        self.save_btn.setText("Save answers" if left else "Save answers && continue")

    def draft_answer(self, card):
        from gui.views.assistant_dialog import AssistantDialog
        dialog = AssistantDialog(self.store, self.run, card.question, parent=self)
        if dialog.exec() == QDialog.Accepted:
            card.text.setPlainText(dialog.output.toPlainText())
            self.notice.notify("Draft inserted. Review it before saving it as your approved answer.", "warning")

    def save_answers(self):
        """Save every answered question; continue the application once no required question is left open."""
        for card in self.cards:
            if (answer := card.answer()) and answer[0] == "invalid":
                self.scroll.ensureWidgetVisible(card)
                self.notice.notify(f"{answer[1]} ({card.question})", "warning")
                return
        saved = 0
        for card in self.cards:
            answer = card.answer()
            question = card.wording.text().strip() if card.wording else card.question
            if answer is None or not question:
                continue
            if answer[0] == "same":
                existing = next(a for a in self.store.answers() if a.id == answer[1])
                existing.variants.append(question)
                self.store.save_answer(existing)
            elif answer[0] == "checklist":
                for member, ticked in answer[1].items():
                    self.store_answer(member, ticked, scope=card.scope())
            else:
                self.store_answer(question, answer[1], answer[2], card.scope())
            self.answered.add(normalized(question))
            saved += 1
        left = self.unanswered_required()
        if not saved and (left or not self.pending):
            self.notice.notify("Answer a question first." if self.pending else "Enter the exact question and its answer first.", "warning")
            return
        if left:
            self.scroll.ensureWidgetVisible(left[0])
            self.notice.notify(f"Saved {saved} answer{'s' if saved > 1 else ''}. {len(left)} required question{'s' if len(left) > 1 else ''} still need{'' if len(left) > 1 else 's'} an answer.", "warning")
        elif self.pending:
            # An optional question left empty is left blank on purpose, or the application would stop for it again.
            for card in self.cards:
                if card.answer() is None:
                    for question in card.members or [card.question]:
                        self.store_answer(question, "", omit=True)
            self.accept()  # Every required question is answered: carry on without a separate Resume step.
        else:
            self.notice.notify("Answer saved. It applies the next time a form asks this question.", "success")

    def store_answer(self, question, value, omit=False, scope="application"):
        key = self.run.id if scope == "application" else employer_key(self.run.job_url) if scope == "employer" else ""
        country = self.run.profile_snapshot.country if self.run.profile_snapshot else ""
        answer = ApprovedAnswer(question=question, profile_name=self.run.profile_name, value=value, scope=scope, scope_key=key, country=country, omit=omit)
        for existing in self.store.answers():
            if not (asks(existing, question) and existing.profile_name == self.run.profile_name and existing.scope == scope and existing.scope_key == key and existing.country == country):
                continue
            if normalized(existing.question) == normalized(question):
                # Editing the same scoped answer replaces it (and any duplicate of it) instead of creating a conflict.
                self.store.delete_answer(existing.id)
                answer.id, answer.question = existing.id, existing.question
                answer.variants = list(dict.fromkeys([*answer.variants, *existing.variants]))
            else:
                # This wording now has its own answer; the answer it was linked to keeps its value for its other wordings.
                existing.variants = [v for v in existing.variants if normalized(v) != normalized(question)]
                self.store.save_answer(existing)
        self.store.save_answer(answer)


class ReviewDialog(QDialog):
    """The application you approve: every value read back from the form, with what deserves a second look first."""
    EDIT = 2

    def __init__(self, store, run, can_send=True, parent=None):
        super().__init__(parent)
        name = run.company or site_key(run.job_url)
        self.setWindowTitle(f"Review application — {name}")
        self.resize(820, 720)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(station_heading("Review before sending", "dispatch", f"{name} · {run.role}", compact=True))
        source = f" · found through the listing on {site_key(run.listing_url)}" if run.listing_url else ""
        layout.addWidget(label(f"Profile {run.profile_name} · {ats_name(run.job_url) or site_key(run.job_url)}{source}", "muted"))
        files = [f"{a.label}: {a.value}" for a in run.fields.values() if a.kind == "file" and a.disposition == "verified" and a.value]
        layout.addWidget(label("Attached · " + (" · ".join(files) if files else "no documents"), "caption"))
        notice = MessageBar()
        layout.addWidget(notice)
        # A review verified before values were recorded can't be approved as seen; a recheck reads them back.
        unread = any(a.disposition == "verified" and a.value == "" for a in run.fields.values())
        messages = [i.message for i in run.interventions] + (["This review was prepared before Intern-Bot recorded the values it read back. Click Recheck on the board, then review it again."] if unread else [])
        if messages:
            notice.notify("\n".join(messages), "warning")

        ai = {"answer:" + a.id for a in store.answers() if a.origin == "ai"}
        self.ai_ids = {a.answer_ref.removeprefix("answer:") for a in run.fields.values() if a.answer_ref in ai}
        tree = ReadableTree()
        tree.setAccessibleName("Filled application answers")
        tree.setHeaderLabels(["Field", "Value", "Note"])
        tree.header().setStretchLastSection(False)
        tree.setColumnWidth(0, 210)
        tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        tree.setColumnWidth(2, 190)
        first = QTreeWidgetItem(tree, ["Check these first"])
        pages, seen = {}, set()
        sections = list(dict.fromkeys([*run.completed_sections, *(a.section for a in run.fields.values())]))
        for assessment in run.fields.values():
            if assessment.disposition not in {"verified", "intentionally_omitted"} or assessment.kind == "password":
                continue
            if assessment.kind == "radio" and assessment.value is not True and assessment.disposition == "verified":
                continue  # Each radio button is its own field; only the chosen one is the answer.
            identity = (assessment.section, assessment.label, assessment.group, assessment.row)
            if identity in seen:
                continue
            seen.add(identity)
            value = assessment.option if assessment.kind == "radio" and assessment.value is True else shown_value(assessment)
            group_name = {"experience": "job", "education": "education", "language_proficiency": "language"}.get(assessment.group, assessment.group)
            field = assessment.label + (f" ({group_name} {assessment.row + 1})" if assessment.group else "")
            note, flagged = ("Document", False) if assessment.kind == "file" else ("Profile", False) if assessment.answer_ref.startswith("profile:") else ("Your saved answer", False)
            if assessment.answer_ref in ai:
                note, flagged = "AI answer · approving confirms it as yours", True
            elif DECLARATION.search(assessment.label):
                note, flagged = "Declaration · approving accepts it for this application", True
            elif assessment.disposition == "intentionally_omitted":
                note, flagged = "Optional · left blank on purpose", True
            if not flagged:
                index = sections.index(assessment.section) + 1 if assessment.section in sections else 1
                if index not in pages:
                    title = run.steps[index - 1] if len(run.steps) == len(sections) else assessment.section
                    if not title or re.fullmatch(r"[\w -]+:[0-9a-f]{10}|form_.*", title):
                        title = f"Application section {index}"
                    pages[index] = QTreeWidgetItem(tree, [title])
            item = QTreeWidgetItem(first if flagged else pages[index], [field, value, note])
            for column in range(3):
                item.setToolTip(column, item.text(column))
        first.setHidden(not first.childCount())
        tree.expandAll()
        layout.addWidget(tree, 1)
        confirms = f" Approving also confirms the {len(self.ai_ids)} AI answer{'s' if len(self.ai_ids) != 1 else ''} above." if self.ai_ids else ""
        layout.addWidget(label("Approve & send rechecks the form first and sends only if it still matches what you see here. "
                               "Edit in browser to change something, then Recheck." + confirms, "caption"))
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        edit = buttons.addButton("Edit in browser", QDialogButtonBox.ActionRole)
        edit.clicked.connect(lambda: self.done(self.EDIT))
        self.send_btn = buttons.addButton("Approve && send", QDialogButtonBox.AcceptRole)
        restyle(self.send_btn, variant="primary")
        self.send_btn.setEnabled(can_send and not run.submission_attempted and not unread)
        if not can_send:
            self.send_btn.setToolTip("Another application is running. Send this one when it finishes.")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class RecipeReviewDialog(QDialog):
    """A site recipe before it drives later applications: what it learned, and the answers you typed that it would keep."""

    def __init__(self, store, recipe, proposals=(), parent=None):
        super().__init__(parent)
        self.store, self.recipe, self.proposals = store, recipe, list(proposals)
        self.setWindowTitle(f"Save recipe — {recipe.host}")
        self.resize(640, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(station_heading("Review filling guide", "fill", recipe.host, compact=True))
        source = "learned by watching you" if recipe.origin == "taught" else "drafted by the AI filling it"
        layout.addWidget(label(f"{source.capitalize()}. Later applications on this site fill without AI. It stores no personal values, "
                               "only how to drive the site; your answers stay in the answer bank.", "muted"))
        nexts = [b.text or b.css for b in recipe.buttons if b.action == "next"]
        submits = [b.text or b.css for b in recipe.buttons if b.action == "submit"]
        layout.addWidget(label("Continue: " + (", ".join(nexts) or "the site's own Next buttons") +
                               " · Submit: " + (", ".join(submits) or "recognized from its wording"), "caption"))
        layout.addWidget(label(f"Confirmation page: “{recipe.receipt}”" if recipe.receipt else
                               "Confirmation page: not known yet. You submit on this site until Intern-Bot sees it once (press I submitted it on that page).", "caption"))
        fields = QListWidget()
        for f in recipe.fields:
            fields.addItem(f"{f.match or f.css} · {f.widget} dropdown" if f.widget != "native" else f"{f.match or f.css} · read as “{f.label}”")
        layout.addWidget(label("Controls it handles specially", "overline"))
        layout.addWidget(fields if recipe.fields else label("None. Every field on this site has a plain label.", "caption"))
        self.answers = QListWidget()
        for answer in self.proposals:
            value = f"your profile ({fact_name(answer.fact)})" if answer.fact else ("Yes" if answer.value else "No") if isinstance(answer.value, bool) else str(answer.value)
            item = QListWidgetItem(f"{answer.question} → {value} · {'everywhere' if answer.scope == 'global' else 'this employer'}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            # A declaration is accepted per application, so keeping it for next time is your explicit choice.
            item.setCheckState(Qt.Unchecked if DECLARATION.search(answer.question) else Qt.Checked)
            self.answers.addItem(item)
        if self.proposals:
            layout.addWidget(label("Answers to keep", "overline"))
            layout.addWidget(self.answers, 1)
        buttons = QDialogButtonBox()
        discard = buttons.addButton("Discard", QDialogButtonBox.DestructiveRole)
        discard.clicked.connect(self.discard)
        save = buttons.addButton("Save recipe", QDialogButtonBox.AcceptRole)
        restyle(save, variant="primary")
        buttons.accepted.connect(self.save)
        layout.addWidget(buttons)

    def save(self):
        save_recipe(self.store, self.recipe.model_copy(update={"approved": True}))
        for index, answer in enumerate(self.proposals):
            if self.answers.item(index).checkState() == Qt.Checked:
                self.store.save_answer(answer)
        self.accept()

    def discard(self):
        stored = self.store.get("recipes", {})
        if not stored.get(self.recipe.host, {}).get("approved"):
            stored.pop(self.recipe.host, None)  # Only an unapproved draft goes; a recipe you saved earlier stays.
            self.store.put("recipes", stored)
        self.reject()


class AnswersView(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.answers = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(station_heading("Answer library", "verify", "Review reusable answers, their scope and the question wordings they match."), 1)
        self.filter = QComboBox()
        self.filter.addItems(["All answers", "Needs confirmation", "Approved"])
        self.filter.setAccessibleName("Filter answers by approval")
        self.filter.currentIndexChanged.connect(self.refresh)
        header.addWidget(self.filter)
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
        # Each answer is a row; the wordings it was matched to are collapsible children.
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Question", "Answer", "Applies to", "Profile", "Country"])
        self.tree.setUniformRowHeights(True)
        self.tree.setWordWrap(False)
        header_view = self.tree.header()
        header_view.setStretchLastSection(False)
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 160), (2, 240), (3, 110), (4, 100)):
            self.tree.setColumnWidth(column, width)
        self.tree.itemSelectionChanged.connect(self.update_actions)
        layout.addWidget(self.tree, 1)
        self.empty = label("Answers you approve while resolving an application's questions appear here.", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty, 1)
        row = QHBoxLayout()
        row.addStretch()
        self.confirm_btn = button("Confirm AI answer", self.confirm, "primary")
        row.addWidget(self.confirm_btn)
        self.remove_btn = button("Delete answer…", self.remove, "danger")
        row.addWidget(self.remove_btn)
        layout.addLayout(row)
        for keys in ("Delete", "Backspace"):
            shortcut(keys, self.tree, self.remove, Qt.WidgetShortcut)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        self.answers = self.store.answers()
        companies = {run.id: run.company or site_key(run.job_url) for run in self.store.runs()}
        query = self.search.text().strip().casefold()
        self.tree.clear()
        for answer in self.answers:
            if self.filter.currentIndex() == 1 and answer.origin != "ai":
                continue
            if self.filter.currentIndex() == 2 and answer.origin == "ai":
                continue
            if query not in " ".join([answer.question, *answer.variants, shown(answer)]).casefold():
                continue
            applies = {"application": f"Only the {companies.get(answer.scope_key, 'deleted')} application",
                       "employer": f"All applications at {answer.scope_key}", "global": "Any application"}[answer.scope]
            count = len(answer.variants)
            question = answer.question + (f"  ·  {count} more wording{'s' if count > 1 else ''}" if count else "")
            item = QTreeWidgetItem(self.tree, [question, shown(answer), applies, answer.profile_name, answer.country or "—"])
            item.setData(0, Qt.UserRole, answer.id)
            for column in range(5):
                item.setToolTip(column, item.text(column))
            for variant in answer.variants:
                child = QTreeWidgetItem(item, [variant])
                child.setData(0, Qt.UserRole, answer.id)
                child.setData(0, Qt.UserRole + 1, variant)
                child.setToolTip(0, f"Also asked as “{variant}”")
            # Searching for a wording opens its answer so the match is visible.
            item.setExpanded(bool(query) and any(query in v.casefold() for v in answer.variants))
        has_matches = bool(self.tree.topLevelItemCount())
        self.tree.setVisible(has_matches)
        self.empty.setVisible(not has_matches)
        self.empty.setText("No matching answers. Change the filter or clear your search." if self.answers else
                           "Answer a question from the workshop to start your library.")
        self.update_actions()

    def update_actions(self):
        item = self.tree.currentItem() if self.tree.selectedItems() else None
        self.remove_btn.setEnabled(bool(item))
        self.remove_btn.setText("Remove wording…" if item and item.data(0, Qt.UserRole + 1) else "Delete answer…")
        answer = next((a for a in self.answers if item and a.id == item.data(0, Qt.UserRole)), None)
        self.confirm_btn.setVisible(any(a.origin == "ai" for a in self.answers))
        self.confirm_btn.setEnabled(bool(answer) and answer.origin == "ai")

    def confirm(self):
        answer = next(a for a in self.answers if a.id == self.tree.currentItem().data(0, Qt.UserRole))
        answer.origin = "you"
        self.store.save_answer(answer)
        self.refresh()
        self.notice.notify("Confirmed. It now counts as your own answer, including for sending.", "success")

    def remove(self):
        if not self.tree.selectedItems():
            return
        item = self.tree.currentItem()
        answer = next(a for a in self.answers if a.id == item.data(0, Qt.UserRole))
        wording = item.data(0, Qt.UserRole + 1)
        if wording:
            if QMessageBox.question(self, "Remove this wording?", f"Stop answering “{wording}” with your answer to “{answer.question}”? Intern-Bot will ask again when a form uses this wording.") != QMessageBox.Yes:
                return
            answer.variants.remove(wording)
            self.store.save_answer(answer)
            self.refresh()
            self.notice.notify("Wording removed.", "success")
            return
        if QMessageBox.question(self, "Delete approved answer?", f"Delete your answer to “{answer.question}”{' and its other wordings' if answer.variants else ''}? Intern-Bot will ask again the next time this question appears.") != QMessageBox.Yes:
            return
        self.store.delete_answer(answer.id)
        self.refresh()
        self.notice.notify("Answer deleted.", "success")
