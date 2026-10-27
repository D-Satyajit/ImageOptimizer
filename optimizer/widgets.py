"""File list model, image preview and small layout helpers."""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from .theme import COLORS

# File list columns: (metadata key, header)
COLUMNS = (
    ("filename", "Filename"),
    ("new_name", "New Name"),
    ("author", "Author"),
    ("size", "File Size"),
    ("file_type", "File Type"),
    ("extension", "Extension"),
    ("date", "Date"),
    ("date_taken", "Date Taken"),
    ("dimensions", "Dimensions"),
    ("resolution", "Resolution"),
    ("camera", "Camera Model"),
)
NEW_NAME_COLUMN = 1
COLUMN_WIDTHS = {"filename": 220, "new_name": 220, "date": 130, "date_taken": 140, "camera": 140}


def section_label(text):
    label = QLabel(text.upper())
    label.setObjectName("SectionTitle")
    return label


def hint_label(text=""):
    label = QLabel(text)
    label.setObjectName("Hint")
    label.setWordWrap(True)
    return label


def make_card(title):
    """Rounded panel with a title row; returns (card, header layout, body layout)"""
    card = QFrame()
    card.setObjectName("Card")
    body = QVBoxLayout(card)
    body.setContentsMargins(14, 12, 14, 14)
    body.setSpacing(10)
    header = QHBoxLayout()
    title_label = QLabel(title)
    title_label.setObjectName("CardTitle")
    header.addWidget(title_label)
    header.addStretch()
    body.addLayout(header)
    return card, header, body


def repolish(widget):
    """Re-apply the stylesheet after an objectName or property change"""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class FileTableModel(QAbstractTableModel):
    """File list with metadata; the New Name column previews renames"""

    def __init__(self, new_name_func):
        super().__init__()
        self.paths = []
        self.metadata = []
        self.new_name_func = new_name_func  # (path, row) -> new filename

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.paths)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        key = COLUMNS[index.column()][0]
        if role == Qt.ItemDataRole.DisplayRole:
            if key == "new_name":
                return self.new_name_func(self.paths[index.row()], index.row())
            return str(self.metadata[index.row()][key])
        if role == Qt.ItemDataRole.ToolTipRole and key == "filename":
            return self.paths[index.row()]
        if role == Qt.ItemDataRole.ForegroundRole and key == "new_name":
            return QColor(COLORS["accent"])
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section][1]
        return None

    def add_rows(self, rows):
        """Append (path, metadata) rows"""
        if not rows:
            return
        first = len(self.paths)
        self.beginInsertRows(QModelIndex(), first, first + len(rows) - 1)
        for path, meta in rows:
            self.paths.append(path)
            self.metadata.append(meta)
        self.endInsertRows()

    def remove_rows(self, rows):
        for row in sorted(rows, reverse=True):
            self.beginRemoveRows(QModelIndex(), row, row)
            del self.paths[row]
            del self.metadata[row]
            self.endRemoveRows()

    def clear(self):
        # Removing rows (rather than resetting the model) keeps column widths and hidden columns
        if self.paths:
            self.beginRemoveRows(QModelIndex(), 0, len(self.paths) - 1)
            self.paths = []
            self.metadata = []
            self.endRemoveRows()

    def refresh_new_names(self):
        if self.paths:
            self.dataChanged.emit(self.index(0, NEW_NAME_COLUMN), self.index(len(self.paths) - 1, NEW_NAME_COLUMN))


class PreviewLabel(QLabel):
    """Shows an image scaled to fit, rescaling as the panel resizes"""

    def __init__(self):
        super().__init__()
        self.setObjectName("PreviewImage")
        self._pixmap = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(200, 120)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def has_image(self):
        return self._pixmap is not None

    def image_size(self):
        return (self._pixmap.width(), self._pixmap.height()) if self._pixmap is not None else None

    def set_image(self, pixmap):
        self._pixmap = pixmap
        self.setText("")
        self._rescale()

    def set_message(self, text):
        self._pixmap = None
        self.setPixmap(QPixmap())
        self.setText(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self):
        if self._pixmap is None or self._pixmap.isNull():
            return
        dpr = self.devicePixelRatioF()
        scaled = self._pixmap.scaled(self.size() * dpr, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        # Never enlarge beyond the decoded preview
        if scaled.width() > self._pixmap.width():
            scaled = QPixmap(self._pixmap)
        scaled.setDevicePixelRatio(dpr)
        self.setPixmap(scaled)
