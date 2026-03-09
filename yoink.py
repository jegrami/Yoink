#!/usr/bin/env python3

"""
yoink.py
--------
CLI tool to download YouTube videos in best available quality.

- Downloads highest quality streams using DASH (Dynamic Adaptive Stream Over HTTP)
- Uses ffmpeg for merging video and audio tracks with lightning speed
- Falls back to Progressive mode if DASH is not available or ffmpeg is not installed
- Implements progress bars with tqdm
- Allows output directory configuration

Author: Jeremiah Igrami

"""

import sys 
import re 
import time
import argparse 
import shutil
import subprocess 

from pathlib import Path 
from urllib.parse import parse_qs, urlparse
from typing import Optional, List, Tuple

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


# === Messages that get printed to stdout ===
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
    """Return the stream resolution as int (e.g. '1080p' -> 1080) or 0 if unknown.
       This will help yoink decide the best available quality by comparing resolutions
    """
    if not stream or not getattr(stream, "resolution", None):
        return 0
    try:
        return int(stream.resolution.replace("p", ""))
    except ValueError:
        return 0


def is_ffmpeg_available() -> bool:
    """Return True if ffmpeg is available in PATH."""
    return shutil.which("ffmpeg") is not None


def is_playlist_url(url: str) -> bool:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return "list" in query or parsed.path.rstrip("/").endswith("/playlist")


def safe_playlist_dir_name(title: str) -> str:
    safe = sanitize_filename(title or "playlist")
    safe = safe.strip(" .")
    return safe or "playlist"


def select_best_audio_stream(yt: YouTube):
    """
    Prefer MP4/M4A audio for safe MP4 alchemy with good old ffmpeg, then fallback to any best audio stream.
    """
    preferred = (
        yt.streams
        .filter(only_audio=True, file_extension="mp4")
        .order_by("abr")
        .desc()
        .first()
    )
    if preferred is not None:
        return preferred

    return (
        yt.streams
        .filter(only_audio=True)
        .order_by("abr")
        .desc()
        .first()
    )


def can_copy_audio_to_mp4(audio_stream) -> bool:
    """
    Return True when audio stream is likely MP4-compatible so that ffmpeg can just do `-c:a copy`.
    """
    if audio_stream is None:
        return False

    subtype = (getattr(audio_stream, "subtype", "") or "").lower()
    mime_type = (getattr(audio_stream, "mime_type", "") or "").lower()
    audio_codec = (getattr(audio_stream, "audio_codec", "") or "").lower()

    return (
        subtype in {"m4a", "mp4"}
        or "mp4" in mime_type
        or "mp4a" in audio_codec
    )



