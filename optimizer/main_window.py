"""Main window: sidebar settings, preview, file list and status bar."""
import logging
import os

from PySide6.QtCore import QSettings, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QIntValidator, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QProgressBar, QPushButton, QRadioButton,
                               QScrollArea, QSlider, QSplitter, QStackedWidget, QTableView,
                               QVBoxLayout, QWidget)

from . import core
from .theme import ICON_PATH
from .widgets import (COLUMN_WIDTHS, COLUMNS, NEW_NAME_COLUMN, FileTableModel, PreviewLabel,
                      hint_label, make_card, repolish, section_label)
from .workers import MetadataLoader, OptimizeWorker, PreviewLoader

PREVIEW_CACHE_SIZE = 30

RENAME_HINTS = {
    "Sequential Numbering": "image_1, image_2, image_3 …",
    "Alphanumeric Pattern": "img_A1 … img_A10, img_B1 …",
    "Add Prefix/Suffix": "prefix + original name + suffix",
    "Date and Time": "FILE_<date>_<time>_1, FILE_<date>_<time>_2 …",
    "Custom Pattern": "prefix_1_suffix. Prefix and suffix may use {name}, {date} and {time}.",
}


def plural(count, word):
    return f"{count} {word}{'s' if count != 1 else ''}"


class MainWindow(QMainWindow):
    def __init__(self, settings_path):
        super().__init__()
        self.setWindowTitle("Image Optimizer Pro")
        self.resize(1200, 800)
        self.setMinimumSize(1000, 700)
        self.setAcceptDrops(True)
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))

        # Remembers the last folders used
        self.settings_store = QSettings(settings_path, QSettings.Format.IniFormat)
        self.pool = QThreadPool.globalInstance()
        self.jobs = {}  # signals object -> running QRunnable (keeps both alive)
        self.load_generation = 0  # Bumped on clear/reset so late metadata results are ignored
        self.pending_keys = set()  # Files whose metadata is still loading
        self.load_done_status = "Ready"
        self.preview_cache = {}  # path -> QImage, oldest first
        self.preview_path = None
        self.worker = None
        self.last_output_dir = ""
        self.mode = "optimize"

        self.model = FileTableModel(self.preview_new_name)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.build_sidebar())
        root.addWidget(self.build_main_area(), 1)
        self.setCentralWidget(central)
        self.build_status_bar()

        # Short delay so scrolling through the list doesn't decode every image on the way
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(60)
        self.preview_timer.timeout.connect(self.load_current_preview)

        open_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Open), self)
        open_shortcut.activated.connect(self.browse_files)
        delete_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), self.table)
        delete_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        delete_shortcut.activated.connect(self.remove_selected)

        self.reset_settings()
        self.set_mode("optimize")

    # ========== LAYOUT ==========
    def build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(300)
        outer = QVBoxLayout(sidebar)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(10)

        title = QLabel("Image Optimizer Pro")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Optimize and rename images in bulk")
        subtitle.setObjectName("Muted")
        outer.addWidget(title)
        outer.addWidget(subtitle)
        outer.addSpacing(4)

        # Mode switch
        segment_bar = QFrame()
        segment_bar.setObjectName("SegmentBar")
        segment_layout = QHBoxLayout(segment_bar)
        segment_layout.setContentsMargins(3, 3, 3, 3)
        segment_layout.setSpacing(3)
        self.optimize_mode_btn = QPushButton("Image Optimize")
        self.rename_mode_btn = QPushButton("File Rename")
        mode_group = QButtonGroup(self)
        for button, mode in ((self.optimize_mode_btn, "optimize"), (self.rename_mode_btn, "rename")):
            button.setObjectName("Segment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked, m=mode: self.set_mode(m))
            mode_group.addButton(button)
            segment_layout.addWidget(button)
        outer.addWidget(segment_bar)

        # Settings for the current mode (scrolls on small screens); the hidden page takes no space
        self.settings_panel = QWidget()
        self.settings_panel.setObjectName("SettingsPage")
        panel_layout = QVBoxLayout(self.settings_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        self.optimize_page = self.build_optimize_page()
        self.rename_page = self.build_rename_page()
        panel_layout.addWidget(self.optimize_page)
        panel_layout.addWidget(self.rename_page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setObjectName("SidebarViewport")
        scroll.setWidget(self.settings_panel)
        outer.addWidget(scroll, 1)

        # Actions
        self.browse_btn = QPushButton("Add Images…")
        self.browse_btn.setObjectName("Browse")
        self.browse_btn.setToolTip("Add files (Ctrl+O). You can also drag files or folders onto the window.")
        self.browse_btn.clicked.connect(self.browse_files)

        self.run_btn = QPushButton("Optimize Images")
        self.run_btn.setObjectName("Primary")
        self.run_btn.clicked.connect(self.run_action)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_processing)
        self.cancel_btn.hide()

        reset_btn = QPushButton("Clear All && Reset")
        reset_btn.setObjectName("Danger")
        reset_btn.clicked.connect(self.reset_application)

        for button in (self.browse_btn, self.run_btn, self.cancel_btn, reset_btn):
            button.setMinimumHeight(38)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            outer.addWidget(button)
        return sidebar

    def build_optimize_page(self):
        page = QWidget()
        page.setObjectName("SettingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(6)

        layout.addWidget(section_label("Output format"))
        format_grid = QGridLayout()
        format_grid.setHorizontalSpacing(12)
        self.format_group = QButtonGroup(self)
        self.format_buttons = {}
        for i, fmt in enumerate(core.OUTPUT_FORMATS):
            button = QRadioButton(fmt)
            self.format_group.addButton(button)
            self.format_buttons[fmt.lower()] = button
            format_grid.addWidget(button, i // 2, i % 2)
        layout.addLayout(format_grid)

        layout.addWidget(section_label("Compression"))
        comp_row = QHBoxLayout()
        self.lossy_rb = QRadioButton("Lossy")
        self.lossless_rb = QRadioButton("Lossless")
        comp_group = QButtonGroup(self)
        for button in (self.lossy_rb, self.lossless_rb):
            comp_group.addButton(button)
            comp_row.addWidget(button)
        comp_row.addStretch()
        layout.addLayout(comp_row)
        self.lossy_rb.toggled.connect(self.on_comp_mode_change)

        quality_row = QHBoxLayout()
        self.quality_title = QLabel("Quality")
        self.quality_value = QLabel()
        quality_row.addWidget(self.quality_title)
        quality_row.addStretch()
        quality_row.addWidget(self.quality_value)
        layout.addLayout(quality_row)
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(10, 100)
        self.quality_slider.valueChanged.connect(lambda value: self.quality_value.setText(f"{value}%"))
        layout.addWidget(self.quality_slider)
        self.comp_hint = hint_label()
        layout.addWidget(self.comp_hint)

        layout.addWidget(section_label("Size"))
        self.size_combo = QComboBox()
        self.size_combo.addItems(list(core.SIZE_PRESETS))
        self.size_combo.currentTextChanged.connect(self.on_size_preset_select)
        layout.addWidget(self.size_combo)
        width_row = QHBoxLayout()
        width_row.addWidget(QLabel("Width"))
        self.width_edit = QLineEdit()
        self.width_edit.setValidator(QIntValidator(1, 50000, self))
        self.width_edit.setPlaceholderText("Original size")
        self.width_edit.textChanged.connect(self.update_output_size)
        width_row.addWidget(self.width_edit, 1)
        width_row.addWidget(QLabel("px"))
        layout.addLayout(width_row)
        self.output_size_label = hint_label()
        self.output_size_label.setToolTip("Height follows each image's own shape. Smaller images are never enlarged.")
        layout.addWidget(self.output_size_label)

        layout.addWidget(section_label("Options"))
        self.progressive_cb = QCheckBox("Progressive JPEG")
        self.progressive_cb.setToolTip("JPEG only: loads gradually on slow connections")
        self.lqip_cb = QCheckBox("Generate LQIP placeholder")
        self.lqip_cb.setToolTip("Also save a tiny blurred _lqip copy to show while the full image loads")
        self.strip_metadata_cb = QCheckBox("Strip metadata (EXIF, GPS)")
        self.strip_metadata_cb.setToolTip("Remove camera data and location. The color profile is kept.")
        self.hashed_names_cb = QCheckBox("Hashed filenames")
        self.hashed_names_cb.setToolTip("Name outputs by a content hash instead of the original name")
        for checkbox in (self.progressive_cb, self.lqip_cb, self.strip_metadata_cb, self.hashed_names_cb):
            layout.addWidget(checkbox)
        layout.addStretch()
        return page

    def build_rename_page(self):
        page = QWidget()
        page.setObjectName("SettingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(6)

        layout.addWidget(section_label("Bulk rename pattern"))
        self.pattern_combo = QComboBox()
        self.pattern_combo.addItems(core.RENAME_PATTERNS)
        self.pattern_combo.currentTextChanged.connect(self.on_rename_options_changed)
        layout.addWidget(self.pattern_combo)
        self.pattern_hint = hint_label()
        layout.addWidget(self.pattern_hint)

        layout.addWidget(section_label("Prefix and suffix"))
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setPlaceholderText("Prefix")
        self.suffix_edit = QLineEdit()
        self.suffix_edit.setPlaceholderText("Suffix")
        for edit in (self.prefix_edit, self.suffix_edit):
            edit.textChanged.connect(self.on_rename_options_changed)
            layout.addWidget(edit)

        layout.addWidget(section_label("Date and time"))
        date_row = QHBoxLayout()
        self.include_date_cb = QCheckBox("Date")
        self.include_time_cb = QCheckBox("Time")
        for checkbox in (self.include_date_cb, self.include_time_cb):
            checkbox.toggled.connect(self.on_rename_options_changed)
            date_row.addWidget(checkbox)
        date_row.addStretch()
        layout.addLayout(date_row)
        layout.addWidget(hint_label("The New Name column previews the result. Renaming changes the files on disk."))
        layout.addStretch()
        return page

    def build_main_area(self):
        area = QWidget()
        area.setObjectName("MainArea")
        layout = QVBoxLayout(area)
        layout.setContentsMargins(16, 16, 16, 12)

        self.preview_card, preview_header, preview_body = make_card("Preview")
        self.preview_info = QLabel()
        self.preview_info.setObjectName("Muted")
        preview_header.addWidget(self.preview_info)
        self.preview = PreviewLabel()
        preview_body.addWidget(self.preview, 1)

        self.files_card, files_header, files_body = make_card("Files")
        self.files_count = QLabel()
        self.files_count.setObjectName("Muted")
        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.setObjectName("Small")
        self.remove_btn.setToolTip("Remove the selected files from the list (Delete). Files on disk are not touched.")
        self.remove_btn.clicked.connect(self.remove_selected)
        files_header.insertWidget(1, self.files_count)
        files_header.addWidget(self.remove_btn)

        # Drop hint while the list is empty, the table otherwise
        self.files_stack = QStackedWidget()
        self.drop_hint = QLabel()
        self.drop_hint.setObjectName("DropHint")
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(28)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for column, (key, _) in enumerate(COLUMNS):
            self.table.setColumnWidth(column, COLUMN_WIDTHS.get(key, 100))
        self.table.selectionModel().currentRowChanged.connect(self.on_current_row_changed)
        self.files_stack.addWidget(self.drop_hint)
        self.files_stack.addWidget(self.table)
        files_body.addWidget(self.files_stack, 1)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(12)
        splitter.addWidget(self.preview_card)
        splitter.addWidget(self.files_card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([340, 420])
        layout.addWidget(splitter)
        return area

    def build_status_bar(self):
        """Status message, progress bar and counts at the bottom of the window"""
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(12, 4, 12, 4)
        row.setSpacing(12)
        self.status_label = QLabel()
        self.progress_info = QLabel()
        self.progress_info.setObjectName("Muted")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedSize(280, 10)
        self.open_folder_btn = QPushButton("Open Output Folder")
        self.open_folder_btn.setObjectName("Small")
        self.open_folder_btn.clicked.connect(self.open_output_folder)
        self.open_folder_btn.hide()
        row.addWidget(self.status_label, 1)
        row.addWidget(self.progress_info)
        row.addWidget(self.progress)
        row.addWidget(self.open_folder_btn)
        bar.addPermanentWidget(container, 1)

    # ========== STATE ==========
    def is_busy(self):
        return self.worker is not None

    def set_busy(self, busy):
        """Lock settings and file changes while a batch runs"""
        self.run_btn.setVisible(not busy)
        self.cancel_btn.setVisible(busy)
        self.cancel_btn.setEnabled(True)
        for widget in (self.browse_btn, self.optimize_mode_btn, self.rename_mode_btn,
                       self.settings_panel, self.remove_btn):
            widget.setEnabled(not busy)
        if not busy:
            self.update_files_view()

    def update_status(self, status, current=0, total=0, state="ready"):
        """Status text and progress bar; state colors it: ready orange, processing red, done green"""
        self.status_label.setText(status)
        if total > 0:
            self.progress_info.setText(f"{current}/{total} ({current / total * 100:.1f}%)")
            self.progress.setRange(0, total)
            self.progress.setValue(current)
        else:
            self.progress_info.setText("")
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
        self.progress.setProperty("state", state)
        repolish(self.progress)

    def reset_settings(self):
        """Restore all controls to their defaults"""
        defaults = core.OptimizeSettings()
        self.format_buttons[defaults.output_format].setChecked(True)
        (self.lossless_rb if defaults.lossless else self.lossy_rb).setChecked(True)
        self.quality_slider.setValue(defaults.quality)
        self.size_combo.setCurrentText(core.DEFAULT_SIZE_PRESET)
        self.on_size_preset_select(core.DEFAULT_SIZE_PRESET)
        self.progressive_cb.setChecked(defaults.progressive)
        self.lqip_cb.setChecked(defaults.lqip)
        self.strip_metadata_cb.setChecked(defaults.strip_metadata)
        self.hashed_names_cb.setChecked(defaults.hashed_names)
        self.on_comp_mode_change()

        rename_defaults = core.RenameOptions()
        self.pattern_combo.setCurrentText(rename_defaults.pattern)
        self.prefix_edit.setText(rename_defaults.prefix)
        self.suffix_edit.setText(rename_defaults.suffix)
        self.include_date_cb.setChecked(rename_defaults.include_date)
        self.include_time_cb.setChecked(rename_defaults.include_time)
        self.on_rename_options_changed()

    def set_mode(self, mode):
        """Switch between image optimizing and file renaming"""
        self.mode = mode
        is_optimize = mode == "optimize"
        self.optimize_mode_btn.setChecked(is_optimize)
        self.rename_mode_btn.setChecked(not is_optimize)
        self.optimize_page.setVisible(is_optimize)
        self.rename_page.setVisible(not is_optimize)
        self.preview_card.setVisible(is_optimize)
        self.table.setColumnHidden(NEW_NAME_COLUMN, is_optimize)
        self.browse_btn.setText("Add Images…" if is_optimize else "Add Files…")
        self.run_btn.setText("Optimize Images" if is_optimize else "Apply Rename")
        self.run_btn.setObjectName("Primary" if is_optimize else "Rename")
        repolish(self.run_btn)
        self.drop_hint.setText(("Drop images or folders here" if is_optimize else "Drop files or folders here")
                               + "\nor use the Add button")

        # Only images can be optimized
        if is_optimize:
            rows = [i for i, path in enumerate(self.model.paths) if not core.is_image_file(path)]
            if rows:
                self.model.remove_rows(rows)
        self.model.refresh_new_names()
        self.update_files_view()
        if is_optimize:
            self.on_current_row_changed()
        self.update_status("Ready")

    def update_files_view(self):
        """Show the drop hint or the table, and keep counts in sync"""
        count = self.model.rowCount()
        self.files_stack.setCurrentIndex(1 if count else 0)
        self.files_count.setText(plural(count, "file") if count else "")
        self.remove_btn.setEnabled(bool(count) and not self.is_busy())
        if not count:
            self.preview_path = None
            self.preview_info.setText("")
            self.preview.set_message("Add images to see a preview")
            self.output_size_label.setText("")

    # ========== FILES ==========
    def browse_files(self):
        if self.is_busy():
            return
        start_dir = self.settings_store.value("last_input_dir", "")
        if self.mode == "optimize":
            patterns = " ".join("*" + ext for ext in core.IMAGE_EXTENSIONS)
            files, _ = QFileDialog.getOpenFileNames(self, "Select Images", start_dir,
                                                    f"Image files ({patterns});;All files (*.*)")
        else:
            files, _ = QFileDialog.getOpenFileNames(self, "Select Files", start_dir, "All files (*.*)")
        if files:
            self.settings_store.setValue("last_input_dir", os.path.dirname(files[0]))
            self.add_files(files)

    def add_files(self, paths, done_status="Ready"):
        """Add files to the list; metadata is read in the background"""
        if self.mode == "optimize":
            paths = [p for p in paths if core.is_image_file(p)]
        if not paths:
            self.update_status("No valid files found")
            return

        known = {core.path_key(p) for p in self.model.paths} | self.pending_keys
        new_paths = []
        for path in paths:
            path = os.path.normpath(path)
            key = core.path_key(path)
            if key not in known:
                known.add(key)
                new_paths.append(path)
        if not new_paths:
            self.update_status("Those files are already in the list")
            return

        self.pending_keys.update(core.path_key(p) for p in new_paths)
        self.load_done_status = done_status
        loader = MetadataLoader(self.load_generation, new_paths)
        loader.signals.loaded.connect(self.on_metadata_loaded)
        loader.signals.finished.connect(self.on_metadata_finished)
        self.start_job(loader)
        self.update_status(f"Reading {plural(len(new_paths), 'file')}…")

    def start_job(self, job):
        self.jobs[job.signals] = job
        self.pool.start(job)

    def on_metadata_loaded(self, generation, rows):
        if generation != self.load_generation:
            return
        for path, _ in rows:
            self.pending_keys.discard(core.path_key(path))
        # The mode may have changed to optimize while non-image files were loading
        rows = [(p, m) for p, m in rows if self.mode == "rename" or core.is_image_file(p)]
        was_empty = self.model.rowCount() == 0
        self.model.add_rows(rows)
        self.update_files_view()
        if was_empty and self.model.rowCount():
            self.table.setCurrentIndex(self.model.index(0, 0))

    def on_metadata_finished(self, generation):
        self.jobs.pop(self.sender(), None)
        if generation == self.load_generation and not self.pending_keys and not self.is_busy():
            self.update_status(self.load_done_status)

    def remove_selected(self):
        """Remove selected rows from the list (files on disk are not touched)"""
        if self.is_busy():
            return
        rows = [index.row() for index in self.table.selectionModel().selectedRows()]
        if rows:
            self.model.remove_rows(rows)
            self.model.refresh_new_names()
            self.update_files_view()
            self.update_status(f"Removed {plural(len(rows), 'file')} from the list")

    def current_row(self):
        row = self.table.currentIndex().row()
        return row if 0 <= row < len(self.model.paths) else None

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.is_busy():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() and not self.is_busy():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """Add dropped files, and the files directly inside dropped folders"""
        paths = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if os.path.isdir(local):
                paths.extend(os.path.join(local, name) for name in sorted(os.listdir(local))
                             if os.path.isfile(os.path.join(local, name)))
            elif os.path.isfile(local):
                paths.append(local)
        if paths:
            self.add_files(paths)
        event.acceptProposedAction()

    # ========== PREVIEW ==========
    def on_current_row_changed(self, *args):
        """Update the preview and output size for the selected image"""
        row = self.current_row()
        if row is None or self.mode != "optimize":
            return
        path = self.model.paths[row]
        meta = self.model.metadata[row]
        self.preview_path = path
        self.preview_info.setText(f"{meta['filename']}   ·   {meta['dimensions']}   ·   {meta['size']}")
        self.update_output_size()
        cached = self.preview_cache.get(path)
        if cached is not None:
            self.preview.set_image(QPixmap.fromImage(cached))
        else:
            self.preview.set_message("Loading preview…")
            self.preview_timer.start()

    def load_current_preview(self):
        if self.preview_path and self.preview_path not in self.preview_cache:
            loader = PreviewLoader(self.preview_path)
            loader.signals.ready.connect(self.on_preview_ready)
            self.start_job(loader)

    def on_preview_ready(self, path, image):
        self.jobs.pop(self.sender(), None)
        if not image.isNull():
            self.preview_cache[path] = image
            while len(self.preview_cache) > PREVIEW_CACHE_SIZE:
                self.preview_cache.pop(next(iter(self.preview_cache)))
        if path != self.preview_path:
            return
        if image.isNull():
            self.preview.set_message("Preview not available")
        else:
            self.preview.set_image(QPixmap.fromImage(image))

    # ========== IMAGE OPTIMIZATION ==========
    def on_comp_mode_change(self):
        """Quality only applies to lossy compression, so disable the slider otherwise"""
        lossy = self.lossy_rb.isChecked()
        for widget in (self.quality_slider, self.quality_title, self.quality_value):
            widget.setEnabled(lossy)
        if lossy:
            self.comp_hint.setText("Smaller files. 75–85% suits most photos.")
        else:
            self.comp_hint.setText("Exact pixels, much larger files. WebP and PNG are truly lossless; "
                                   "JPEG and AVIF use their highest quality.")

    def on_size_preset_select(self, choice):
        width = core.SIZE_PRESETS.get(choice)
        custom = width is None
        self.width_edit.setEnabled(custom)
        self.width_edit.setText("" if custom else str(width))
        if custom:
            self.width_edit.setFocus()
        self.update_output_size()

    def requested_width(self):
        text = self.width_edit.text().strip()
        return int(text) if text.isdigit() and int(text) > 0 else None

    def update_output_size(self):
        """Show the output size of the selected image (height follows its aspect ratio)"""
        row = self.current_row()
        if row is None or self.mode != "optimize":
            self.output_size_label.setText("")
            return
        try:
            width, height = core.output_dimensions(self.model.paths[row], self.requested_width())
            self.output_size_label.setText(f"Selected image → {width} × {height} px")
        except Exception as e:
            self.output_size_label.setText("")
            logging.error(f"Error calculating output size: {str(e)}")

    def current_format(self):
        return next(fmt for fmt, button in self.format_buttons.items() if button.isChecked())

    def run_action(self):
        if self.mode == "optimize":
            self.start_processing()
        else:
            self.apply_rename()

    def start_processing(self):
        """Start image optimization on a worker thread"""
        if self.is_busy():
            return
        if not self.model.paths:
            self.update_status("No images to process")
            return
        if self.pending_keys:
            self.update_status("Still reading files, try again in a moment")
            return
        if self.width_edit.text().strip() and self.requested_width() is None:
            self.update_status("Invalid width")
            return

        start_dir = self.settings_store.value("last_output_dir", "")
        output_dir = QFileDialog.getExistingDirectory(self, "Select Output Directory", start_dir)
        if not output_dir:
            return
        self.settings_store.setValue("last_output_dir", output_dir)

        # Snapshot the controls; the worker never touches widgets
        settings = core.OptimizeSettings(
            images=list(self.model.paths),
            output_dir=output_dir,
            output_format=self.current_format(),
            lossless=self.lossless_rb.isChecked(),
            quality=self.quality_slider.value(),
            width=self.requested_width(),
            progressive=self.progressive_cb.isChecked(),
            lqip=self.lqip_cb.isChecked(),
            strip_metadata=self.strip_metadata_cb.isChecked(),
            hashed_names=self.hashed_names_cb.isChecked(),
        )
        self.open_folder_btn.hide()
        self.worker = OptimizeWorker(settings)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(self.on_batch_done)
        self.set_busy(True)
        self.update_status("Processing…", 0, len(settings.images), "processing")
        self.worker.start()

    def on_progress(self, done, total, name):
        if self.worker and not self.worker.silent:
            status = f"Processing {name}…" if name else "Writing report…"
            self.update_status(status, done, total, "processing")

    def on_batch_done(self, total, written, errors, cancelled, output_dir):
        worker = self.worker
        self.worker = None
        worker.wait()
        self.set_busy(False)
        if worker.silent:
            self.update_status("Ready")
            return
        if cancelled:
            self.update_status(f"Cancelled after {self.progress.value()} of {total} images")
            return
        status = f"Done: {plural(written, 'file')} saved"
        if errors:
            status += f", {errors} failed (see image_optimizer.log)"
        self.update_status(status, total, total, "done")
        self.last_output_dir = output_dir
        self.open_folder_btn.show()

    def cancel_processing(self):
        if self.worker:
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.update_status("Stopping after the current image…", self.progress.value(),
                               self.progress.maximum(), "processing")

    def open_output_folder(self):
        if self.last_output_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_output_dir))

    # ========== FILE RENAMING ==========
    def rename_options(self):
        return core.RenameOptions(
            pattern=self.pattern_combo.currentText(),
            prefix=self.prefix_edit.text(),
            suffix=self.suffix_edit.text(),
            include_date=self.include_date_cb.isChecked(),
            include_time=self.include_time_cb.isChecked(),
        )

    def preview_new_name(self, path, index):
        return core.generate_new_filename(path, index, self.rename_options())

    def on_rename_options_changed(self, *args):
        self.pattern_hint.setText(RENAME_HINTS.get(self.pattern_combo.currentText(), ""))
        self.model.refresh_new_names()

    def apply_rename(self):
        """Rename every listed file on disk using the selected pattern"""
        if not self.model.paths:
            self.update_status("No files to rename")
            return
        if self.pending_keys:
            self.update_status("Still reading files, try again in a moment")
            return
        count = len(self.model.paths)
        answer = QMessageBox.question(
            self, "Apply Rename",
            f"Rename {plural(count, 'file')} on disk using \"{self.pattern_combo.currentText()}\"?")
        if answer != QMessageBox.StandardButton.Yes:
            return

        result = core.rename_files(self.model.paths, self.rename_options())
        if result.error:
            status = f"Error renaming files: {result.error}"
        else:
            status = f"Renamed {plural(result.renamed, 'file')} successfully"

        # Reload the list so names and metadata reflect the files on disk
        self.load_generation += 1
        self.pending_keys.clear()
        self.model.clear()
        self.update_files_view()
        self.add_files(result.paths, done_status=status)

    # ========== RESET ==========
    def reset_application(self):
        """Clear the list and restore all settings"""
        if self.worker:
            # The batch stops after its current image; its result is discarded
            self.worker.silent = True
            self.worker.cancel()
        self.load_generation += 1
        self.pending_keys.clear()
        self.model.clear()
        self.preview_cache.clear()
        self.open_folder_btn.hide()
        self.reset_settings()
        self.set_mode("optimize")
        if self.worker:
            self.cancel_btn.setEnabled(False)
            self.update_status("Stopping…")

    def closeEvent(self, event):
        if self.worker:
            self.worker.cancel()
            self.worker.wait()
        self.pool.waitForDone(5000)
        super().closeEvent(event)
