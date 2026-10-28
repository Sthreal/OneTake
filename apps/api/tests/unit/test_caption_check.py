"""批次 1b 单测：字幕安全区（渲染前估算 + 渲染后探针 + 交付门接入）。

关键一条：估算常数是**实测标定**的，所以这里拿**真渲染**去比（估算 vs 实际墨迹框），
而不是只断言自己算出来的数。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.integrations.media import subtitle_burner as burner
from onetake_api.integrations.media.subtitle_burner import burn_subtitles
from onetake_api.modules.content_qa.caption_check import (
    KIND_CAPTION_MISSING,
    KIND_LABEL_OVERLAP,
    KIND_PINNED_BOTTOM,
    KIND_TALL_BAND,
    KIND_WIDE_LINE,
    SEVERITY_INFO,
    SEVERITY_WARN,
    check_caption_layout,
    estimate_cue_boxes,
    label_box,
    probe_caption_pixels,
    safe_width_px,
)

WIDTH, HEIGHT, FPS = 1080, 1920, 25


def _black_video(root: Path, *, width: int = WIDTH, height: int = HEIGHT) -> bytes:
    output = root / f"black-{width}x{height}.mp4"
    subprocess.run(
        [get_ffmpeg_exe(), "-y", "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:d=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)],
        check=True, capture_output=True, text=True,
    )
    return output.read_bytes()


def _ink_box(root: Path, video_bytes: bytes, *, tag: str) -> tuple[int, int, int, int]:
    video = root / f"{tag}.mp4"
    frame = root / f"{tag}.png"
    video.write_bytes(video_bytes)
    subprocess.run(
        [get_ffmpeg_exe(), "-y", "-ss", "0.5", "-i", str(video), "-frames:v", "1", str(frame)],
        check=True, capture_output=True, text=True,
    )
    with Image.open(frame) as image:
        box = image.convert("L").point(lambda value: 255 if value > 60 else 0).getbbox()
    assert box is not None, "渲染出来的帧里没有任何字"
    return box


def _srt(text: str) -> bytes:
    return f"1\n00:00:00,000 --> 00:00:02,000\n{text}\n".encode("utf-8")


def test_estimate_matches_real_render() -> None:
    """估算常数必须对得上真渲染（1080×1920、standard）：宽/高/底边都在容差内。"""
    text = "测试字幕"
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        box = _ink_box(root, burn_subtitles(
            base_video_bytes=_black_video(root), srt_bytes=_srt(text),
            duration_seconds=2, fps=FPS, width=WIDTH, style="standard",
        ), tag="estimate")
    estimated = estimate_cue_boxes(
        cues=[(text, 0.0, 0.0)], width=WIDTH, height=HEIGHT, font_size_units=16,
    )[0]
    actual_w, actual_h = box[2] - box[0], box[3] - box[1]
    assert abs(estimated.width_px - actual_w) / actual_w < 0.12, (estimated.width_px, actual_w)
    assert abs(estimated.height_px - actual_h) / actual_h < 0.25, (estimated.height_px, actual_h)
    assert abs(estimated.box[3] - box[3]) <= 15, (estimated.box[3], box[3])
    assert abs((estimated.box[0] + estimated.box[2]) / 2 - (box[0] + box[2]) / 2) <= 6


def test_layout_flags_over_long_line_and_warns_on_tall_band() -> None:
    """验收 5：超长文案 → 报 warn（具体命中"字幕带过高"；单行超宽记 info，渲染器会自动折行）。"""
    long_line = "这是一句故意写得非常长的字幕文案用来触发越界检查" * 2
    findings = check_caption_layout(width=WIDTH, height=HEIGHT, authored_lines=[long_line])
    kinds = {(finding.kind, finding.severity) for finding in findings}
    assert (KIND_WIDE_LINE, SEVERITY_INFO) in kinds
    assert (KIND_TALL_BAND, SEVERITY_WARN) in kinds


def test_layout_passes_on_normal_caption_from_real_pipeline() -> None:
    """真实 SRT（走生产切分）只在"会被自动折行"上给 info，不给 warn。"""
    srt = _srt("今天这支口红真的绝了，涂上之后气色立刻不一样")
    findings = check_caption_layout(width=WIDTH, height=HEIGHT, srt_bytes=srt)
    assert [finding for finding in findings if finding.severity == SEVERITY_WARN] == []
    assert all(finding.kind == KIND_WIDE_LINE for finding in findings)
    assert all(finding.at_seconds for finding in findings), "info 也要带上秒数，便于定位"


def test_layout_flags_label_overlap_when_caption_drops_to_bottom(monkeypatch) -> None:
    """把字幕压到帧底（MarginV=0）时，会与 bottom_right 的 AIGC 标识框相撞 → warn。"""
    monkeypatch.setattr(burner, "CAPTION_MARGIN_V", 0)
    # 要横着也能够到右下角标识（标识在 x≈950..1038）→ 用一条 14 字的长字幕
    findings = check_caption_layout(
        width=WIDTH, height=HEIGHT, authored_lines=["测试字幕文字测试字幕文字测试"],
        label_position="bottom_right", avoid_subtitle=False,
    )
    overlaps = [finding for finding in findings if finding.kind == KIND_LABEL_OVERLAP]
    assert overlaps and overlaps[0].severity == SEVERITY_WARN
    marker = label_box(
        width=WIDTH, height=HEIGHT, position="bottom_right",
        size_ratio=0.028, margin_ratio=0.04, avoid_subtitle=False,
    )
    assert marker is not None and marker[3] > HEIGHT * 0.9


def test_probe_passes_on_normal_caption() -> None:
    """真渲染的正常字幕：探针不得误报（没有 warn）。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        video = burn_subtitles(
            base_video_bytes=_black_video(root), srt_bytes=_srt("测试字幕"),
            duration_seconds=2, fps=FPS, width=WIDTH, style="standard",
        )
        findings = probe_caption_pixels(video_bytes=video, width=WIDTH, height=HEIGHT)
    assert findings == [], [finding.message for finding in findings]


