"""Tests that drive the main window headlessly (QT_QPA_PLATFORM=offscreen)."""
import logging
import os
import time
import types

import pytest
from conftest import noisy_image
from PIL import Image
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl, qInstallMessageHandler
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from optimizer import main_window
from optimizer.app import create_app
from optimizer.widgets import NEW_NAME_COLUMN

qt_warnings = []


@pytest.fixture(scope="session")
def qapp():
    # The headless platform has no system fonts; ignore its font-directory notice
    qInstallMessageHandler(
        lambda mode, context, message: None if "Cannot find font directory" in message else qt_warnings.append(message))
    return QApplication.instance() or create_app([])


def pump(app, condition, timeout=120):
    """Process events until condition() is true"""
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting for the window"
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


@pytest.fixture
def output_dir(tmp_path):
    path = tmp_path / "out"
    path.mkdir()
    return path


@pytest.fixture
def window(qapp, tmp_path, output_dir, monkeypatch, caplog):
    """Main window with the folder picker returning output_dir and confirmations answered Yes"""
    monkeypatch.setattr(main_window, "QFileDialog", types.SimpleNamespace(
        getExistingDirectory=lambda *args, **kwargs: str(output_dir),
        getOpenFileNames=lambda *args, **kwargs: ([], "")))

    class AlwaysYes:
        StandardButton = QMessageBox.StandardButton
        question = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(main_window, "QMessageBox", AlwaysYes)

    qt_warnings.clear()
    win = main_window.MainWindow(str(tmp_path / "settings.ini"))
    win.show()
    yield win
    win.close()
    assert not qt_warnings
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


def add_and_wait(app, win, paths):
    win.add_files([str(p) for p in paths])
    pump(app, lambda: not win.pending_keys and not win.jobs)


def new_names(win):
    return [win.model.data(win.model.index(row, NEW_NAME_COLUMN)) for row in range(win.model.rowCount())]


def test_initial_state(window):
    assert window.mode == "optimize" and window.optimize_mode_btn.isChecked()
    assert window.run_btn.text() == "Optimize Images"
    assert window.lossy_rb.isChecked() and window.quality_slider.value() == 80
    assert window.quality_value.text() == "80%" and window.quality_slider.isEnabled()
    assert window.format_buttons["webp"].isChecked()
    assert window.size_combo.currentText() == "Full HD (1920px)"
    assert window.width_edit.text() == "1920" and not window.width_edit.isEnabled()
    assert window.files_stack.currentIndex() == 0 and "Drop images" in window.drop_hint.text()
    assert window.table.isColumnHidden(NEW_NAME_COLUMN)
    assert window.status_label.text() == "Ready"


def test_add_files_filters_previews_and_sizes(qapp, window, photos):
    (photos / "notes.txt").write_text("not an image")
    add_and_wait(qapp, window, [photos / "landscape.jpg", photos / "portrait.jpg",
                                photos / "small.jpg", photos / "notes.txt"])

    assert window.model.rowCount() == 3 and window.files_count.text() == "3 files"
    assert window.files_stack.currentIndex() == 1
    pump(qapp, window.preview.has_image)
    assert "landscape.jpg" in window.preview_info.text()
    assert "1920 × 1280" in window.output_size_label.text()

    window.table.setCurrentIndex(window.model.index(1, 0))
    pump(qapp, lambda: window.preview.has_image() and window.preview_path.endswith("portrait.jpg"))
    assert window.preview.image_size() == (800, 1200)  # Upright from EXIF
    assert "1600 × 2400" in window.output_size_label.text()  # Narrower than 1920, so not enlarged

    window.add_files([str(photos / "landscape.jpg")])
    assert window.model.rowCount() == 3 and "already" in window.status_label.text()


def test_size_and_compression_controls(qapp, window, photos):
    add_and_wait(qapp, window, [photos / "landscape.jpg"])
    window.size_combo.setCurrentText("Custom...")
    assert window.width_edit.isEnabled() and window.width_edit.text() == ""
    assert "2400 × 1600" in window.output_size_label.text()
    window.width_edit.setText("640")
    assert "640 × 427" in window.output_size_label.text()

    window.lossless_rb.setChecked(True)
    assert not window.quality_slider.isEnabled() and "lossless" in window.comp_hint.text().lower()


