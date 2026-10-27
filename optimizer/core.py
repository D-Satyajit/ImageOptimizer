"""Image optimization and bulk renaming, with no UI code.

Everything here can run on a worker thread and is covered by tests/test_core.py.
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import math
import os
from dataclasses import dataclass, field
from collections.abc import Callable
from datetime import datetime
from typing import NamedTuple

from PIL import Image, ImageFilter, ImageOps

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp')

OUTPUT_FORMATS = ("JPEG", "PNG", "WebP", "AVIF")

# Output width for each preset; None means the width is typed in
SIZE_PRESETS = {
    "Mobile (480px)": 480,
    "Tablet (768px)": 768,
    "Desktop (1080px)": 1080,
    "Full HD (1920px)": 1920,
    "2K (2560px)": 2560,
    "4K (3840px)": 3840,
    "Custom...": None,
}
DEFAULT_SIZE_PRESET = "Full HD (1920px)"

RENAME_PATTERNS = (
    "Sequential Numbering",
    "Alphanumeric Pattern",
    "Add Prefix/Suffix",
    "Date and Time",
    "Custom Pattern",
)

EXIF_ORIENTATION = 274
EXIF_ARTIST = 315
EXIF_MODEL = 272
EXIF_DATE_TAKEN = 36867
EXIF_IFD = 0x8769

# JPEG stores EXIF in a single segment of at most 64 KB
MAX_JPEG_EXIF_BYTES = 65533


@dataclass
class OptimizeSettings:
    """Settings for one optimization batch; the defaults are the app's defaults"""
    images: list[str] = field(default_factory=list)
    output_dir: str = ""
    output_format: str = "webp"   # jpeg, png, webp or avif
    lossless: bool = False
    quality: int = 80             # 10-100, used for lossy output
    width: int | None = SIZE_PRESETS[DEFAULT_SIZE_PRESET]  # None keeps the original size
    progressive: bool = True      # JPEG only
    lqip: bool = False            # Also save a tiny blurred placeholder
    strip_metadata: bool = False  # Remove EXIF/GPS (the color profile is always kept)
    hashed_names: bool = False    # Name outputs by content hash


@dataclass
class RenameOptions:
    pattern: str = "Sequential Numbering"
    prefix: str = ""
    suffix: str = ""
    include_date: bool = True
    include_time: bool = True


class RenameResult(NamedTuple):
    paths: list[str]   # Every file's path after renaming (unchanged where skipped)
    renamed: int
    error: str | None  # Set if renaming stopped early


class BatchResult(NamedTuple):
    report: list[dict]  # One row per written file
    errors: int
    cancelled: bool


def is_image_file(file_path: str) -> bool:
    """Check if a file is an image based on its extension"""
    return os.path.splitext(file_path)[1].lower() in IMAGE_EXTENSIONS


def path_key(path: str) -> str:
    """Normalized path for comparisons (Windows paths are case-insensitive)"""
    return os.path.normcase(os.path.abspath(path))


def format_size(size: int) -> str:
    """Convert bytes to human-readable format"""
    if size == 0:
        return "0B"
    # Savings are negative when the output is larger than the original
    sign = "-" if size < 0 else ""
    size = abs(size)
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = min(int(math.floor(math.log(size, 1024))), len(size_name) - 1)
    s = round(size / math.pow(1024, i), 2)
    return f"{sign}{s} {size_name[i]}"


def exif_text(value) -> str:
    """EXIF text for display; cameras often pad empty fields with NUL bytes or spaces"""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    text = str(value).strip("\x00 \t\r\n") if value is not None else ""
    return text or "N/A"


