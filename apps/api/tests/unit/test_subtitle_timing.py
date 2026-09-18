from onetake_api.modules.subtitle.service import _build_segments, _format_srt


def test_build_segments_and_srt() -> None:
    segments = _build_segments("第一句话。第二句话！第三句话？", 6.0)
    assert len(segments) == 3
    assert segments[0]["start"] == 0
    assert segments[-1]["end"] == 6.0
    srt = _format_srt(segments)
    assert "00:00:00,000 -->" in srt
    assert "第三句话？" in srt
