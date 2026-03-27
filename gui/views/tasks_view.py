from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QHBoxLayout, QLabel
from PySide6.QtCore import Qt

class TasksView(QWidget):
    def __init__(self, scheduler):
        super().__init__()
        self.scheduler = scheduler
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header Title
        title = QLabel("Tasks (0 Total)")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # Main Table
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Store / ATS", "Target URL", "Profile", "Status", "Play", "Edit", "Delete"
        ])
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch) # Stretch URL column
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        
        layout.addWidget(self.table)

        # Bottom Control Bar
        control_layout = QHBoxLayout()
        
        self.btn_create = QPushButton("+ Create Tasks")
        self.btn_create.setObjectName("primaryBtn")
        
        self.btn_clear = QPushButton("🗑 Clear Tasks")
        
        self.btn_start = QPushButton("▶ Start Tasks")
        self.btn_start.setObjectName("primaryBtn")
        self.btn_start.clicked.connect(self.start_all_tasks)
        
        self.btn_stop = QPushButton("■ Stop Tasks")
        
        control_layout.addWidget(self.btn_create)
        control_layout.addWidget(self.btn_clear)
        control_layout.addStretch()
        control_layout.addWidget(self.btn_start)
        control_layout.addWidget(self.btn_stop)
        
        layout.addLayout(control_layout)

    def start_all_tasks(self):
        print("[GUI] 'Start All Tasks' clicked! Initiating automation loop...")
        for row in range(self.table.rowCount()):
            self.start_single_task(row)

    def start_single_task(self, row_index):
        print(f"[GUI] 'Play' clicked on task row {row_index}! Queueing job...")
        
        url_item = self.table.item(row_index, 1)
        if not url_item:
            return
            
        target_url = url_item.text()
        status_item = self.table.item(row_index, 3)
        
        from plugins.manager import PluginManager
        plugin_class = PluginManager.get_plugin_for_url(target_url)
        
        if plugin_class:
            plugin_instance = plugin_class()
            # Queue the job in the asyncio loop safely
            self.scheduler.add_job(plugin_instance.apply_to_job, args=[target_url])
            
            # Update GUI status to indicate running state
            if status_item:
                status_item.setText("▶ Running")
                status_item.setForeground(Qt.green)
        else:
            print(f"[GUI] Failed to find module matching domain: {target_url}")
            if status_item:
                status_item.setText("✖ Error: No Plugin")
                status_item.setForeground(Qt.red)

    def add_dummy_task(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        self.table.setItem(row, 0, QTableWidgetItem("Workday"))
        self.table.setItem(row, 1, QTableWidgetItem("https://company.wd1.myworkdayjobs.com/"))
        self.table.setItem(row, 2, QTableWidgetItem("Profile 1"))
        
        status_item = QTableWidgetItem("● Pending")
        status_item.setForeground(Qt.yellow)
        self.table.setItem(row, 3, status_item)
        
        # Action Buttons
        play_btn = QPushButton("▶")
        play_btn.setObjectName("actionPlay")
        play_btn.clicked.connect(lambda checked=False, r=row: self.start_single_task(r))
        self.table.setCellWidget(row, 4, play_btn)
        
        edit_btn = QPushButton("✎")
        self.table.setCellWidget(row, 5, edit_btn)
        
        del_btn = QPushButton("🗑")
        del_btn.setObjectName("actionStop")
        self.table.setCellWidget(row, 6, del_btn)
