"""Tests for optimizer.core: metadata, resizing, saving, reports and renaming."""
import hashlib
import json
import os
from datetime import datetime

import pytest
from conftest import DATE_TAKEN, SRGB_PROFILE, noisy_image, sample_photos
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from optimizer import core

WIDTH = 1200  # Smaller than the defaults to keep the tests quick


def batch(photos, names, **overrides):
    settings = core.OptimizeSettings(images=[str(photos / n) for n in names], output_dir=str(photos), width=WIDTH)
    for key, value in overrides.items():
        setattr(settings, key, value)
    return core.BatchOptimizer(settings)


def image_size(path):
    with Image.open(path) as img:
        return img.size


def read_exif(path):
    with Image.open(path) as img:
        exif = img.getexif()
        return dict(exif), exif.get_ifd(0x8769).get(36867), img.info.get("icc_profile")


# ========== METADATA AND SIZING ==========
def test_metadata_reads_exif_including_date_taken(photos):
    meta = core.extract_metadata(str(photos / "landscape.jpg"))
    assert meta["date_taken"] == DATE_TAKEN  # Stored in the Exif sub-IFD, not IFD0
    assert (meta["author"], meta["camera"], meta["dimensions"]) == ("Tester", "CamModel", "2400×1600")


def test_metadata_formats_camera_style_dpi(photos):
    exif = Image.Exif()
    exif[282] = exif[283] = IFDRational(300, 1)
    exif[296] = 2  # Inches
    noisy_image(200, 100).save(photos / "dpi.jpg", exif=exif)
    assert core.extract_metadata(str(photos / "dpi.jpg"))["resolution"] == "300×300 DPI"


def test_metadata_for_non_image_and_unreadable_files(photos):
    (photos / "notes.txt").write_text("hello")
    assert core.extract_metadata(str(photos / "notes.txt"))["file_type"] == "Other"
    assert core.extract_metadata(str(photos / "missing.jpg"))["size"] == "N/A"


def test_exif_text_strips_camera_padding():
    assert core.exif_text("\x00\x00 ") == "N/A"
    assert core.exif_text(b"Cam\x00") == "Cam"
    assert core.exif_text(None) == "N/A"


@pytest.mark.parametrize("name, width, expected", [
    ("landscape.jpg", WIDTH, (1200, 800)),
    ("portrait.jpg", WIDTH, (1200, 1800)),  # EXIF rotation applied first
    ("small.jpg", WIDTH, (600, 450)),       # Never upscaled
    ("landscape.jpg", None, (2400, 1600)),  # No width keeps the size
])
def test_output_dimensions(photos, name, width, expected):
    assert core.output_dimensions(str(photos / name), width) == expected


def test_preview_is_small_and_upright(photos):
    preview = core.load_preview(str(photos / "portrait.jpg"), 600)
    assert preview.size == (400, 600)
    assert preview.mode == "RGBA"


def test_format_size():
    assert core.format_size(0) == "0B"
    assert core.format_size(1536) == "1.5 KB"
    assert core.format_size(-1234) == "-1.21 KB"


def test_defaults_are_lossy_80_webp_full_hd():
    settings = core.OptimizeSettings()
    assert (settings.output_format, settings.lossless, settings.quality, settings.width) == ("webp", False, 80, 1920)


# ========== OPTIMIZATION ==========
def test_lossless_batch_into_source_folder(photos):
    names = ["landscape.jpg", "portrait.jpg", "small.jpg", "dup.jpg", "dup.png", "self.webp"]
    self_hash = hashlib.md5((photos / "self.webp").read_bytes()).hexdigest()
    calls = []

    result = batch(photos, names, lossless=True, lqip=True).run(lambda *args: calls.append(args))

    assert result.errors == 0 and not result.cancelled
    assert calls[0] == (0, 6, "landscape.jpg") and calls[-1] == (6, 6, "")
    assert image_size(photos / "landscape.webp") == (1200, 800)
    assert image_size(photos / "portrait.webp") == (1200, 1800)
    assert image_size(photos / "small.webp") == (600, 450)
    assert max(image_size(photos / "landscape_lqip.webp")) <= 20  # Placeholder is its own file
    assert (photos / "dup.webp").exists() and (photos / "dup_1.webp").exists()
    # A source that matches its output name is never overwritten
    assert hashlib.md5((photos / "self.webp").read_bytes()).hexdigest() == self_hash
    assert (photos / "self_1.webp").exists()
    assert b"VP8L" in (photos / "landscape.webp").read_bytes()  # Lossless WebP

    report = json.loads((photos / "optimization_report.json").read_text(encoding="utf-8"))
    assert len(report) == len(result.report) == 12
    small = next(row for row in report if row["file"] == "small.webp")
    assert small["savings"].startswith("-")  # Output grew; reported rather than crashing
    assert "landscape_lqip.webp" in (photos / "report.html").read_text(encoding="utf-8")