def create_progress_bar(
    total_bytes: Optional[int],
    desc: str,
    position: int = 0,
    colour: str = "green",
) -> tqdm:
    """
    Create a tqdm progress bar (pip style):

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
        colour=colour,     
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
    colour: str = "green",
) -> Path:
    """
    Show progress bar when downloading stream, including how many bytes 
    have been downloaded and how many left.

    Returns the Path to the downloaded file.

    """
    total_size = getattr(stream, "filesize", None)
    if total_size is None:
        total_size = getattr(stream, "filesize_approx", None)

    progress_bar = create_progress_bar(total_size, desc=description, colour=colour)

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



# === Main script logic; everything before this was just warm up === 

def download_video(
    url: str,
    output_dir: str = "downloads",
    force_best_quality: bool = False,
    *,
    exit_on_error: bool = True,
    filename_prefix: str = "",
    audio_codec: str = "copy",
    audio_bitrate: str = "192k",
    skip_existing: bool = False,
    progress_prefix: str = "",
) -> bool:
    """
    Download one video and return True on success, False on failure.
    """

    def fail(message: str, err: Optional[Exception] = None) -> bool:
        if err is not None:
            print(f"{LOG_ERR} {message}: {err}")
        else:
            print(f"{LOG_ERR} {message}")
        if exit_on_error:
            sys.exit(1)
        return False

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    prefix = progress_prefix.strip()
    if prefix and not prefix.endswith(" "):
        prefix = f"{prefix} "

    if audio_codec not in {"copy", "aac"}:
        return fail("Invalid audio codec. Expected 'copy' or 'aac'.")

    try:
        print(f"{LOG_INFO} {BOLD}Fetching video info…{RESET}")
        yt = YouTube(url)
        title = yt.title or "video"
        print(f"{LOG_INFO} Title: {BOLD}{title}{RESET}")

        final_basename = sanitize_filename(f"{filename_prefix}{title}")
        final_output_path = output_dir_path / f"{final_basename}.mp4"

        if skip_existing and final_output_path.exists():
            print(f"{LOG_WARN} Skipping existing file: {BOLD}{final_output_path.name}{RESET}")
            return True

        progressive_stream = (
            yt.streams
            .filter(progressive=True, file_extension="mp4")
            .order_by("resolution")
            .desc()
            .first()
        )

        video_stream = (
            yt.streams
            .filter(only_video=True, file_extension="mp4")
            .order_by("resolution")
            .desc()
            .first()
        )

        audio_stream = select_best_audio_stream(yt)

        prog_res = resolution_value(progressive_stream)
        video_res = resolution_value(video_stream)
        ffmpeg_available = is_ffmpeg_available()

        print(f"{LOG_INFO} Best progressive stream: {BOLD}{prog_res or 'N/A'}p{RESET}")
        print(f"{LOG_INFO} Best adaptive video-only stream: {BOLD}{video_res or 'N/A'}p{RESET}")
        print(f"{LOG_INFO} ffmpeg available: {BOLD}{ffmpeg_available}{RESET}")

        if force_best_quality:
            if not ffmpeg_available:
                return fail("--force-best requires ffmpeg in PATH.")
            if video_stream is None or audio_stream is None:
                return fail("--force-best requires adaptive video and audio streams.")

        use_adaptive = (
            force_best_quality
            or (
                ffmpeg_available
                and video_stream is not None
                and audio_stream is not None
                and video_res > prog_res
            )
        )

        if use_adaptive:
            print(
                f"\n{LOG_INFO} {BOLD}{GREEN}Using high-quality adaptive mode"
                f" (video + audio + ffmpeg merge).{RESET}"
            )

            video_ext = video_stream.subtype or "mp4"
            audio_ext = audio_stream.subtype or "m4a"

            video_filename = f"{yt.video_id}_video.{video_ext}"
            audio_filename = f"{yt.video_id}_audio.{audio_ext}"

            video_path = None
            audio_path = None

            try:
                video_path = download_with_progress(
                    yt=yt,
                    stream=video_stream,
                    output_dir=output_dir_path,
                    description=f"{prefix}Downloading video",
                    filename=video_filename,
                    colour="green",
                )

                audio_path = download_with_progress(
                    yt=yt,
                    stream=audio_stream,
                    output_dir=output_dir_path,
                    description=f"{prefix}Downloading audio",
                    filename=audio_filename,
                    colour="blue",
                )

                effective_audio_codec = audio_codec
                if audio_codec == "copy" and not can_copy_audio_to_mp4(audio_stream):
                    print(f"{LOG_WARN} Audio stream is not MP4-copy-safe; falling back to AAC.")
                    effective_audio_codec = "aac"

                print(
                    f"\n{LOG_INFO} Merging video and audio with ffmpeg into: "
                    f"{BOLD}{final_output_path.name}{RESET}"
                )

                merge_cmd = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(video_path),
                    "-i",
                    str(audio_path),
                    "-c:v",
                    "copy",
                ]

                if effective_audio_codec == "copy":
                    merge_cmd.extend(["-c:a", "copy", str(final_output_path)])
                else:
                    merge_cmd.extend(["-c:a", "aac", "-b:a", audio_bitrate, str(final_output_path)])

                try:
                    subprocess.run(merge_cmd, check=True)
                except subprocess.CalledProcessError as merge_err:
                    if effective_audio_codec == "copy":
                        print(f"{LOG_WARN} Copy-merge failed; retrying with AAC re-encode.")
                        retry_cmd = [
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(video_path),
                            "-i",
                            str(audio_path),
                            "-c:v",
                            "copy",
                            "-c:a",
                            "aac",
                            "-b:a",
                            audio_bitrate,
                            str(final_output_path),
                        ]
                        try:
                            subprocess.run(retry_cmd, check=True)
                        except subprocess.CalledProcessError as retry_err:
                            return fail("ffmpeg merge failed after AAC retry", retry_err)
                    else:
                        return fail("ffmpeg merge failed", merge_err)

            finally:
                for temp_path in (video_path, audio_path):
                    if temp_path is None:
                        continue
                    try:
                        temp_path.unlink(missing_ok=True)
                    except TypeError:
                        if temp_path.exists():
                            temp_path.unlink()

            print(f"\n{LOG_OK} Download and merge complete!")
            print(f"{LOG_INFO} File saved to: {BOLD}{final_output_path.resolve()}{RESET}")
            return True

        print(
            f"\n{LOG_WARN} {BOLD}{YELLOW}Using progressive mode"
            f" (single file: video + audio).{RESET}"
        )

        if progressive_stream is None:
            return fail("No suitable progressive stream found, and adaptive mode is unavailable.")

        final_path = download_with_progress(
            yt=yt,
            stream=progressive_stream,
            output_dir=output_dir_path,
            description=f"{prefix}Downloading",
            filename=final_output_path.name,
            colour="magenta",
        )

        print(f"\n{LOG_OK} Download completed!")
        print(f"{LOG_INFO} File saved to: {BOLD}{final_path.resolve()}{RESET}")
        return True

    except PytubeFixError as e:
        return fail("YouTube / pytubefix error", e)
    except KeyboardInterrupt:
        return fail("Download interrupted by user")
    except Exception as e:
        return fail("Unexpected error", e)


def download_playlist(
    url: str,
    output_dir: str = "downloads",
    force_best_quality: bool = False,
    *,
    start: int = 1,
    end: Optional[int] = None,
    stop_on_error: bool = False,
    audio_codec: str = "copy",
    audio_bitrate: str = "192k",
    skip_existing: bool = False,
    flat_output: bool = False,
    delay: float = 0.0,
) -> bool:
    """
    downloads allplaylist items  by iterating each video URL through download_video().
    """
    try:
        playlist = Playlist(url)
        playlist_title = playlist.title or "playlist"
        all_urls = list(playlist.video_urls)
    except Exception as e:
        print(f"{LOG_ERR} Failed to load playlist: {e}")
        return False

    if not all_urls:
        print(f"{LOG_ERR} Playlist contains no videos.")
        return False

    total_items = len(all_urls)

    if start < 1:
        print(f"{LOG_WARN} --start must be >= 1. Using 1.")
        start = 1

    if end is None or end > total_items:
        end = total_items

    if end < start:
        print(f"{LOG_ERR} Invalid range: start ({start}) is greater than end ({end}).")
        return False

    selected_urls = all_urls[start - 1:end]
    selected_total = len(selected_urls)

    playlist_output_dir = Path(output_dir)
    if not flat_output:
        playlist_output_dir = playlist_output_dir / safe_playlist_dir_name(playlist_title)
    playlist_output_dir.mkdir(parents=True, exist_ok=True)

    print(f"{LOG_INFO} Playlist: {BOLD}{playlist_title}{RESET}")
    print(f"{LOG_INFO} Items selected: {BOLD}{selected_total}{RESET} (range {start}-{end})")
    print(f"{LOG_INFO} Output directory: {BOLD}{playlist_output_dir.resolve()}{RESET}")

    failures: List[Tuple[int, str]] = []
    pad_width = len(str(end))

    for idx, video_url in enumerate(selected_urls, start=start):
        current = idx - start + 1
        progress_prefix = f"[{current}/{selected_total}]"
        filename_prefix = f"{idx:0{pad_width}d} - "

        print(f"\n{LOG_INFO} {BOLD}{progress_prefix} Processing item #{idx}{RESET}")

        ok = download_video(
            video_url,
            output_dir=str(playlist_output_dir),
            force_best_quality=force_best_quality,
            exit_on_error=False,
            filename_prefix=filename_prefix,
            audio_codec=audio_codec,
            audio_bitrate=audio_bitrate,
            skip_existing=skip_existing,
            progress_prefix=progress_prefix,
        )

        if not ok:
            failures.append((idx, video_url))
            if stop_on_error:
                print(f"{LOG_WARN} Stopping early because --stop-on-error is set.")
                break

        if delay > 0 and current < selected_total:
            time.sleep(delay)

    success_count = selected_total - len(failures)

    print(f"\n{LOG_INFO} {BOLD}Playlist summary{RESET}")
    print(f"{LOG_OK} Successful: {success_count}")
    print(f"{LOG_WARN} Failed: {len(failures)}")

    if failures:
        print(f"{LOG_WARN} Failed items:")
        for failed_idx, failed_url in failures:
            print(f"  - #{failed_idx}: {failed_url}")

    return len(failures) == 0




# === The CLI entry configuration ===

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download a YouTube video or playlist in best available quality.\n"
            "Uses DASH method (video+audio tracks downloaded separately) when beneficial and if ffmpeg is available."
        )
    )
    parser.add_argument("url", help="URL of the YouTube video or playlist")
    parser.add_argument(
        "-o",
        "--output",
        default="downloads",
        help="Output directory (default: ./downloads)",
    )
    parser.add_argument(
        "-f",
        "--force-best",
        action="store_true",
        help="Forces adaptive best-quality mode (requires ffmpeg)",
    )
    parser.add_argument(
        "--playlist",
        action="store_true",
        help="Treat URL as playlist even if auto-detection does not match",
    )
    parser.add_argument("--start", type=int, default=1, help="Playlist start index (1-based)")
    parser.add_argument("--end", type=int, default=None, help="Playlist end index (inclusive)")
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop playlist download on first failed item",
    )
    parser.add_argument(
        "--audio-codec",
        choices=("copy", "aac"),
        default="copy",
        help="Audio strategy for adaptive merge (default: copy, auto-fallback to aac if unsafe)",
    )
    parser.add_argument(
        "--audio-bitrate",
        default="192k",
        help="AAC bitrate used when re-encoding (default: 192k)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip download if output file already exists",
    )
    parser.add_argument(
        "--flat-output",
        action="store_true",
        help="Do not create playlist subfolder; write directly into --output",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Delay in seconds between playlist items (default: 0)",
    )
    return parser.parse_args()




def main() -> None:
    args = parse_args()

    playlist_mode = args.playlist or is_playlist_url(args.url)

    if playlist_mode:
        ok = download_playlist(
            args.url,
            output_dir=args.output,
            force_best_quality=args.force_best,
            start=args.start,
            end=args.end,
            stop_on_error=args.stop_on_error,
            audio_codec=args.audio_codec,
            audio_bitrate=args.audio_bitrate,
            skip_existing=args.skip_existing,
            flat_output=args.flat_output,
            delay=args.delay,
        )
    else:
        ok = download_video(
            args.url,
            output_dir=args.output,
            force_best_quality=args.force_best,
            exit_on_error=False,
            audio_codec=args.audio_codec,
            audio_bitrate=args.audio_bitrate,
            skip_existing=args.skip_existing,
        )

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()







