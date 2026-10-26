"""Image optimization and bulk-renaming logic for Image Optimizer Pro.

Kept free of UI code so it can run on a worker thread and be tested on its own.
"""
import hashlib
import html
import json
import logging
import math
import os
from datetime import datetime

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

RENAME_PATTERNS = (
    "Sequential Numbering",
    "Alphanumeric Pattern",
    "Add Prefix/Suffix",
    "Date and Time",
    "Custom Pattern",
)

DEFAULT_SETTINGS = {
    "format": "webp",
    "comp_mode": "lossy",
    "quality": 80,
    "size_preset": "Full HD (1920px)",
    "progressive": True,
    "lqip": False,
    "strip_meta": False,
    "hash_names": False,
}

DEFAULT_RENAME_OPTIONS = {
    "pattern": "Sequential Numbering",
    "prefix": "",
    "suffix": "",
    "include_date": True,
    "include_time": True,
}

EXIF_ORIENTATION = 274
EXIF_IFD = 0x8769


def is_image_file(file_path):
    """Check if a file is an image based on its extension"""
    return os.path.splitext(file_path)[1].lower() in IMAGE_EXTENSIONS


def path_key(path):
    """Normalized path for comparisons (Windows paths are case-insensitive)"""
    return os.path.normcase(os.path.abspath(path))


def format_size(size):
    """Convert bytes to human-readable format"""
    if size == 0:
        return "0B"
    # Savings are negative when the output is larger than the original
    sign = "-" if size < 0 else ""
    size = abs(size)
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = min(int(math.floor(math.log(size, 1024))), len(size_name) - 1)
    p = math.pow(1024, i)
    s = round(size / p, 2)
    return f"{sign}{s} {size_name[i]}"


def exif_text(value):
    """EXIF text for display; cameras often pad empty fields with NUL bytes or spaces"""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    text = str(value).strip("\x00 \t\r\n") if value is not None else ""
    return text or "N/A"


def extract_metadata(file_path):
    """
    Extract metadata from a file
    - For image files: Author, File Size, File Type, Extension
      Date, Date Taken, Dimensions, Resolution, Camera Model
    - For non-image files: Basic file info only
    """
    try:
        # Get basic file info that applies to all file types
        file_size = os.path.getsize(file_path)
        file_ext = os.path.splitext(file_path)[1][1:].upper()
        mod_date = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y-%m-%d %H:%M")

        # Initialize with default values for non-image files
        author = "N/A"
        date_taken = "N/A"
        dimensions = "N/A"
        resolution = "N/A"
        camera_model = "N/A"
        file_type = "Other"

        # Only extract image-specific metadata for image files
        if is_image_file(file_path):
            file_type = "Image"
            with Image.open(file_path) as img:
                exif_data = img.getexif()

                # Get dimensions for images
                dimensions = f"{img.width}×{img.height}"

                # Get resolution for images
                dpi = img.info.get('dpi', (0, 0))
                # Camera JPEGs store DPI as IFDRational, which has no number formatting
                resolution = f"{float(dpi[0]):g}×{float(dpi[1]):g} DPI" if dpi[0] > 0 else "N/A"

                # Extract EXIF data for images (TIFF reads sub-IFDs from the open file)
                if exif_data:
                    author = exif_text(exif_data.get(315))
                    # DateTimeOriginal lives in the Exif sub-IFD, not IFD0
                    date_taken = exif_text(exif_data.get_ifd(EXIF_IFD).get(36867))
                    camera_model = exif_text(exif_data.get(272))

        return {
            "filename": os.path.basename(file_path),
            "author": author,
            "size": format_size(file_size),
            "file_type": file_type,
            "extension": file_ext,
            "date": mod_date,
            "date_taken": date_taken,
            "dimensions": dimensions,
            "resolution": resolution,
            "camera": camera_model
        }

    except Exception as e:
        logging.error(f"Error extracting metadata from {file_path}: {str(e)}")
        return {
            "filename": os.path.basename(file_path),
            "author": "N/A",
            "size": "N/A",
            "file_type": "N/A",
            "extension": "N/A",
            "date": "N/A",
            "date_taken": "N/A",
            "dimensions": "N/A",
            "resolution": "N/A",
            "camera": "N/A"
        }


