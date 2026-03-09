# yoink 🎬

A simple CLI utility for downloading YouTube videos in the best available quality. Automatically uses DASH (adaptive streams + ffmpeg merge) when it makes sense. Falls back to progressive mode when it doesn't.

**yoink** is a verb, and that's why it's spelled lowercase, even at the beginning of a sentence.

---

## Features

- Downloads best-quality video via DASH (separate video + audio → merged with ffmpeg)
- Falls back to progressive mode if ffmpeg isn't available or DASH isn't worth it
- Playlist support with range selection, delay between items, and failure tracking
- Colored, pip-style progress bars
- Skip already-downloaded files with `--skip-existing`
- Smart audio codec handling. Tries stream copy first, re-encodes to AAC if needed

---

## Requirements

- Python 3.14
- [uv](https://github.com/astral-sh/uv) (package manager)
- [ffmpeg](https://ffmpeg.org/) in your PATH (required for adaptive/DASH mode)

---

## Installation

```bash
git clone git@github.com:jegrami/yoink.git
cd yoink
uv sync
```

---

## Usage

```bash
uv run yoink.py <URL> [options]
```

### Download a single video

```bash
uv run yoink.py "https://youtube.com/watch?v=dQw4w9WgXcQ"
```

### Force best quality (requires ffmpeg)

```bash
uv run yoink.py "https://youtube.com/watch?v=dQw4w9WgXcQ" --force-best
```

### Download to a specific folder

```bash
uv run yoink.py "https://youtube.com/watch?v=dQw4w9WgXcQ" -o Videos/
```

### Download a playlist

yoink auto-detects playlist URLs, so `--playlist` is optional. But you can use it to force playlist mode if auto-detection doesn't pick it up.

```bash
# auto-detected
uv run yoink.py "https://youtube.com/playlist?list=PLxxx"

# or explicit
uv run yoink.py "https://youtube.com/playlist?list=PLxxx" --playlist
```

### Download items 3–10 of a playlist, with a 2-second delay between each

```bash
uv run yoink.py "https://youtube.com/playlist?list=PLxxx" --start 3 --end 10 --delay 2
```

---

## All Options

| Flag | Default | Description |
|---|---|---|
| `url` | — | YouTube video or playlist URL |
| `-o`, `--output` | `./downloads` | Output directory |
| `-f`, `--force-best` | `false` | Force adaptive mode (requires ffmpeg) |
| `--playlist` | `false` | Force playlist mode (auto-detected from URL otherwise) |
| `--start` | `1` | Playlist start index (1-based) |
| `--end` | last item | Playlist end index (inclusive) |
| `--stop-on-error` | `false` | Stop playlist download on first failure |
| `--audio-codec` | `copy` | Audio codec for merge: `copy` or `aac` |
| `--audio-bitrate` | `192k` | AAC bitrate when re-encoding audio |
| `--skip-existing` | `false` | Skip download if the output file already exists |
| `--flat-output` | `false` | Don't create a playlist subfolder |
| `--delay` | `0` | Seconds to wait between playlist items |

---

## How it works

When you run yoink on a YouTube video url, it:

1. Fetches stream info from YouTube
2. Compares the best progressive stream (video+audio in one file) vs. the best adaptive video-only stream
3. If ffmpeg is available **and** the adaptive stream is higher quality → downloads video and audio separately, merges them with ffmpeg
4. Otherwise → falls back to the best progressive stream

For audio merging, it tries `-c:a copy` first (fast, lossless), and automatically falls back to AAC re-encoding if the audio stream isn't MP4-compatible.

---

## Output

Videos are saved as `.mp4` files. Playlist items get a zero-padded numeric prefix (`01 - Title.mp4`, `02 - Title.mp4`, etc.) and are organized into a subfolder named after the playlist (unless `--flat-output` is set).

---

## Running Tests

Tests live in `tests/test_yoink.py` and use [pytest](https://docs.pytest.org/). They cover playlist URL detection, progressive and adaptive download paths, ffmpeg copy-to-AAC fallback, playlist range selection, stop-on-error behavior, and the `--skip-existing` short-circuit.

```bash
uv run pytest
```

For verbose output:

```bash
uv run pytest -v
```

---



## Author

Jeremiah Igrami