def extract_metadata(file_path: str) -> dict:
    """
    Metadata shown in the file list. Images get Author, Date Taken, Dimensions,
    Resolution and Camera Model; other files get "N/A" for those.
    """
    metadata = {
        "filename": os.path.basename(file_path),
        "author": "N/A",
        "size": "N/A",
        "file_type": "N/A",
        "extension": "N/A",
        "date": "N/A",
        "date_taken": "N/A",
        "dimensions": "N/A",
        "resolution": "N/A",
        "camera": "N/A",
    }
    try:
        metadata["size"] = format_size(os.path.getsize(file_path))
        metadata["extension"] = os.path.splitext(file_path)[1][1:].upper()
        metadata["date"] = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y-%m-%d %H:%M")
        metadata["file_type"] = "Other"

        if is_image_file(file_path):
            metadata["file_type"] = "Image"
            with Image.open(file_path) as img:
                metadata["dimensions"] = f"{img.width}×{img.height}"
                dpi = img.info.get('dpi', (0, 0))
                if dpi[0] > 0:
                    # Camera JPEGs store DPI as IFDRational, which has no number formatting
                    metadata["resolution"] = f"{float(dpi[0]):g}×{float(dpi[1]):g} DPI"

                # Read EXIF while the file is open (TIFF reads sub-IFDs from it)
                exif = img.getexif()
                if exif:
                    metadata["author"] = exif_text(exif.get(EXIF_ARTIST))
                    metadata["camera"] = exif_text(exif.get(EXIF_MODEL))
                    # DateTimeOriginal lives in the Exif sub-IFD, not IFD0
                    metadata["date_taken"] = exif_text(exif.get_ifd(EXIF_IFD).get(EXIF_DATE_TAKEN))
    except Exception as e:
        logging.error(f"Error extracting metadata from {file_path}: {str(e)}")
    return metadata


def output_dimensions(img_path: str, width: int | None) -> tuple[int, int]:
    """Size an image will have after optimizing to the given width (None keeps its size)"""
    with Image.open(img_path) as img:
        orig_width, orig_height = img.size
        # EXIF rotation is applied before resizing, so swap for rotated photos
        if img.getexif().get(EXIF_ORIENTATION) in (5, 6, 7, 8):
            orig_width, orig_height = orig_height, orig_width

    # Images are never upscaled
    if not width or width >= orig_width:
        return orig_width, orig_height
    return width, max(1, round(orig_height * width / orig_width))


def load_preview(img_path: str, max_size: int) -> Image.Image:
    """Decode a small, upright RGBA preview quickly"""
    with Image.open(img_path) as img:
        # JPEG only: decode at the smallest scale that still covers the preview size,
        # which skips most of the work for large photos
        ratio = min(max_size / img.width, max_size / img.height, 1)
        img.draft(None, (max(1, int(img.width * ratio)), max(1, int(img.height * ratio))))
        img.thumbnail((max_size, max_size))
        # Rotate the small image rather than the full-size one
        img = ImageOps.exif_transpose(img)
        return img.convert("RGBA")


# ========== FILE RENAMING ==========
def generate_new_filename(path: str, index: int, options: RenameOptions,
                          now: datetime | None = None) -> str:
    """New filename (with lowercased extension) for the file at `index` in the list"""
    name, ext = os.path.splitext(os.path.basename(path))
    ext = ext.lower()
    now = now or datetime.now()
    date_str = now.strftime("%Y-%m-%d") if options.include_date else ""
    time_str = now.strftime("%H-%M") if options.include_time else ""
    pattern = options.pattern

    if pattern == "Sequential Numbering":
        return f"image_{index + 1}{ext}"

    if pattern == "Alphanumeric Pattern":
        # img_A1 ... img_A10, img_B1 ... img_Z10, img_AA1, etc.
        letters = ""
        group = index // 10
        while group >= 0:
            letters = chr(65 + group % 26) + letters
            group = group // 26 - 1
        return f"img_{letters}{index % 10 + 1}{ext}"

    if pattern == "Add Prefix/Suffix":
        return f"{options.prefix}{name}{options.suffix}{ext}"

    if pattern == "Date and Time":
        dt_str = "_".join(part for part in (date_str, time_str) if part)
        return f"FILE_{dt_str}_{index + 1}{ext}"

    if pattern == "Custom Pattern":
        # prefix_index_suffix, where prefix/suffix may use {name}, {date}, {time} placeholders
        custom = f"{options.prefix}_{{index}}_{options.suffix}"
        for placeholder, value in (("{prefix}", options.prefix), ("{suffix}", options.suffix),
                                   ("{index}", str(index + 1)), ("{date}", date_str),
                                   ("{time}", time_str), ("{name}", name)):
            custom = custom.replace(placeholder, value)
        return f"{custom}{ext}"

    return os.path.basename(path)


