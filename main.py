import sys
import os
from pathlib import Path
from PySide6.QtCore import QLibraryInfo
from PySide6.QtWidgets import QApplication
from dotenv import load_dotenv

# Load secrets from a local .env file into os.environ seamlessly
load_dotenv()

from gui.main_window import MainWindow


def configure_qt_plugin_path():
    """Help Qt find PySide6's platform plugins when launched from IDEs."""
    plugins_path = Path(QLibraryInfo.path(QLibraryInfo.PluginsPath))
    platforms_path = plugins_path / "platforms"

    if platforms_path.exists():
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms_path)


def main():
    configure_qt_plugin_path()
    app = QApplication(sys.argv)
    
    # Load and apply the Cybersole dark theme QSS
    try:
        with open("gui/styles.qss", "r") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print("Warning: gui/styles.qss not found. Using default styles.")
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
