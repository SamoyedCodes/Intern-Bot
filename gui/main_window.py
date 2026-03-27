from PySide6.QtWidgets import QMainWindow, QTabWidget, QVBoxLayout, QWidget, QLabel, QHBoxLayout
from PySide6.QtCore import Qt
from gui.views.tasks_view import TasksView
from gui.views.profile_view import ProfileView

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Intern-Bot")
        self.resize(1050, 650)
        
        # Central Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Top Nav Bar (Custom styled via QSS)
        self.tabs = QTabWidget()
        
        # Add Views
        self.tasks_view = TasksView()
        self.profile_view = ProfileView()
        
        # Inject dummy data to show Cybersole similarity
        self.tasks_view.add_dummy_task()
        self.tasks_view.add_dummy_task()
        self.tasks_view.add_dummy_task()
        
        self.tabs.addTab(self.tasks_view, "Tasks")
        self.tabs.addTab(self.profile_view, "Profile")
        self.tabs.addTab(QWidget(), "Settings") # Empty settings tab
        
        main_layout.addWidget(self.tabs)
        
        # Bottom Status Bar
        status_widget = QWidget()
        status_widget.setStyleSheet("background-color: #15151F; padding: 2px;")
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(15, 5, 15, 5)
        
        conn_label = QLabel("● Connected")
        conn_label.setStyleSheet("color: #2ECC71; font-weight: bold; font-size: 11px;")
        
        ver_label = QLabel("Version 1.0.0 (Latest)")
        ver_label.setStyleSheet("color: #888888; font-size: 11px;")
        
        status_layout.addWidget(conn_label)
        status_layout.addStretch()
        status_layout.addWidget(ver_label)
        
        main_layout.addWidget(status_widget)