def test_metadata_kept_by_default(photos):
    batch(photos, ["landscape.jpg", "portrait.jpg"]).run()
    tags, date_taken, icc = read_exif(photos / "landscape.webp")
    assert tags.get(315) == "Tester" and date_taken == DATE_TAKEN
    assert icc == SRGB_PROFILE
    assert 274 not in read_exif(photos / "portrait.webp")[0]  # Orientation already applied


def test_strip_metadata_keeps_color_profile(photos, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    optimizer = batch(photos, ["landscape.jpg", "portrait.jpg"], output_dir=str(out),
                      output_format="jpeg", quality=70, strip_metadata=True)
    optimizer.run()
    tags, date_taken, icc = read_exif(out / "landscape.jpeg")
    assert not tags and date_taken is None
    assert icc == SRGB_PROFILE
    assert image_size(out / "portrait.jpeg") == (1200, 1800)


@pytest.mark.parametrize("output_format", ["png", "avif", "jpeg"])
def test_other_formats_at_custom_width(photos, tmp_path, output_format):
    result = batch(photos, ["landscape.jpg"], output_dir=str(tmp_path), output_format=output_format,
                   lossless=True, width=640).run()
    assert result.errors == 0
    assert image_size(tmp_path / f"landscape.{output_format}") == (640, 427)


def test_hashed_names(photos, tmp_path):
    batch(photos, ["small.jpg"], output_dir=str(tmp_path), hashed_names=True).run()
    outputs = [n for n in os.listdir(tmp_path) if n.endswith(".webp")]
    assert len(outputs) == 1 and len(outputs[0]) == len("01234567.webp")


def test_cancel_stops_early_without_report(photos, tmp_path):
    seen = []
    result = batch(photos, ["small.jpg"] * 5, output_dir=str(tmp_path)).run(
        lambda done, total, name: seen.append(done), lambda: len(seen) >= 2)
    assert result.cancelled and len(result.report) == 2
    assert not (tmp_path / "report.html").exists()


def test_unreadable_image_counts_as_error(photos, tmp_path):
    (photos / "broken.jpg").write_bytes(b"not an image")
    result = batch(photos, ["broken.jpg", "small.jpg"], output_dir=str(tmp_path)).run()
    assert result.errors == 1 and len(result.report) == 1


# ========== RENAMING ==========
NOW = datetime(2025, 7, 6, 14, 30)


@pytest.mark.parametrize("index, expected", [
    (0, "img_A1.jpg"), (9, "img_A10.jpg"), (10, "img_B1.jpg"), (259, "img_Z10.jpg"),
    (260, "img_AA1.jpg"), (280, "img_AC1.jpg"), (7019, "img_ZZ10.jpg"), (7020, "img_AAA1.jpg"),
])
def test_alphanumeric_names_stay_valid(index, expected):
    options = core.RenameOptions(pattern="Alphanumeric Pattern")
    assert core.generate_new_filename("x.JPG", index, options) == expected


@pytest.mark.parametrize("options, expected", [
    (core.RenameOptions(), "image_3.png"),
    (core.RenameOptions(pattern="Add Prefix/Suffix", prefix="a_", suffix="_z"), "a_pic_z.png"),
    (core.RenameOptions(pattern="Date and Time"), "FILE_2025-07-06_14-30_3.png"),
    (core.RenameOptions(pattern="Date and Time", include_time=False), "FILE_2025-07-06_3.png"),
    (core.RenameOptions(pattern="Custom Pattern", prefix="{name}", suffix="{date}"), "pic_3_2025-07-06.png"),
])
def test_rename_patterns(options, expected):
    assert core.generate_new_filename("folder/pic.PNG", 2, options, NOW) == expected


def test_rename_files_avoids_existing_names(tmp_path):
    for name in ("Case.JPG", "b.txt", "image_2.txt"):
        (tmp_path / name).write_text(name)

    # A case-only change renames in place instead of adding _1
    result = core.rename_files([str(tmp_path / "Case.JPG")], core.RenameOptions(pattern="Add Prefix/Suffix"))
    assert result.error is None and sorted(os.listdir(tmp_path)) == ["Case.jpg", "b.txt", "image_2.txt"]

    result = core.rename_files([str(tmp_path / "Case.jpg"), str(tmp_path / "b.txt")], core.RenameOptions())
    assert result.renamed == 2
    assert [os.path.basename(p) for p in result.paths] == ["image_1.jpg", "image_2_1.txt"]


def test_rename_reports_errors(tmp_path):
    result = core.rename_files([str(tmp_path / "missing.txt")], core.RenameOptions())
    assert result.error and result.renamed == 0


# ========== REAL PHOTOS (optional) ==========
@pytest.mark.skipif(not sample_photos(), reason="no photos in samples/")
@pytest.mark.parametrize("path", sample_photos())
def test_real_photo_metadata_and_preview(path):
    meta = core.extract_metadata(path)
    assert meta["file_type"] == "Image" and meta["size"] != "N/A" and meta["resolution"] != "N/A"
    assert "\x00" not in meta["author"]
    preview = core.load_preview(path, 1200)
    assert max(preview.size) == 1200
