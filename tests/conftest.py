"""Shared fixtures: generated test photos and a headless Qt application."""
import os
import sys

import pytest
from PIL import Image, ImageCms

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES_DIR = os.path.join(ROOT, "samples")
sys.path.insert(0, ROOT)

# Run Qt without a visible window
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DATE_TAKEN = "2024:01:02 03:04:05"
SRGB_PROFILE = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def noisy_image(width, height, seed=0):
    """Photo-like content that doesn't compress to nothing"""
    return Image.effect_noise((width, height), 60 + seed).convert("RGB").resize((width, height))


def camera_exif(orientation=1):
    exif = Image.Exif()
    exif[315] = "Tester"
    exif[272] = "CamModel"
    exif[274] = orientation
    exif.get_ifd(0x8769)[36867] = DATE_TAKEN
    return exif


@pytest.fixture
def photos(tmp_path):
    """
    A folder of test images:
    - landscape.jpg 2400x1600 with EXIF and an sRGB profile
    - portrait.jpg stored 2400x1600 but rotated upright by EXIF (1600x2400)
    - small.jpg 600x450, heavily compressed so optimized copies come out larger
    - dup.jpg / dup.png share a name; self.webp matches its own output name
    """
    folder = tmp_path / "photos"
    folder.mkdir()
    noisy_image(2400, 1600, 1).save(folder / "landscape.jpg", quality=92, exif=camera_exif(),
                                    icc_profile=SRGB_PROFILE)
    noisy_image(2400, 1600, 2).save(folder / "portrait.jpg", quality=92, exif=camera_exif(orientation=6))
    noisy_image(600, 450, 3).save(folder / "small.jpg", quality=30)
    noisy_image(400, 300, 4).save(folder / "dup.jpg", quality=80)
    noisy_image(400, 300, 5).save(folder / "dup.png")
    noisy_image(480, 320, 6).save(folder / "self.webp", quality=80)
    return folder


def sample_photos():
    """Real camera photos placed in samples/ (git-ignored); tests using them skip when absent"""
    if not os.path.isdir(SAMPLES_DIR):
        return []
    return sorted(os.path.join(SAMPLES_DIR, name) for name in os.listdir(SAMPLES_DIR)
                  if name.lower().endswith((".jpg", ".jpeg")))
