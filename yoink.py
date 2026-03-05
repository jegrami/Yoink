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
MAGENTA = f"{ESC}[95m"


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

def download_video(url: str, output_dir: str = "downloads", force_best_quality: bool = False) -> None:
    """
    Download a YouTube video from the provided url.

    - If ffmpeg and adaptive stream exist:
        * download best video-only stream (with progress bar)
        * download best audio-only stream (with progress bar)
        * merge both streams using ffmpeg into a final .mp4 file
    - If ffmpeg or adaptive stream is not available:
        * download the best progressive stream (video + audio in one file)
          with a progress bar - progressive usually don't exceed 720p.
    - If `force_best_quality` is True:
        * always use adaptive mode (requires ffmpeg)
    """
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    try:
        print(f"{LOG_INFO} {BOLD}Fetching video info…{RESET}")
        yt = YouTube(url)
        title = yt.title or "video"
        safe_title = sanitize_filename(title)
        print(f"{LOG_INFO} Title: {BOLD}{title}{RESET}")

        # Best progressive stream (video + audio together)
        progressive_stream = (
            yt.streams
            .filter(progressive=True, file_extension="mp4")
            .order_by("resolution")
            .desc()
            .first()
        )

        # Best adaptive video-only stream
        video_stream = (
            yt.streams
            .filter(only_video=True, file_extension="mp4")
            .order_by("resolution")
            .desc()
            .first()
        )

        # Best adaptive audio-only stream (any extension)
        audio_stream = (
            yt.streams
            .filter(only_audio=True)
            .order_by("abr")
            .desc()
            .first()
        )

        prog_res = resolution_value(progressive_stream)
        video_res = resolution_value(video_stream)

        print(f"{LOG_INFO} Best progressive stream: {BOLD}{prog_res or 'N/A'}p{RESET}")
        print(f"{LOG_INFO} Best adaptive video-only stream: {BOLD}{video_res or 'N/A'}p{RESET}")
        print(f"{LOG_INFO} ffmpeg available: {BOLD}{is_ffmpeg_available()}{RESET}")

        # Check requirements for force_best_quality mode
        if force_best_quality:
            if not is_ffmpeg_available():
                print(
                    f"{LOG_ERR} Error: --force-best requires ffmpeg to be installed. "
                    f"Please install ffmpeg or remove the --force-best flag."
                )
                sys.exit(1)
            if video_stream is None or audio_stream is None:
                print(
                    f"{LOG_ERR} Error: --force-best requires adaptive stream (video + audio provided as separate files)"
                )
                sys.exit(1)

        use_adaptive = (
            force_best_quality
            or (
                is_ffmpeg_available()
                and video_stream is not None
                and audio_stream is not None
                and video_res > prog_res
            )
        )

        
        # (Recommended) Best quality mode: separate video + audio, then merge with ffmpeg
        if use_adaptive:
            print(
                f"\n{LOG_INFO} {BOLD}{GREEN}Using high-quality adaptive mode"
                f" (video + audio + ffmpeg merge).{RESET}"
            )

            
            
            # Video-only
            video_ext = video_stream.subtype or "mp4"
            video_filename = f"{yt.video_id}_video.{video_ext}"
            video_size = getattr(video_stream, "filesize", None) or getattr(
                video_stream, "filesize_approx", None
            )
            if video_size:
                print(
                    f"{LOG_INFO} Video size: "
                    f"{BOLD}{video_size / (1024 * 1024):.2f} MB{RESET}"
                )

            video_path = download_with_progress(
                yt=yt,
                stream=video_stream,
                output_dir=output_dir_path,
                description="Downloading video",
                filename=video_filename,
                color="green",
            )

           
            # Audio-only
            audio_ext = audio_stream.subtype or "m4a"
            audio_filename = f"{yt.video_id}_audio.{audio_ext}"
            audio_size = getattr(audio_stream, "filesize", None) or getattr(
                audio_stream, "filesize_approx", None
            )
            if audio_size:
                print(
                    f"{LOG_INFO} Audio size: "
                    f"{BOLD}{audio_size / (1024 * 1024):.2f} MB{RESET}"
                )

            audio_path = download_with_progress(
                yt=yt,
                stream=audio_stream,
                output_dir=output_dir_path,
                description="Downloading audio",
                filename=audio_filename,
                color="blue",
            )

            
            # Merge with ffmpeg
            final_path = output_dir_path / f"{safe_title}.mp4"
            print(
                f"\n{LOG_INFO} Merging video and audio with ffmpeg into: "
                f"{BOLD}{final_path.name}{RESET}"
            )

            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-i",
                str(audio_path),
                "-c",
                "copy",
                str(final_path),
            ]
            subprocess.run(cmd, check=True)

            # Optionally remove temporary files
            try:
                video_path.unlink(missing_ok=True)
                audio_path.unlink(missing_ok=True)
            except TypeError:
                if video_path.exists():
                    video_path.unlink()
                if audio_path.exists():
                    audio_path.unlink()

            print(f"\n{LOG_OK} Download and merge completed!")
            print(f"{LOG_INFO} Final file: {BOLD}{final_path.resolve()}{RESET}")

        
        # Fallback to single progressive stream if adaptive fails
        
        else:
            print(
                f"\n{LOG_WARN} {BOLD}{YELLOW}Using progressive mode"
                f" (single file: video + audio).{RESET}"
            )

            if progressive_stream is None:
                print(f"{LOG_ERR} Could not find a suitable video stream.\nBoth progressive and adaptive modes have failed.\nThere might be a problem with the url. Check and try again.")
                sys.exit(1)

            file_size = getattr(progressive_stream, "filesize", None) or getattr(
                progressive_stream, "filesize_approx", None
            )
            if file_size:
                print(
                    f"{LOG_INFO} Resolution: {BOLD}{progressive_stream.resolution}{RESET}"
                )
                print(
                    f"{LOG_INFO} Size: "
                    f"{BOLD}{file_size / (1024 * 1024):.2f} MB{RESET}"
                )
            print(f"{LOG_INFO} Output directory: {BOLD}{output_dir_path.resolve()}{RESET}")

            final_path = download_with_progress(
                yt=yt,
                stream=progressive_stream,
                output_dir=output_dir_path,
                description="Downloading",
                filename=f"{safe_title}.mp4",
                color="magenta",
            )

            print(f"\n{LOG_OK} Download completed!")
            print(f"{LOG_INFO} File saved to: {BOLD}{final_path.resolve()}{RESET}")

    except PytubeFixError as e:
        print(f"{LOG_ERR} YouTube / pytubefix error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n{LOG_ERR} Download interrupted by user with C^ .")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"{LOG_ERR} ffmpeg execution error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"{LOG_ERR} Unexpected error: {e}")
        sys.exit(1)