def test_dropping_a_folder_adds_its_images(qapp, window, tmp_path):
    folder = tmp_path / "dropped"
    folder.mkdir()
    noisy_image(64, 48).save(folder / "a.png")
    noisy_image(64, 48).save(folder / "b.jpg")
    (folder / "readme.txt").write_text("x")

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(folder))])
    window.dropEvent(QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    pump(qapp, lambda: not window.pending_keys and not window.jobs)
    assert sorted(m["filename"] for m in window.model.metadata) == ["a.png", "b.jpg"]


def test_optimize_batch(qapp, window, photos, output_dir):
    add_and_wait(qapp, window, [photos / "landscape.jpg", photos / "portrait.jpg", photos / "small.jpg"])
    window.run_btn.click()

    assert window.is_busy() and window.cancel_btn.isVisible() and not window.run_btn.isVisible()
    assert not window.browse_btn.isEnabled() and not window.settings_panel.isEnabled()
    pump(qapp, lambda: not window.is_busy())

    assert window.status_label.text() == "Done: 3 files saved"
    assert window.progress.property("state") == "done" and window.open_folder_btn.isVisible()
    assert sorted(os.listdir(output_dir)) == ["landscape.webp", "optimization_report.json", "portrait.webp",
                                             "report.html", "small.webp"]
    with Image.open(output_dir / "landscape.webp") as img:
        assert img.size == (1920, 1280)
    with Image.open(output_dir / "portrait.webp") as img:
        assert img.size == (1600, 2400)  # Upright, and narrower than 1920 so not enlarged
    assert window.run_btn.isVisible() and window.browse_btn.isEnabled() and window.settings_panel.isEnabled()


def many_photos(folder, count=8):
    folder.mkdir()
    paths = [folder / f"many_{i}.jpg" for i in range(count)]
    for i, path in enumerate(paths):
        noisy_image(2000, 1300, i).save(path, quality=90)
    return paths


def test_cancel_stops_after_current_image(qapp, window, tmp_path, output_dir):
    add_and_wait(qapp, window, many_photos(tmp_path / "many"))
    window.run_btn.click()
    pump(qapp, lambda: window.progress.value() >= 1)
    window.cancel_processing()
    assert "Stopping" in window.status_label.text() and not window.cancel_btn.isEnabled()

    pump(qapp, lambda: not window.is_busy())
    assert window.status_label.text().startswith("Cancelled after")
    assert len(os.listdir(output_dir)) < 8


def test_reset_while_running(qapp, window, tmp_path, output_dir):
    add_and_wait(qapp, window, many_photos(tmp_path / "many"))
    window.quality_slider.setValue(50)
    window.run_btn.click()
    window.reset_application()
    assert window.status_label.text() == "Stopping…" and window.model.rowCount() == 0

    pump(qapp, lambda: not window.is_busy())
    assert window.status_label.text() == "Ready" and window.quality_slider.value() == 80
    assert window.files_stack.currentIndex() == 0
    assert not (output_dir / "report.html").exists()


def test_rename_flow(qapp, window, tmp_path):
    folder = tmp_path / "rename"
    folder.mkdir()
    (folder / "a.txt").write_text("a")
    (folder / "b.txt").write_text("b")
    noisy_image(30, 20).save(folder / "Case.JPG")

    window.rename_mode_btn.click()
    assert window.run_btn.text() == "Apply Rename" and not window.preview_card.isVisible()
    assert not window.table.isColumnHidden(NEW_NAME_COLUMN)

    add_and_wait(qapp, window, [folder / "a.txt", folder / "b.txt", folder / "Case.JPG"])
    assert new_names(window) == ["image_1.txt", "image_2.txt", "image_3.jpg"]
    window.pattern_combo.setCurrentText("Add Prefix/Suffix")
    window.prefix_edit.setText("x_")
    assert new_names(window) == ["x_a.txt", "x_b.txt", "x_Case.jpg"]
    assert "prefix" in window.pattern_hint.text()

    window.run_btn.click()
    pump(qapp, lambda: not window.pending_keys and not window.jobs)
    assert sorted(os.listdir(folder)) == ["x_Case.jpg", "x_a.txt", "x_b.txt"]
    assert window.status_label.text() == "Renamed 3 files successfully"
    assert [m["filename"] for m in window.model.metadata] == ["x_a.txt", "x_b.txt", "x_Case.jpg"]

    # Back in optimize mode only the image stays, and it can be removed from the list
    window.optimize_mode_btn.click()
    assert [m["filename"] for m in window.model.metadata] == ["x_Case.jpg"]
    window.table.selectRow(0)
    window.remove_selected()
    assert window.model.rowCount() == 0 and window.files_stack.currentIndex() == 0
