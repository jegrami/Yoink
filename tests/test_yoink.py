from __future__ import annotations

import subprocess
from pathlib import Path 
from types import SimpleNamespace 

import pytest 

import yoink 


class FakeStream:
    def __init__(
        self,
        *,
        progressive=False,
        only_video=False,
        only_audio=False,
        file_extension=None,
        resolution=None,
        abr=None,
        subtype=None,
        mime_type="",
        audio_codec="",
    ):
        self.progressive = progressive
        self.only_video = only_video
        self.only_audio = only_audio
        self.file_extension = file_extension
        self.resolution = resolution
        self.abr = abr
        self.subtype = subtype
        self.mime_type = mime_type
        self.audio_codec = audio_codec


class FakeQuery:
    def __init__(self, streams):
        self._streams = list(streams)
        self._sort_key = None
        self._reverse = False

    def filter(self, **kwargs):
        result = self._streams
        for key, expected in kwargs.items():
            result = [s for s in result if getattr(s, key, None) == expected]
        return FakeQuery(result)

    def order_by(self, key):
        self._sort_key = key
        return self

    def desc(self):
        self._reverse = True
        return self

    def first(self):
        if not self._streams:
            return None

        def sort_value(stream):
            if self._sort_key == "resolution":
                raw = getattr(stream, "resolution", None) or ""
                return int(str(raw).replace("p", "")) if str(raw).endswith("p") else 0
            if self._sort_key == "abr":
                raw = getattr(stream, "abr", None) or ""
                return int(str(raw).replace("kbps", "")) if "kbps" in str(raw) else 0
            return 0

        streams = sorted(self._streams, key=sort_value, reverse=self._reverse)
        return streams[0]

class FakeYouTube:
    def __init__(self, url, *, title="Video", video_id="abc123", streams=None):
        self.url = url
        self.title = title
        self.video_id = video_id
        self.streams = FakeQuery(streams or [])

    def register_on_progress_callback(self, _cb):
        return None


def make_default_streams():
    progressive_720 = FakeStream(
        progressive=True, file_extension="mp4", resolution="720p", subtype="mp4"
    )
    video_1080 = FakeStream(
        only_video=True, file_extension="mp4", resolution="1080p", subtype="mp4"
    )
    audio_m4a = FakeStream(
        only_audio=True,
        file_extension="mp4",
        abr="160kbps",
        subtype="m4a",
        mime_type="audio/mp4",
        audio_codec="mp4a.40.2",
    )
    return [progressive_720, video_1080, audio_m4a]

    

@pytest.fixture
def patch_download_with_progress(monkeypatch, tmp_path):
    def _patch():
        def fake_download_with_progress(*, filename=None, **_kwargs):
            assert filename is not None
            out = tmp_path / filename
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"dummy")
            return out

        monkeypatch.setattr(yoink, "download_with_progress", fake_download_with_progress)

    return _patch


def test_is_playlist_url_detection():
    assert yoink.is_playlist_url("https://www.youtube.com/playlist?list=PL123")
    assert yoink.is_playlist_url("https://www.youtube.com/watch?v=abc&list=PL123")
    assert not yoink.is_playlist_url("https://www.youtube.com/watch?v=abc")


def test_download_video_progressive_path(monkeypatch, tmp_path, patch_download_with_progress):
    streams = [s for s in make_default_streams() if s.progressive]
    monkeypatch.setattr(yoink, "YouTube", lambda url: FakeYouTube(url, streams=streams))
    monkeypatch.setattr(yoink, "is_ffmpeg_available", lambda: False)
    patch_download_with_progress()

    ok = yoink.download_video("https://example/video", output_dir=str(tmp_path), exit_on_error=False)
    assert ok is True


