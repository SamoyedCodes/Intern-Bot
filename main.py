import sys
import PySide6.QtAsyncio as QtAsyncio
from PySide6.QtWidgets import QApplication
from dotenv import load_dotenv

# Load secrets from a local .env file into os.environ seamlessly
load_dotenv()

from gui.main_window import MainWindow
from apscheduler.schedulers.asyncio import AsyncIOScheduler

def main():
    app = QApplication(sys.argv)
    
    # Initialize background task scheduler
    scheduler = AsyncIOScheduler()
    scheduler.start()
    
    # Load and apply the Cybersole dark theme QSS
    try:
        with open("gui/styles.qss", "r") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print("Warning: gui/styles.qss not found. Using default styles.")
    
    window = MainWindow(scheduler)
    window.show()
    
    # Run the QtAsyncio loop to allow safe integration with Playwright background tasks
    QtAsyncio.run()

if __name__ == "__main__":
    main()
