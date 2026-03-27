from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QFormLayout
from PySide6.QtCore import Qt

class ProfileView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Global Applicant Profile")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px; color: #FFFFFF;")
        layout.addWidget(title)
        
        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignRight if hasattr(Qt, 'AlignRight') else 2) # 2 is right align enum
        
        self.fname_input = QLineEdit()
        self.fname_input.setPlaceholderText("John")
        form_layout.addRow("First Name:", self.fname_input)
        
        self.lname_input = QLineEdit()
        self.lname_input.setPlaceholderText("Doe")
        form_layout.addRow("Last Name:", self.lname_input)
        
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("john.doe@example.com")
        form_layout.addRow("Email:", self.email_input)
        
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("555-0199")
        form_layout.addRow("Phone:", self.phone_input)
        
        layout.addLayout(form_layout)
        layout.addStretch()
