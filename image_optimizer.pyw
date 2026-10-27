"""Image Optimizer Pro launcher: double-click this file, or run start.bat."""
import logging
import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Errors go to a log next to this file, since pythonw has no console
logging.basicConfig(
    filename=os.path.join(APP_DIR, "image_optimizer.log"),
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

if __name__ == "__main__":
    try:
        from optimizer.app import run
        sys.exit(run(settings_path=os.path.join(APP_DIR, "image_optimizer.ini")))
    except Exception as e:
        logging.exception("Critical error occurred")
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "Fatal Error",
                                 f"Application crashed: {str(e)}\nCheck image_optimizer.log for details")
        except Exception:
            pass