def rename_files(paths: list[str], options: RenameOptions) -> RenameResult:
    """Rename files on disk; stops at the first error"""
    new_paths = list(paths)
    renamed = 0
    now = datetime.now()  # One timestamp so every file gets the same date/time

    try:
        for i, path in enumerate(paths):
            new_name = generate_new_filename(path, i, options, now)
            if os.path.basename(path) == new_name:
                continue

            # Avoid existing names (a case-only rename on Windows matches the file itself)
            base_new_path = new_path = os.path.join(os.path.dirname(path), new_name)
            counter = 1
            while os.path.exists(new_path) and path_key(new_path) != path_key(path):
                stem, ext = os.path.splitext(base_new_path)
                new_path = f"{stem}_{counter}{ext}"
                counter += 1

            os.rename(path, new_path)
            new_paths[i] = new_path
            renamed += 1
    except Exception as e:
        logging.error(f"Error renaming files: {str(e)}")
        return RenameResult(new_paths, renamed, str(e))

    return RenameResult(new_paths, renamed, None)


# ========== IMAGE OPTIMIZATION ==========
def resize_image(img: Image.Image, width: int | None = None, height: int | None = None) -> Image.Image:
    """Resize image while maintaining aspect ratio (never upscales)"""
    orig_width, orig_height = img.size
    if width and height:
        ratio = min(width / orig_width, height / orig_height)
    elif width:
        ratio = width / orig_width
    elif height:
        ratio = height / orig_height
    else:
        return img

    # Upscaling only adds file size, not detail
    if ratio >= 1:
        return img

    new_size = (max(1, round(orig_width * ratio)), max(1, round(orig_height * ratio)))
    return img.resize(new_size, Image.LANCZOS)


def strip_metadata(img: Image.Image) -> Image.Image:
    """Remove EXIF/XMP metadata, keeping the color profile and transparency"""
    stripped_img = img.copy()
    stripped_img.info = {key: img.info[key] for key in ("icc_profile", "transparency") if key in img.info}
    return stripped_img


