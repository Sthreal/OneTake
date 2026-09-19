from onetake_api.integrations.media.subtitle_segmentation import split_srt_bytes


def _srt(text: str, start: str = "00:00:03,231", end: str = "00:00:07,673") -> bytes:
    return f"1\n{start} --> {end}\n{text}\n".encode("utf-8")


def test_long_sentence_is_split_into_sequential_cues() -> None:
    original = _srt("市面上的果汁大多没有鲜榨成分，口感不够真实。")
    result = split_srt_bytes(original).decode("utf-8")
    assert result.count("-->") == 2
    assert "市面上的果汁大多没有鲜榨成分" in result
    assert "口感不够真实" in result
    assert "00:00:03,231 -->" in result
    assert "--> 00:00:07,673" in result


def test_short_sentence_is_not_changed() -> None:
    original = _srt("30%鲜橙汁。", start="00:00:07,673", end="00:00:09,087")
    assert split_srt_bytes(original) == original


def test_long_sentence_without_punctuation_is_split_by_length() -> None:
    original = _srt("这是一个没有任何标点但是长度明显超过最大字幕限制的测试句子")
    result = split_srt_bytes(original).decode("utf-8")
    assert result.count("-->") >= 2
