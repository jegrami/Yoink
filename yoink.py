#!/usr/bin/env python3

"""
yoink.py
--------
CLI tool to download YouTube videos in best available quality.

- Downloads highest quality video + audio using adaptive mode
- Uses ffmpeg for merging when needed
- Falls back to progressive mode if adaptive stream is not available or ffmpeg is not installed
- Progress bars via tqdm
- Output directory configurable

Author: Jeremiah Igrami

"""

import sys 
import re 
import argparse 
import shutil
import subprocess 

from pathlib import Path 
from typing import Optional, List

from pytubefix import YouTube, Playlist 
from pytubefix.exceptions import PytubeFixError 
from tqdm import tqdm 


# === ANSI color definitions for a more informative CLI output ===


ESC = chr(27)

RESET = f"{ESC}[0m"
BOLD = f"{ESC}[1m"

GREEN = f"{ESC}[92m"
RED = f"{ESC}[91m"
YELLOW = f"{ESC}[93m"
BLUE = f"{ESC}[94m"


# === Loging definition ===
LOG_INFO = f"{BLUE}[+]{RESET}"
LOG_OK   = f"{GREEN}[✓]{RESET}"
LOG_WARN = f"{YELLOW}[!]{RESET}"
LOG_ERR  = f"{RED}[-]{RESET}"


# === Helper functions === 

def sanitize_filename(name: str, replacement: str = "_") -> str:
    """Return a filesystem-safe version of a filename."""
    name = re.sub(r'[\\/*?:"<>|]', replacement, name)
    name = name.strip()[:200]
    return name or "video"


def resolution_value(stream) -> int:
    """Return the stream resolution as int (e.g. '1080p' -> 1080) or 0 if unknown."""
    if not stream or not getattr(stream, "resolution", None):
        return 0
    try:
        return int(stream.resolution.replace("p", ""))
    except ValueError:
        return 0


def is_ffmpeg_available() -> bool:
    """Return True if ffmpeg is available on PATH."""
    return shutil.which("ffmpeg") is not None


def create_progress_bar(
    total_bytes: Optional[int],
    desc: str,
    position: int = 0,
    color: str = "green",
) -> tqdm:
    """
    Create a tqdm progress bar with a 'pip-like' style:

    - colored bar
    - shows downloaded size, total size, speed, elapsed time
    """
    if total_bytes is None:
        total_bytes = 0

    return tqdm(
        total=total_bytes,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        desc=desc,
        ascii=False,
        position=position,
        leave=True,
        color=color,     
        dynamic_ncols=True,
        bar_format=(
            "{l_bar}{bar} "
            "{n_fmt}/{total_fmt} "
            "{rate_fmt} "
            "{elapsed}"
        ),
    )


def download_with_progress(
    yt: YouTube,
    stream,
    output_dir: Path,
    description: str,
    filename: Optional[str] = None,
    color: str = "green",
) -> Path:
    """
    Show progress bar when downloading stream, including how many bytes 
    have been downloaded and how many left.

    Returns the Path to the downloaded file.
    """
    total_size = getattr(stream, "filesize", None)
    if total_size is None:
        total_size = getattr(stream, "filesize_approx", None)

    progress_bar = create_progress_bar(total_size, desc=description, color=color)

    last_bytes_remaining = total_size or 0

    def on_progress(_stream, _chunk, bytes_remaining: int) -> None:
        nonlocal last_bytes_remaining
        if total_size is None:
            downloaded_now = len(_chunk)
        else:
            downloaded_now = last_bytes_remaining - bytes_remaining
            last_bytes_remaining = bytes_remaining

        if downloaded_now > 0:
            progress_bar.update(downloaded_now)

    yt.register_on_progress_callback(on_progress)

    try:
        file_path_str = stream.download(
            output_path=str(output_dir),
            filename=filename,
        )
    finally:
        progress_bar.close()

    return Path(file_path_str)



# === Main script logic; everything before this is just warm up === 








