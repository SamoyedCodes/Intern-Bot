import sys
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent

# Ensure imports and relative paths resolve from the project root regardless
# of which directory the process was launched from.
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")


def configure_qt_plugin_path():
    """Help Qt find PySide6's platform plugins when launched from IDEs or Anaconda."""
    import PySide6
    platforms_path = Path(PySide6.__file__).parent / "plugins" / "platforms"
    if platforms_path.exists():
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms_path)


configure_qt_plugin_path()

from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)

    styles_path = ROOT / "gui" / "styles.qss"
    if styles_path.exists():
        app.setStyleSheet(styles_path.read_text(encoding="utf-8"))
    else:
        print(f"Warning: {styles_path} not found. Using default styles.")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