def test_probe_detects_pinned_bottom_caption(monkeypatch) -> None:
    """字幕贴到帧底（MarginV 压到 -3 → 字墨底边落到帧边）→ 探针报"疑似被裁"。

    注：MarginV=0 实测底边仍留 ~15px（0.2em 的下伸余量）→ 不贴边、不该报；所以这里用 -3 构造真正的贴底。
    """
    monkeypatch.setattr(burner, "CAPTION_MARGIN_V", -3)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        video = burn_subtitles(
            base_video_bytes=_black_video(root), srt_bytes=_srt("测试字幕"),
            duration_seconds=2, fps=FPS, width=WIDTH, style="standard",
        )
        findings = probe_caption_pixels(video_bytes=video, width=WIDTH, height=HEIGHT)
    assert [finding.kind for finding in findings] == [KIND_PINNED_BOTTOM]


def test_probe_detects_missing_caption() -> None:
    """没烧字幕的片子：探针报"抽帧未检出字幕像素"。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        video = _black_video(Path(temp_dir))
        findings = probe_caption_pixels(video_bytes=video, width=WIDTH, height=HEIGHT)
    assert [finding.kind for finding in findings] == [KIND_CAPTION_MISSING]


# ---- 交付门接入 ----


def _patch_gate_dependencies(monkeypatch) -> None:
    class _FakeQa:
        def latest(self, session, project_id):
            return None

    class _FakeCompliance:
        def report(self, session, *, project_id):
            return SimpleNamespace(banned_words=[], platform_warnings=[])

    class _FakeAck:
        def list_for_project(self, session, project_id):
            return []

    monkeypatch.setattr("onetake_api.modules.video_plan.gate.ContentQaPublicService", _FakeQa)
    monkeypatch.setattr("onetake_api.modules.video_plan.gate.CompliancePublicService", _FakeCompliance)
    monkeypatch.setattr("onetake_api.modules.video_plan.gate.GateAckRepository", _FakeAck)


def test_gate_reports_caption_safety_warn(monkeypatch) -> None:
    from onetake_api.modules.video_plan.gate import build_gate_report

    _patch_gate_dependencies(monkeypatch)
    monkeypatch.setattr(
        "onetake_api.modules.video_plan.gate.check_captions",
        lambda **_kwargs: [SimpleNamespace(kind=KIND_PINNED_BOTTOM, severity=SEVERITY_WARN,
                                          message="字幕像素贴到画面底部：疑似被裁切", at_seconds=[0.3])],
    )
    gate = build_gate_report(None, project_id="prj_test", srt_bytes=_srt("测试字幕"))
    check = next(item for item in gate.checks if item.id == "caption_safety")
    assert check.level == "warn"
    assert "疑似被裁切" in check.message
    assert check.at_seconds == [0.3]
    assert gate.download_allowed is False, "warn 未 ack 前不允许下载（既有语义不变）"


def test_gate_reports_caption_safety_ok_on_clean_caption(monkeypatch) -> None:
    from onetake_api.modules.video_plan.gate import build_gate_report

    _patch_gate_dependencies(monkeypatch)
    srt = _srt("涂上之后气色立刻不一样")
    gate = build_gate_report(None, project_id="prj_test", srt_bytes=srt)
    check = next(item for item in gate.checks if item.id == "caption_safety")
    assert check.level == "ok"
    assert "通过" in check.message


def test_gate_skips_caption_safety_without_subtitles(monkeypatch) -> None:
    from onetake_api.modules.video_plan.gate import build_gate_report

    _patch_gate_dependencies(monkeypatch)
    gate = build_gate_report(None, project_id="prj_test")
    assert all(item.id != "caption_safety" for item in gate.checks)


def test_safe_width_matches_measured_wrap_point() -> None:
    """水平安全区口径：1080 宽 = 630px（实测 8 个汉字单行 584px、9 个折行 ≈657px）。"""
    assert abs(safe_width_px(1080) - 630) < 1
    assert abs(safe_width_px(720) - 420) < 1