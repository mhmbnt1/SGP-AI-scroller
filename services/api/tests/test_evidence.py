from pathlib import Path

import pytest
from focusfeed_api.security.ssrf import UnsafeURL
from focusfeed_api.services.evidence import ToolMissing, coverage, fetch_captions, parse_vtt

VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.500 align:start position:0%
Tonight we're making a <c>high protein</c> stir fry

00:00:02.500 --> 00:00:05.000
Tonight we're making a high protein stir fry

00:00:05.000 --> 00:00:09.200
You need chicken breast, broccoli and garlic

00:00:09.200 --> 00:00:08.000
backwards timing is clamped
"""


def test_parse_vtt_merges_rolling_duplicates_and_strips_tags():
    segs = parse_vtt(VTT)
    assert [s.text for s in segs] == [
        "Tonight we're making a high protein stir fry",
        "You need chicken breast, broccoli and garlic",
        "backwards timing is clamped",
    ]
    assert segs[0].start_s == 0.0 and segs[0].end_s == 2.5
    assert segs[2].end_s >= segs[2].start_s
    assert coverage(segs, 20) == pytest.approx((2.5 + 4.2 + 0.0) / 20, abs=0.01)
    assert coverage(segs, None) == 0.0


def test_fetch_captions_requires_tool_and_safe_url(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("focusfeed_api.services.evidence.shutil.which", lambda name: None)
    with pytest.raises(ToolMissing):
        fetch_captions(
            "https://www.youtube.com/watch?v=abc",
            languages=["en"],
            timeout_seconds=5,
            max_bytes=1000,
            workdir=tmp_path,
        )
    monkeypatch.setattr("focusfeed_api.services.evidence.shutil.which", lambda name: "/usr/bin/true")
    with pytest.raises(UnsafeURL):
        fetch_captions(
            "https://evil.example/watch?v=abc",
            languages=["en"],
            timeout_seconds=5,
            max_bytes=1000,
            workdir=tmp_path,
        )
    with pytest.raises(UnsafeURL):
        fetch_captions(
            "file:///etc/passwd", languages=["en"], timeout_seconds=5, max_bytes=1000, workdir=tmp_path
        )


def test_fetch_captions_uses_fixed_argv_without_shell(tmp_path: Path, monkeypatch):
    calls = []

    class R:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(argv, **kw):
        calls.append((argv, kw))
        (tmp_path / "x.en.vtt").write_text(VTT)
        return R()

    monkeypatch.setattr("focusfeed_api.services.evidence.shutil.which", lambda name: "/usr/bin/yt-dlp")
    monkeypatch.setattr("focusfeed_api.services.evidence.validate_url", lambda url, allowed_domains=None: url)
    monkeypatch.setattr("focusfeed_api.services.evidence.subprocess.run", fake_run)
    res = fetch_captions(
        "https://www.youtube.com/watch?v=abc; rm -rf /",
        languages=["en"],
        timeout_seconds=5,
        max_bytes=10_000,
        workdir=tmp_path,
    )
    argv, kw = calls[0]
    assert (
        isinstance(argv, list)
        and argv[0] == "/usr/bin/yt-dlp"
        and "--skip-download" in argv
        and argv[-2] == "--"
    )
    assert (
        argv[-1] == "https://www.youtube.com/watch?v=abc; rm -rf /"
    )  # passed as ONE argument, never interpreted by a shell
    assert "shell" not in kw and kw["timeout"] == 5
    assert res is not None and res.language == "en" and len(res.segments) == 3
