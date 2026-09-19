from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CAPTION_CHARS = 16
SPLIT_PUNCTUATION = r"[，。！？；：、,.;!?;:]+"
TIME_PATTERN = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


@dataclass(frozen=True)
class SubtitleCue:
    start_ms: int
    end_ms: int
    text: str


def split_srt_bytes(srt_bytes: bytes) -> bytes:
    try:
        source = srt_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return srt_bytes
    cues = _parse_cues(source)
    if not cues:
        return srt_bytes
    expanded: list[SubtitleCue] = []
    for cue in cues:
        expanded.extend(_split_cue(cue))
    if len(expanded) == len(cues):
        return srt_bytes
    lines: list[str] = []
    for index, cue in enumerate(expanded, 1):
        lines.extend([str(index), f"{_format_time(cue.start_ms)} --> {_format_time(cue.end_ms)}", cue.text, ""])
    return "\n".join(lines).encode("utf-8")


def _parse_cues(source: str) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    for block in re.split(r"\n\s*\n", source.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        match = TIME_PATTERN.search(lines[1])
        if match is None:
            continue
        text = "".join(lines[2:]).strip()
        if not text:
            continue
        start_ms = _to_ms(*match.groups()[0:4])
        end_ms = _to_ms(*match.groups()[4:8])
        if end_ms <= start_ms:
            continue
        cues.append(SubtitleCue(start_ms=start_ms, end_ms=end_ms, text=text))
    return cues


def _split_cue(cue: SubtitleCue) -> list[SubtitleCue]:
    normalized = re.sub(r"[\s\u3000]+", "", cue.text)
    if len(normalized) <= MAX_CAPTION_CHARS:
        return [cue]
    parts = _split_text(normalized)
    if len(parts) <= 1:
        return [cue]
    total_ms = cue.end_ms - cue.start_ms
    total_chars = sum(len(part) for part in parts)
    cursor = cue.start_ms
    remaining_ms = total_ms
    remaining_chars = total_chars
    result: list[SubtitleCue] = []
    for index, part in enumerate(parts):
        if index == len(parts) - 1:
            end_ms = cue.end_ms
        else:
            duration = max(1, round(remaining_ms * len(part) / remaining_chars))
            end_ms = min(cursor + duration, cue.end_ms - (len(parts) - index - 1))
        result.append(SubtitleCue(start_ms=cursor, end_ms=end_ms, text=part))
        cursor = end_ms
        remaining_ms = cue.end_ms - cursor
        remaining_chars -= len(part)
    return result


def _split_text(text: str) -> list[str]:
    punctuation_parts = [part for part in re.split(SPLIT_PUNCTUATION, text) if part]
    expanded: list[str] = []
    for part in punctuation_parts or [text]:
        if len(part) <= MAX_CAPTION_CHARS:
            expanded.append(part)
        else:
            expanded.extend(part[index : index + MAX_CAPTION_CHARS] for index in range(0, len(part), MAX_CAPTION_CHARS))
    packed: list[str] = []
    for part in expanded:
        if packed and len(packed[-1]) + len(part) <= MAX_CAPTION_CHARS:
            packed[-1] += part
        else:
            packed.append(part)
    return packed


def _to_ms(hours: str, minutes: str, seconds: str, milliseconds: str) -> int:
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(milliseconds)


def _format_time(value: int) -> str:
    hours, remainder = divmod(value, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
