"""Qt application setup and entry point."""
import logging
import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .theme import build_stylesheet, dark_palette


def log_uncaught_exception(exc_type, exc_value, exc_traceback):
    """Errors inside Qt callbacks would otherwise vanish under pythonw"""
    logging.error("Unhandled error", exc_info=(exc_type, exc_value, exc_traceback))


def create_app(argv):
    app = QApplication(argv)
    app.setApplicationName("Image Optimizer Pro")
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setStyleSheet(build_stylesheet())
    return app


def run(settings_path, argv=None):
    """Show the main window; returns the exit code. settings_path is the INI for remembered folders."""
    sys.excepthook = log_uncaught_exception
    if sys.platform == "win32":
        try:
            # Show the app's own icon in the taskbar instead of Python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ImageOptimizerPro")
        except Exception:
            pass
    app = create_app(sys.argv if argv is None else argv)
    window = MainWindow(settings_path)
    window.show()
    return app.exec()