def test_download_video_adaptive_copy_success(monkeypatch, tmp_path, patch_download_with_progress):
    monkeypatch.setattr(yoink, "YouTube", lambda url: FakeYouTube(url, streams=make_default_streams()))
    monkeypatch.setattr(yoink, "is_ffmpeg_available", lambda: True)
    patch_download_with_progress()

    calls = []

    def fake_run(cmd, check):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(yoink.subprocess, "run", fake_run)

    ok = yoink.download_video(
        "https://example/video",
        output_dir=str(tmp_path),
        force_best_quality=True,
        audio_codec="copy",
        exit_on_error=False,
    )
    assert ok is True
    assert calls, "Expected at least one ffmpeg call."
    assert any("copy" in part for part in calls[0])


def test_download_video_copy_fallback_to_aac(monkeypatch, tmp_path, patch_download_with_progress):
    monkeypatch.setattr(yoink, "YouTube", lambda url: FakeYouTube(url, streams=make_default_streams()))
    monkeypatch.setattr(yoink, "is_ffmpeg_available", lambda: True)
    patch_download_with_progress()

    calls = {"count": 0}

    def fake_run(cmd, check):
        calls["count"] += 1
        if calls["count"] == 1:
            raise subprocess.CalledProcessError(returncode=1, cmd=cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(yoink.subprocess, "run", fake_run)

    ok = yoink.download_video(
        "https://example/video",
        output_dir=str(tmp_path),
        force_best_quality=True,
        audio_codec="copy",
        exit_on_error=False,
    )
    assert ok is True
    assert calls["count"] == 2, "Expected copy attempt then AAC retry."


def test_download_playlist_continue_on_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        yoink,
        "Playlist",
        lambda _url: SimpleNamespace(title="PL", video_urls=["u1", "u2", "u3"]),
    )

    calls = []

    def fake_download_video(url, **_kwargs):
        calls.append(url)
        return url != "u2"

    monkeypatch.setattr(yoink, "download_video", fake_download_video)

    ok = yoink.download_playlist(
        "https://example/playlist",
        output_dir=str(tmp_path),
        stop_on_error=False,
    )
    assert ok is False
    assert calls == ["u1", "u2", "u3"]


def test_download_playlist_stop_on_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        yoink,
        "Playlist",
        lambda _url: SimpleNamespace(title="PL", video_urls=["u1", "u2", "u3"]),
    )

    calls = []

    def fake_download_video(url, **_kwargs):
        calls.append(url)
        return url != "u2"

    monkeypatch.setattr(yoink, "download_video", fake_download_video)

    ok = yoink.download_playlist(
        "https://example/playlist",
        output_dir=str(tmp_path),
        stop_on_error=True,
    )
    assert ok is False
    assert calls == ["u1", "u2"]


def test_download_playlist_range_selection(monkeypatch, tmp_path):
    monkeypatch.setattr(
        yoink,
        "Playlist",
        lambda _url: SimpleNamespace(title="PL", video_urls=["u1", "u2", "u3", "u4"]),
    )

    seen = []

    def fake_download_video(url, **kwargs):
        seen.append((url, kwargs.get("filename_prefix")))
        return True

    monkeypatch.setattr(yoink, "download_video", fake_download_video)

    ok = yoink.download_playlist(
        "https://example/playlist",
        output_dir=str(tmp_path),
        start=2,
        end=3,
    )
    assert ok is True
    assert [u for u, _ in seen] == ["u2", "u3"]
    assert seen[0][1].startswith("2")
    assert seen[1][1].startswith("3")


def test_skip_existing_short_circuits(monkeypatch, tmp_path, patch_download_with_progress):
    yt = FakeYouTube("u", title="My Video", streams=make_default_streams())
    monkeypatch.setattr(yoink, "YouTube", lambda url: yt)
    monkeypatch.setattr(yoink, "is_ffmpeg_available", lambda: False)

    existing = tmp_path / "My Video.mp4"
    existing.write_bytes(b"already-there")

    def should_not_run(*args, **kwargs):
        raise AssertionError("download_with_progress should not be called when skip_existing=True")

    monkeypatch.setattr(yoink, "download_with_progress", should_not_run)

    ok = yoink.download_video(
        "https://example/video",
        output_dir=str(tmp_path),
        skip_existing=True,
        exit_on_error=False,
    )
    assert ok is True 
