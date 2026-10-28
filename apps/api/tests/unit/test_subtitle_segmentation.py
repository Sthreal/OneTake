import re

from onetake_api.integrations.media.subtitle_segmentation import split_srt_bytes


def _srt(text: str, start: str = "00:00:03,231", end: str = "00:00:07,673") -> bytes:
    return f"1\n{start} --> {end}\n{text}\n".encode("utf-8")


def test_long_sentence_is_split_into_sequential_cues() -> None:
    original = _srt("市面上的果汁大多没有鲜榨成分，口感不够真实。")
    result = split_srt_bytes(original).decode("utf-8")
    assert result.count("-->") == 2
    # cue 内允许换行、句子允许跨 cue；要守的契约是「字幕文本内容与配音一致」：
    # 因此只取各自的文本行（跳过 cue 号与时间戳行）再拼接比对
    content = "".join(
        re.sub(r"\s+", "", line)
        for line in result.splitlines()
        if line.strip() and "-->" not in line and not line.strip().isdigit()
    )
    assert "市面上的果汁大多没有鲜榨成分" in content
    assert "口感不够真实" in content
    assert "00:00:03,231 -->" in result
    assert "--> 00:00:07,673" in result


def test_short_sentence_is_not_changed() -> None:
    original = _srt("30%鲜橙汁。", start="00:00:07,673", end="00:00:09,087")
    assert split_srt_bytes(original) == original


def test_long_sentence_without_punctuation_is_split_by_length() -> None:
    original = _srt("这是一个没有任何标点但是长度明显超过最大字幕限制的测试句子")
    result = split_srt_bytes(original).decode("utf-8")
    assert result.count("-->") >= 2