def output_dimensions(img_path, width):
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


def load_preview(img_path, max_size):
    """Decode a small, upright RGBA preview quickly (JPEGs are decoded at reduced scale)"""
    with Image.open(img_path) as img:
        # JPEG only: decode at the smallest scale that still covers the preview size, which
        # skips most of the work for large photos
        ratio = min(max_size / img.width, max_size / img.height, 1)
        img.draft(None, (max(1, int(img.width * ratio)), max(1, int(img.height * ratio))))
        img.thumbnail((max_size, max_size))
        # Rotate the small image rather than the full-size one
        img = ImageOps.exif_transpose(img)
        return img.convert("RGBA")


# ========== FILE RENAMING ==========
def generate_new_filename(path, index, options, now=None):
    """
    Generate new filename based on the selected renaming pattern
    - path: Original file path
    - index: Position in file list (for sequential numbering)
    - options: pattern, prefix, suffix, include_date, include_time
    Returns new filename with extension
    """
    base_name = os.path.basename(path)
    name, ext = os.path.splitext(base_name)
    ext = ext.lower()  # Standardize extension case
    now = now or datetime.now()

    pattern = options["pattern"]
    prefix = options["prefix"]
    suffix = options["suffix"]
    date_str = now.strftime("%Y-%m-%d") if options["include_date"] else ""
    time_str = now.strftime("%H-%M") if options["include_time"] else ""

    if pattern == "Sequential Numbering":
        return f"image_{index+1}{ext}"

    elif pattern == "Alphanumeric Pattern":
        # Generate pattern: img_A1 ... img_A10, img_B1 ... img_Z10, img_AA1, etc.
        letter = ""
        group = index // 10
        while group >= 0:
            letter = chr(65 + group % 26) + letter
            group = group // 26 - 1
        number = index % 10 + 1
        return f"img_{letter}{number}{ext}"

    elif pattern == "Add Prefix/Suffix":
        return f"{prefix}{name}{suffix}{ext}"

    elif pattern == "Date and Time":
        dt_str = "_".join(part for part in (date_str, time_str) if part)
        return f"FILE_{dt_str}_{index+1}{ext}"

    elif pattern == "Custom Pattern":
        # prefix_index_suffix, where prefix/suffix may use {name}, {date}, {time} placeholders
        custom_pattern = f"{prefix}_{{index}}_{suffix}"
        custom_pattern = custom_pattern.replace("{prefix}", prefix)
        custom_pattern = custom_pattern.replace("{suffix}", suffix)
        custom_pattern = custom_pattern.replace("{index}", str(index+1))
        custom_pattern = custom_pattern.replace("{date}", date_str)
        custom_pattern = custom_pattern.replace("{time}", time_str)
        custom_pattern = custom_pattern.replace("{name}", name)
        return f"{custom_pattern}{ext}"

    # Fallback to original name
    return base_name


def rename_files(paths, options):
    """
    Rename files on disk using the selected pattern
    Returns (new_paths, renamed_count, error message or None)
    """
    new_paths = list(paths)
    renamed_count = 0
    now = datetime.now()

    try:
        for i, path in enumerate(paths):
            new_name = generate_new_filename(path, i, options, now)
            new_path = os.path.join(os.path.dirname(path), new_name)

            # Skip if name hasn't changed
            if os.path.basename(path) == new_name:
                continue

            # Handle filename conflicts (a case-only rename on Windows matches the file itself)
            counter = 1
            base_new_path = new_path
            while os.path.exists(new_path) and path_key(new_path) != path_key(path):
                name, ext = os.path.splitext(base_new_path)
                new_path = f"{name}_{counter}{ext}"
                counter += 1

            os.rename(path, new_path)
            new_paths[i] = new_path
            renamed_count += 1

    except Exception as e:
        logging.error(f"Error renaming files: {str(e)}")
        return new_paths, renamed_count, str(e)

    return new_paths, renamed_count, None


