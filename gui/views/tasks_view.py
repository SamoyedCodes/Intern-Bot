import asyncio
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.storage import JsonStore
from plugins.manager import PluginManager


@dataclass
class ApplicationTask:
    company: str
    role: str
    job_url: str
    platform: str = "Workday"
    phase: str = "phase_1_login"
    status: str = "Queued"
    note: str = "Ready"

    def to_dict(self):
        return {
            "company": self.company,
            "role": self.role,
            "job_url": self.job_url,
            "platform": self.platform,
            "phase": self.phase,
            "status": self.status,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data):
        phase = data.get("phase", "phase_1_login")
        status = cls._normalize_status(data.get("status", "Queued"), phase)
        return cls(
            company=data.get("company", "Unknown Company"),
            role=data.get("role", "Internship"),
            job_url=data.get("job_url", ""),
            platform=data.get("platform", "Workday"),
            phase=phase,
            status=status,
            note=data.get("note", "Ready"),
        )

    @staticmethod
    def _normalize_status(status: str, phase: str):
        if status == "Awaiting Activation":
            return "Needs Review"
        if status == "Needs Review" and phase != "phase_1_awaiting_activation":
            if phase == "phase_3_application_questions_manual":
                return "Manual Questions"
            return "Manual Required"
        return status


class TaskDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Application Task")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel("New Application")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        self.company = QLineEdit()
        self.role = QLineEdit()
        self.url = QLineEdit()
        self.company.setPlaceholderText("Company")
        self.role.setPlaceholderText("Software Engineering Intern")
        self.url.setPlaceholderText("https://company.wd1.myworkdayjobs.com/...")

        layout.addWidget(self.company)
        layout.addWidget(self.role)
        layout.addWidget(self.url)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_task(self) -> ApplicationTask:
        return ApplicationTask(
            company=self.company.text().strip() or "Unknown Company",
            role=self.role.text().strip() or "Internship",
            job_url=self.url.text().strip(),
        )