class BatchOptimizer:
    """Optimizes one batch of images with a fixed set of settings"""

    def __init__(self, settings: OptimizeSettings):
        self.settings = settings
        # Never overwrite a source image or another output from the same batch
        self.source_paths = {path_key(p) for p in settings.images}
        self.batch_outputs: set[str] = set()

    def run(self, progress: Callable[[int, int, str], None] | None = None,
            is_cancelled: Callable[[], bool] = lambda: False) -> BatchResult:
        """
        Process all images and write the reports. progress(done, total, current filename)
        is called before each image and once more at the end with an empty filename.
        """
        images = self.settings.images
        total = len(images)
        report = []
        errors = 0

        for i, img_path in enumerate(images):
            if is_cancelled():
                return BatchResult(report, errors, True)
            if progress:
                progress(i, total, os.path.basename(img_path))

            try:
                report.extend(report_row(version) for version in self.process_image(img_path))
            except Exception as e:
                errors += 1
                logging.error(f"Error processing {img_path}: {str(e)}")

        try:
            write_reports(report, self.settings.output_dir)
        except Exception as e:
            errors += 1
            logging.error(f"Error writing report: {str(e)}")

        if progress:
            progress(total, total, "")
        return BatchResult(report, errors, False)

    def process_image(self, img_path: str) -> list[dict]:
        """Optimize one image (plus its LQIP if enabled); returns the written versions"""
        original_size = os.path.getsize(img_path)

        # Closed straight away so the file isn't left locked
        with Image.open(img_path) as img:
            img = ImageOps.exif_transpose(img)
            if self.settings.strip_metadata:
                img = strip_metadata(img)

        # Height follows each image's own aspect ratio
        resized_img = resize_image(img, self.settings.width)
        versions = [self.save_optimized(resized_img, img_path, original_size)]

        if self.settings.lqip:
            lqip = resized_img.copy()
            lqip.thumbnail((20, 20))
            lqip = lqip.filter(ImageFilter.GaussianBlur(radius=2))
            versions.append(self.save_optimized(lqip, img_path, original_size, suffix="_lqip"))

        return versions

    def get_unique_output_path(self, output_path: str) -> str:
        """Never overwrite a source image or another output from the same batch"""
        base, ext = os.path.splitext(output_path)
        counter = 1
        while path_key(output_path) in self.source_paths or path_key(output_path) in self.batch_outputs:
            output_path = f"{base}_{counter}{ext}"
            counter += 1
        self.batch_outputs.add(path_key(output_path))
        return output_path

    def save_options(self, img: Image.Image, output_format: str) -> dict:
        """Encoder options for the output format, including metadata to keep"""
        settings = self.settings
        lossless = settings.lossless
        options = {}
        if output_format == "JPEG":
            # JPEG has no lossless mode, so use its highest quality instead
            options["quality"] = 100 if lossless else settings.quality
            if lossless:
                options["subsampling"] = 0
            options["progressive"] = settings.progressive
        elif output_format == "PNG":
            options["optimize"] = True
        elif output_format == "WEBP":
            options["lossless"] = lossless
            # For lossless WebP, quality is compression effort rather than image quality
            options["quality"] = 90 if lossless else settings.quality
            options["method"] = 6  # Slowest, smallest
        elif output_format == "AVIF":
            # AVIF has no true lossless mode here; use maximum quality without chroma subsampling
            options["quality"] = 100 if lossless else settings.quality
            if lossless:
                options["subsampling"] = "4:4:4"

        # Pillow drops metadata on save unless it is passed explicitly
        exif = img.getexif()
        if exif:
            exif_bytes = exif.tobytes()
            if output_format != "JPEG" or len(exif_bytes) <= MAX_JPEG_EXIF_BYTES:
                options["exif"] = exif_bytes
        if img.info.get("icc_profile"):
            options["icc_profile"] = img.info["icc_profile"]
        return options

    def save_optimized(self, img: Image.Image, img_path: str, original_size: int, suffix: str = "") -> dict:
        """Save one optimized version and describe it for the report"""
        output_format = self.settings.output_format.upper()
        if output_format == "JPEG":
            img = img.convert("RGB")

        if self.settings.hashed_names:
            stem = hashlib.md5(img.tobytes()).hexdigest()[:8]
        else:
            stem = os.path.splitext(os.path.basename(img_path))[0]
        file_name = f"{stem}{suffix}.{output_format.lower()}"
        output_path = self.get_unique_output_path(os.path.join(self.settings.output_dir, file_name))

        img.save(output_path, format=output_format, **self.save_options(img, output_format))

        return {
            "path": output_path,
            "size": os.path.getsize(output_path),
            "original_size": original_size,
            "dimensions": img.size,
        }


def report_row(version: dict) -> dict:
    """Report entry for one written file"""
    original_size = version["original_size"]
    savings = original_size - version["size"]
    ratio = (savings / original_size) * 100 if original_size else 0
    return {
        "file": os.path.basename(version["path"]),
        "original_size": format_size(original_size),
        "new_size": format_size(version["size"]),
        "savings": format_size(savings),
        "ratio": f"{ratio:.1f}%",
        "dimensions": version["dimensions"],
    }


REPORT_HTML = """<html><head><meta charset="utf-8"><style>
body {{ font-family: Arial, sans-serif; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
tr:nth-child(even) {{ background-color: #f2f2f2; }}
th {{ background-color: #4CAF50; color: white; }}
</style></head><body>
<h1>Image Optimization Report</h1>
<table>
<tr><th>File</th><th>Original</th><th>Optimized</th><th>Savings</th><th>Ratio</th><th>Dimensions</th></tr>
{rows}
</table></body></html>
"""


def write_reports(report: list[dict], output_dir: str) -> None:
    """Write optimization_report.json and report.html to the output folder"""
    with open(os.path.join(output_dir, "optimization_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    rows = "\n".join(
        f"<tr><td>{html.escape(item['file'])}</td><td>{item['original_size']}</td>"
        f"<td>{item['new_size']}</td><td>{item['savings']}</td><td>{item['ratio']}</td>"
        f"<td>{item['dimensions'][0]}x{item['dimensions'][1]}</td></tr>"
        for item in report
    )
    with open(os.path.join(output_dir, "report.html"), "w", encoding="utf-8") as f:
        f.write(REPORT_HTML.format(rows=rows))
