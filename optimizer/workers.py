"""Background jobs, so reading files and optimizing never block the window."""
import logging

from PySide6.QtCore import QObject, QRunnable, QThread, Signal
from PySide6.QtGui import QImage

from . import core

PREVIEW_SIZE = 1200  # Longest side decoded for the preview
METADATA_CHUNK = 25  # Rows sent to the file list at a time


class MetadataSignals(QObject):
    loaded = Signal(int, list)  # load generation, [(path, metadata), ...]
    finished = Signal(int)


class MetadataLoader(QRunnable):
    """Reads file metadata on the thread pool, reporting rows in small chunks"""

    def __init__(self, generation, paths):
        super().__init__()
        self.setAutoDelete(False)  # The window keeps it alive until it reports back
        self.generation = generation
        self.paths = paths
        self.signals = MetadataSignals()

    def run(self):
        chunk = []
        for path in self.paths:
            chunk.append((path, core.extract_metadata(path)))
            if len(chunk) == METADATA_CHUNK:
                self.signals.loaded.emit(self.generation, chunk)
                chunk = []
        if chunk:
            self.signals.loaded.emit(self.generation, chunk)
        self.signals.finished.emit(self.generation)


class PreviewSignals(QObject):
    ready = Signal(str, QImage)  # path, preview (null if it could not be read)


class PreviewLoader(QRunnable):
    """Decodes a downscaled preview on the thread pool"""

    def __init__(self, path):
        super().__init__()
        self.setAutoDelete(False)
        self.path = path
        self.signals = PreviewSignals()

    def run(self):
        try:
            img = core.load_preview(self.path, PREVIEW_SIZE)
            data = img.tobytes("raw", "RGBA")
            image = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888).copy()
        except Exception as e:
            logging.error(f"Error loading preview for {self.path}: {str(e)}")
            image = QImage()
        self.signals.ready.emit(self.path, image)


class OptimizeWorker(QThread):
    """Runs one optimization batch on its own thread"""
    progress = Signal(int, int, str)  # done, total, current filename
    done = Signal(int, int, int, bool, str)  # total, files written, errors, cancelled, output dir

    def __init__(self, settings: core.OptimizeSettings):
        super().__init__()
        self.settings = settings
        self.silent = False  # Set when the batch was reset; its result is not shown
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self.settings.images)
        try:
            result = core.BatchOptimizer(self.settings).run(self.progress.emit, lambda: self._cancelled)
            written, errors, cancelled = len(result.report), result.errors, result.cancelled
        except Exception:
            logging.exception("Batch failed")
            written, errors, cancelled = 0, total, False
        self.done.emit(total, written, errors, cancelled, self.settings.output_dir)
