import sys
import PySide6.QtAsyncio as QtAsyncio
from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    
    # Load and apply the Cybersole dark theme QSS
    try:
        with open("gui/styles.qss", "r") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print("Warning: gui/styles.qss not found. Using default styles.")
    
    window = MainWindow()
    window.show()
    
    # Run the QtAsyncio loop to allow safe integration with Playwright background tasks
    QtAsyncio.run()

if __name__ == "__main__":
    main()