# ========== IMAGE OPTIMIZATION ==========
def resize_image(img, width=None, height=None):
    """Resize image while maintaining aspect ratio (never upscales)"""
    orig_width, orig_height = img.size

    # If both dimensions are specified, fit within them
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


def strip_metadata(img):
    """Remove EXIF/XMP metadata, keeping the color profile and transparency"""
    stripped_img = img.copy()
    stripped_img.info = {key: img.info[key] for key in ("icc_profile", "transparency") if key in img.info}
    return stripped_img


class BatchOptimizer:
    """
    Optimizes one batch of images with a fixed snapshot of settings:
    images, output_dir, format, comp_mode, quality, width, progressive,
    lqip, strip_meta, hash_names
    """

    def __init__(self, settings):
        self.settings = settings
        # Never overwrite a source image or another output from the same batch
        self.source_paths = {path_key(p) for p in settings["images"]}
        self.batch_outputs = set()

    def run(self, progress=None, is_cancelled=lambda: False):
        """
        Process all images and write the reports
        - progress(done, total, current filename) is called before each image and at the end
        Returns (report rows, error count, cancelled)
        """
        images = self.settings["images"]
        total = len(images)
        report_data = []
        errors = 0

        for i, img_path in enumerate(images):
            if is_cancelled():
                return report_data, errors, True

            if progress:
                progress(i, total, os.path.basename(img_path))

            try:
                for version in self.process_image(img_path):
                    original_size = version["original_size"]
                    new_size = version["size"]
                    savings = original_size - new_size
                    ratio = (savings / original_size) * 100 if original_size else 0

                    report_data.append({
                        "file": os.path.basename(version["path"]),
                        "original_size": format_size(original_size),
                        "new_size": format_size(new_size),
                        "savings": format_size(savings),
                        "ratio": f"{ratio:.1f}%",
                        "dimensions": version["dimensions"]
                    })
            except Exception as e:
                errors += 1
                logging.error(f"Error processing {img_path}: {str(e)}")

        try:
            self.generate_report(report_data)
        except Exception as e:
            errors += 1
            logging.error(f"Error writing report: {str(e)}")

        if progress:
            progress(total, total, "")
        return report_data, errors, False

    def process_image(self, img_path):
        """Process a single image with all optimizations and resizing"""
        original_size = os.path.getsize(img_path)

        # Open the image (closed afterwards so the file isn't left locked)
        with Image.open(img_path) as img:
            # Apply EXIF orientation correction
            img = ImageOps.exif_transpose(img)
            if self.settings["strip_meta"]:
                img = strip_metadata(img)

        # Width comes from the preset or custom entry; height follows each image's own aspect ratio
        resized_img = resize_image(img, self.settings["width"])
        optimized_versions = [self.save_optimized(resized_img, img_path, original_size)]

        # Generate LQIP if requested
        if self.settings["lqip"]:
            optimized_versions.append(self.generate_lqip(resized_img, img_path, original_size))

        return optimized_versions

    def generate_lqip(self, img, img_path, original_size):
        """Create Low-Quality Image Placeholder (LQIP)"""
        lqip = img.copy()
        lqip.thumbnail((20, 20))
        lqip = lqip.filter(ImageFilter.GaussianBlur(radius=2))
        return self.save_optimized(lqip, img_path, original_size, suffix="_lqip")

    def get_unique_output_path(self, output_path):
        """Never overwrite a source image or another output from the same batch"""
        base, ext = os.path.splitext(output_path)
        counter = 1
        while path_key(output_path) in self.source_paths or path_key(output_path) in self.batch_outputs:
            output_path = f"{base}_{counter}{ext}"
            counter += 1
        self.batch_outputs.add(path_key(output_path))
        return output_path

    def save_optimized(self, img, img_path, original_size, suffix=""):
        """Save optimized image with appropriate settings"""
        settings = self.settings

        # Determine output format
        output_format = settings["format"].upper()
        if output_format == "JPEG":
            img = img.convert("RGB")

        # Generate filename
        original_name = os.path.splitext(os.path.basename(img_path))[0]

        if settings["hash_names"]:
            # Use hashed filenames if option is checked
            hash_str = hashlib.md5(img.tobytes()).hexdigest()[:8]
            file_name = f"{hash_str}{suffix}.{output_format.lower()}"
        else:
            # Keep original filename
            file_name = f"{original_name}{suffix}.{output_format.lower()}"

        output_path = self.get_unique_output_path(os.path.join(settings["output_dir"], file_name))

        # Save options
        lossless = settings["comp_mode"] == "lossless"
        quality = settings["quality"]
        save_kwargs = {}
        if output_format == "JPEG":
            # JPEG has no lossless mode, so use its highest quality instead
            save_kwargs["quality"] = 100 if lossless else quality
            if lossless:
                save_kwargs["subsampling"] = 0
            save_kwargs["progressive"] = settings["progressive"]
        elif output_format == "PNG":
            save_kwargs["optimize"] = True
        elif output_format == "WEBP":
            save_kwargs["lossless"] = lossless
            # For lossless WebP, quality is compression effort rather than image quality
            save_kwargs["quality"] = 90 if lossless else quality
            save_kwargs["method"] = 6  # Higher compression
        elif output_format == "AVIF":
            # AVIF has no true lossless mode here; use maximum quality without chroma subsampling
            save_kwargs["quality"] = 100 if lossless else quality
            if lossless:
                save_kwargs["subsampling"] = "4:4:4"

        # Pillow drops metadata on save unless it is passed explicitly
        exif = img.getexif()
        if exif:
            exif_bytes = exif.tobytes()
            # JPEG stores EXIF in a single segment of at most 64 KB
            if output_format != "JPEG" or len(exif_bytes) <= 65533:
                save_kwargs["exif"] = exif_bytes
        if img.info.get("icc_profile"):
            save_kwargs["icc_profile"] = img.info["icc_profile"]

        img.save(output_path, format=output_format, **save_kwargs)

        return {
            "path": output_path,
            "size": os.path.getsize(output_path),
            "original_size": original_size,
            "dimensions": img.size
        }

    def generate_report(self, data):
        """Generate optimization reports in JSON and HTML formats"""
        output_dir = self.settings["output_dir"]
        report_path = os.path.join(output_dir, "optimization_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        # Generate HTML report
        html_path = os.path.join(output_dir, "report.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write('<html><head><meta charset="utf-8"><style>')
            f.write("body { font-family: Arial, sans-serif; }")
            f.write("table { border-collapse: collapse; width: 100%; }")
            f.write("th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }")
            f.write("tr:nth-child(even) { background-color: #f2f2f2; }")
            f.write("th { background-color: #4CAF50; color: white; }")
            f.write("</style></head><body>")
            f.write("<h1>Image Optimization Report</h1>")
            f.write("<table>")
            f.write("<tr>")
            f.write("<th>File</th><th>Original</th><th>Optimized</th><th>Savings</th><th>Ratio</th><th>Dimensions</th>")
            f.write("</tr>")

            for item in data:
                f.write("<tr>")
                f.write(f"<td>{html.escape(item['file'])}</td>")
                f.write(f"<td>{item['original_size']}</td>")
                f.write(f"<td>{item['new_size']}</td>")
                f.write(f"<td>{item['savings']}</td>")
                f.write(f"<td>{item['ratio']}</td>")
                f.write(f"<td>{item['dimensions'][0]}x{item['dimensions'][1]}</td>")
                f.write("</tr>")

            f.write("</table></body></html>")
