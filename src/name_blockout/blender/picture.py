# SPDX-License-Identifier: GPL-3.0-or-later
"""Pictures in and out through Blender (any format it reads; PNG out), as float arrays with rows from the top."""

from __future__ import annotations

from pathlib import Path

import bpy
import numpy as np


def load(path: Path) -> np.ndarray:
    """A picture file as (h, w, 4), values as stored (an 8-bit picture: as shown on a screen)."""
    image = bpy.data.images.load(str(path), check_existing=False)
    w, h = image.size
    pixels = np.empty(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    bpy.data.images.remove(image)
    return pixels.reshape(h, w, 4)[::-1]


def save(path: Path, rgba: np.ndarray) -> Path:
    h, w = rgba.shape[:2]
    image = bpy.data.images.new(path.stem, w, h, alpha=True)
    image.pixels.foreach_set(np.ascontiguousarray(rgba[::-1]).astype(np.float32).ravel())
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    return path
