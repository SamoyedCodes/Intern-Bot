import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent

# Ensure imports and relative paths resolve from the project root regardless
# of which directory the process was launched from.
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from core.automation.privacy import configure_privacy
configure_privacy()


def configure_qt_plugin_path():
    """Help Qt find PySide6's platform plugins when launched from IDEs or Anaconda."""
    import PySide6
    platforms_path = Path(PySide6.__file__).parent / "plugins" / "platforms"
    if platforms_path.exists():
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms_path)


configure_qt_plugin_path()

from PySide6.QtWidgets import QApplication, QMessageBox
from gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)

    styles_path = ROOT / "gui" / "styles.qss"
    if styles_path.exists():
        app.setStyleSheet(styles_path.read_text(encoding="utf-8"))
    else:
        print(f"Warning: {styles_path} not found. Using default styles.")

    try:
        window = MainWindow()
    except Exception:
        QMessageBox.critical(None, "Intern-Bot could not start", "Could not initialize local state or the operating-system keychain. Check that the keychain is available and the local data files are valid. No data files were removed.")
        return 1
    window.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
