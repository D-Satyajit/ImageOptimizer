# Image Optimizer Pro

A Windows desktop app for preparing photos for the web. It batch-converts and resizes images to WebP, AVIF, JPEG or PNG, and bulk-renames files. Built with [PySide6](https://doc.qt.io/qtforpython-6/) (Qt) and [Pillow](https://python-pillow.org/).

## Features

**Image optimization**

- Output as WebP, AVIF, JPEG or PNG, lossy (with a quality slider) or lossless
- Resize to a preset width (480 px up to 4K) or a custom width. Height follows each image's own aspect ratio, and smaller images are never enlarged
- Photos are turned upright using their EXIF orientation
- Camera metadata (EXIF, including GPS location) is kept unless **Strip metadata** is ticked. The color profile is always kept
- Optional tiny blurred placeholder (`name_lqip.webp`) and content-hashed filenames
- Never overwrites a source image; outputs with the same name get `_1`, `_2`, …
- Writes `optimization_report.json` and `report.html` with the size saved for every file

**Bulk renaming**

- Patterns: sequential numbers, alphanumeric (`img_A1`, `img_A2`, …), prefix/suffix, date and time, or a custom pattern using `{name}`, `{date}` and `{time}`
- The **New Name** column previews the result before anything changes on disk

**Interface**

- Drag and drop files or folders onto the window, or use **Add** (Ctrl+O)
- Previews and file details load in the background, so large photos don't freeze the window
- Cancel a running batch, and open the output folder when it finishes

## Getting started

You need Windows and Python 3.10 or newer (tested with 3.12 and 3.15).

Double-click **`start.bat`**. The first time, it installs the required packages; after that it just opens the app.

To install and run it yourself:

```bash
pip install -r requirements.txt
pythonw image_optimizer.pyw
```

### Desktop shortcut

1. Right-click the desktop, then choose **New** → **Shortcut**
2. Enter `pythonw.exe "C:\path\to\ImageOptimizer\image_optimizer.pyw"` as the target
3. Name it **Image Optimizer**
4. Optional: right-click the shortcut → **Properties** → **Change Icon**

## Project layout

```
ImageOptimizer/
├── image_optimizer.pyw    # Launcher (double-click it, or use start.bat)
├── start.bat              # Installs requirements on first run, then launches
├── optimizer/
│   ├── core.py            # Image processing and renaming, no UI code
│   ├── app.py             # Qt application setup
│   ├── main_window.py     # Main window
│   ├── widgets.py         # File list model, preview and layout helpers
│   ├── workers.py         # Background loading and the optimization thread
│   ├── theme.py           # Dark theme stylesheet and palette
│   └── assets/            # Icons
├── tests/                 # pytest suite for the core logic and the UI
├── requirements.txt
└── requirements-dev.txt
```

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The UI tests run without showing a window. To also test against real camera photos, put a few JPEGs in a `samples/` folder (it is git-ignored).

## Troubleshooting

- Errors are written to `image_optimizer.log` next to `image_optimizer.pyw`.
- Run `python image_optimizer.pyw` (instead of `pythonw`) to see errors in a console.
- The app remembers your last-used folders in `image_optimizer.ini`. Delete that file to reset them.