class StatCard(QFrame):
    def __init__(self, label: str, value: str, accent: str):
        super().__init__()
        self.setObjectName("statCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("statValue")
        self.value_label.setStyleSheet(f"color: {accent};")

        label_widget = QLabel(label)
        label_widget.setObjectName("statLabel")

        layout.addWidget(self.value_label)
        layout.addWidget(label_widget)

    def set_value(self, value: int):
        self.value_label.setText(str(value))


class FitTextLabel(QLabel):
    """Single-line table label that shrinks text instead of eliding it."""

    def __init__(self, text: str, color=None):
        super().__init__(text)
        self._base_font = self.font()
        self._color = color
        self.setObjectName("fitTaskCell")
        self.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.setToolTip(text)
        self.setMinimumWidth(1)
        if color:
            self.setStyleSheet(f"color: {color};")
        self._fit_text()

    def sizeHint(self):
        fm = QFontMetrics(self._base_font)
        width = fm.horizontalAdvance(self.text()) + 12
        return QSize(min(width, 250), super().sizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_text()

    def _fit_text(self):
        width = max(1, self.width() - 12)
        font = self._base_font
        base_size = font.pointSize() if font.pointSize() > 0 else 10

        for size in range(base_size, 0, -1):
            candidate = self._base_font
            candidate.setPointSize(size)
            if QFontMetrics(candidate).horizontalAdvance(self.text()) <= width:
                self.setFont(candidate)
                return

        smallest = self._base_font
        smallest.setPointSize(1)
        self.setFont(smallest)


class TasksView(QWidget):
    status_message = Signal(str)
    task_finished = Signal(object, bool, object)

    def __init__(self, scheduler=None, profile_provider: Optional[Callable[[], Dict]] = None):
        super().__init__()
        self.scheduler = scheduler
        self.profile_provider = profile_provider
        self.plugin_manager = PluginManager()
        self.store = JsonStore()
        self.tasks: List[ApplicationTask] = []
        self._loading_state = False
        self.task_finished.connect(self._on_task_finished)

        self.setObjectName("tasksView")
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(18)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel("Application Queue")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Stage Workday internship applications, launch them, and review before submit.")
        subtitle.setObjectName("pageSubtitle")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)

        self.search = QLineEdit()
        self.search.setObjectName("searchInput")
        self.search.setPlaceholderText("Search tasks")
        self.search.textChanged.connect(self._render_table)

        header.addLayout(title_block)
        header.addStretch()
        header.addWidget(self.search)
        root.addLayout(header)

        stats = QGridLayout()
        stats.setHorizontalSpacing(14)
        self.total_card = StatCard("Total Tasks", "0", "#19d68b")
        self.ready_card = StatCard("Queued", "0", "#7c8cff")
        self.running_card = StatCard("Running", "0", "#37a7ff")
        self.needs_card = StatCard("Needs Review", "0", "#ffcc66")
        stats.addWidget(self.total_card, 0, 0)
        stats.addWidget(self.ready_card, 0, 1)
        stats.addWidget(self.running_card, 0, 2)
        stats.addWidget(self.needs_card, 0, 3)
        root.addLayout(stats)

        commands = QHBoxLayout()
        self.add_btn = QPushButton("New Task")
        self.add_btn.setObjectName("primaryButton")
        self.add_btn.clicked.connect(self.add_task_dialog)

        self.start_selected_btn = QPushButton("Start Selected")
        self.start_selected_btn.clicked.connect(self.start_selected_task)

        self.start_all_btn = QPushButton("Start All")
        self.start_all_btn.clicked.connect(self.start_all_tasks)

        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.clicked.connect(self.delete_selected_task)

        commands.addWidget(self.add_btn)
        commands.addWidget(self.start_selected_btn)
        commands.addWidget(self.start_all_btn)
        commands.addStretch()
        commands.addWidget(self.delete_btn)
        root.addLayout(commands)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Company", "Role", "Platform", "Phase", "Status", "Note", "URL", "Action"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(64)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Fixed)
        self.table.horizontalHeader().resizeSection(7, 120)
        self.table.setTextElideMode(Qt.ElideNone)
        root.addWidget(self.table)

        self.load_state()

    def add_task_dialog(self):
        dialog = TaskDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        task = dialog.get_task()
        if not task.job_url:
            self.status_message.emit("A task needs a job URL.")
            return
        self.add_task(task)

    def add_task(self, task: ApplicationTask):
        self.tasks.append(task)
        self._render_table()
        self.save_state()
        self.status_message.emit(f"Queued {task.role} at {task.company}.")

    def start_selected_task(self):
        row = self.table.currentRow()
        if row < 0:
            self.status_message.emit("Select a task first.")
            return
        task = self._task_for_visible_row(row)
        if task:
            self._start_task(task)

    def start_all_tasks(self):
        if not self.tasks:
            self.status_message.emit("No tasks to start.")
            return
        for task in list(self.tasks):
            if task.status in {"Queued", "Failed", "Paused", "Needs Review", "Manual Required", "Manual Questions"}:
                self._start_task(task)

    def delete_selected_task(self):
        row = self.table.currentRow()
        task = self._task_for_visible_row(row)
        if not task:
            self.status_message.emit("Select a task to delete.")
            return
        self.tasks.remove(task)
        self._render_table()
        self.save_state()
        self.status_message.emit(f"Deleted {task.company} task.")

    def _start_task(self, task: ApplicationTask):
        plugin = self.plugin_manager.get_plugin_for_url(task.job_url)
        if not plugin:
            task.status = "Failed"
            task.note = "No ATS plugin matched this URL"
            self._render_table()
            self.save_state()
            self.status_message.emit(task.note)
            return

        task.platform = plugin.portal_name
        if plugin.portal_name == "Workday":
            task.company = self._company_name_from_workday_url(task.job_url)
        task.status = "Running"
        task.note = "Launching browser"
        self._render_table()
        self.save_state()

        profile = self._get_profile_for_task(task)
        worker = threading.Thread(
            target=self._run_plugin_task_in_thread,
            args=(task, plugin, profile),
            daemon=True,
        )
        worker.start()
        self.status_message.emit(f"Started {task.company}.")

    def _pause_or_resume_task(self, task: ApplicationTask):
        if task.status == "Running":
            self.status_message.emit(f"{task.company} is already running.")
            return

        if task.status in {"Paused", "Failed", "Queued", "Needs Review", "Manual Required", "Manual Questions"}:
            self._start_task(task)
            return

        self.status_message.emit(f"{task.company} is not in a resumable state.")

    def _get_profile_for_task(self, task: ApplicationTask):
        if not self.profile_provider:
            return {}

        try:
            return self.profile_provider(task.job_url)
        except TypeError:
            return self.profile_provider()

    def _run_plugin_task_in_thread(self, task: ApplicationTask, plugin, profile: Dict):
        try:
            result = asyncio.run(plugin.apply_to_job(task.job_url, profile, {"phase": task.phase}))
            payload = self._normalize_plugin_result(result)
            self.task_finished.emit(task, payload["success"], payload)
        except Exception as exc:
            self.task_finished.emit(task, False, {"status": "Failed", "note": str(exc)})

    def _normalize_plugin_result(self, result):
        if isinstance(result, dict):
            return {
                "success": bool(result.get("success")),
                "status": result.get("status") or ("Manual Required" if result.get("success") else "Failed"),
                "phase": result.get("phase"),
                "note": result.get("note", ""),
            }

        return {
            "success": bool(result),
            "status": "Manual Required" if result else "Failed",
            "phase": None,
            "note": "Review browser before final submit" if result else "Automation returned false",
        }

    def _on_task_finished(self, task: ApplicationTask, success: bool, result: dict):
        task.status = result.get("status") or ("Manual Required" if success else "Failed")
        task.note = result.get("note", "")
        if result.get("phase"):
            task.phase = result["phase"]
        self._render_table()
        self.save_state()
        self.status_message.emit(f"{task.company}: {task.status}")

    def _task_for_visible_row(self, row: int) -> Optional[ApplicationTask]:
        if row < 0:
            return None
        tasks = self._filtered_tasks()
        return tasks[row] if row < len(tasks) else None

    def _filtered_tasks(self) -> List[ApplicationTask]:
        query = self.search.text().strip().lower()
        if not query:
            return self.tasks
        return [
            task for task in self.tasks
            if query in task.company.lower()
            or query in task.role.lower()
            or query in task.job_url.lower()
        ]

    def _render_table(self):
        visible_tasks = self._filtered_tasks()
        self.table.setRowCount(len(visible_tasks))
        for row, task in enumerate(visible_tasks):
            self.table.setRowHeight(row, 64)
            values = [
                task.company,
                task.role,
                task.platform,
                self._phase_label(task.phase),
                task.status,
                task.note,
                task.job_url,
            ]
            for col, value in enumerate(values):
                if col in {3, 4, 5}:
                    color = self._status_color_name(task.status) if col == 4 else None
                    self.table.setCellWidget(row, col, FitTextLabel(value, color=color))
                    continue
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)
            self.table.horizontalHeader().resizeSections(QHeaderView.ResizeToContents)
            action = QPushButton(self._action_label(task))
            action.setObjectName(self._action_object_name(task))
            action.setMinimumHeight(30)
            action.setMinimumWidth(96)
            action.setEnabled(task.status != "Running")
            action.clicked.connect(lambda checked=False, t=task: self._pause_or_resume_task(t))
            self.table.setCellWidget(row, 7, action)
        self._refresh_stats()

    def _action_label(self, task: ApplicationTask):
        if task.status == "Queued":
            return "Start"
        if task.status == "Running":
            return "Running"
        if task.status == "Needs Review":
            return "Resume"
        if task.status == "Manual Questions":
            return "Manual"
        return "Resume"

    def _action_object_name(self, task: ApplicationTask):
        if task.status == "Queued":
            return "taskStartButton"
        if task.status == "Running":
            return "taskRunningButton"
        return "taskResumeButton"

    def _phase_label(self, phase: str):
        labels = {
            "phase_1_login": "Sign In / Account",
            "phase_1_awaiting_activation": "Email Activation",
            "phase_2_autofill_resume": "Autofill with Resume",
            "phase_2_my_information": "My Information",
            "phase_2_my_experience": "My Experience",
            "phase_3_application_questions_manual": "Application Questions - Manual",
        }
        return labels.get(phase, phase)

    def _refresh_stats(self):
        counts = {
            "total": len(self.tasks),
            "queued": sum(1 for task in self.tasks if task.status == "Queued"),
            "running": sum(1 for task in self.tasks if task.status == "Running"),
            "needs": sum(1 for task in self.tasks if task.status == "Needs Review"),
        }
        self.total_card.set_value(counts["total"])
        self.ready_card.set_value(counts["queued"])
        self.running_card.set_value(counts["running"])
        self.needs_card.set_value(counts["needs"])

    def _status_color(self, status: str):
        if status == "Running":
            return Qt.cyan
        if status == "Needs Review":
            return Qt.yellow
        if status == "Manual Required":
            return Qt.yellow
        if status == "Manual Questions":
            return Qt.yellow
        if status == "Paused":
            return Qt.lightGray
        if status == "Failed":
            return Qt.red
        return Qt.green



    @staticmethod
    def _company_name_from_workday_url(job_url):
        parsed = urlparse(job_url)
        host = parsed.netloc.lower()
        if not host:
            host = job_url.lower().split("/")[0]
        host = host.replace("www.", "")
        slug = host.split(".", 1)[0] if host else "Workday"
        return slug.replace("-", " ").replace("_", " ").title()

    def load_state(self):
        self._loading_state = True
        data = self.store.load()
        task_rows = data.get("tasks", [])
        self.tasks = [
            ApplicationTask.from_dict(row)
            for row in task_rows
            if row.get("job_url")
        ]
        self._loading_state = False
        self._render_table()

    def save_state(self):
        if self._loading_state:
            return

        data = self.store.load()
        data["tasks"] = [task.to_dict() for task in self.tasks]
        self.store.save(data)
