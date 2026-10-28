"""Phase 5 单测：客观信号、抽帧拼图、合规检查、AIGC 标识断言、交付门汇总。"""
from __future__ import annotations

import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe
from PIL import Image

from onetake_api.config import Settings
from onetake_api.integrations.media.local_composer import LocalCompositionAdapter
from onetake_api.integrations.mock_video.renderer import VideoMetadata, render_base_video
from onetake_api.modules.compliance import ad_words, platform_rules
from onetake_api.modules.compliance.labels import assert_aigc_label
from onetake_api.modules.content_plan.domain import ContentPlan, ContentScene, ContentVariant
from onetake_api.modules.content_qa.contact_sheet import build_contact_sheet, splice_timestamps
from onetake_api.modules.content_qa.domain import LEVEL_OK, LEVEL_WARN, QaRequest
from onetake_api.modules.content_qa.rules import RuleContentQaAdapter
from onetake_api.modules.content_qa.signals import parse_signals, probe_signals
from onetake_api.modules.composition.port import CompositionRequest

WIDTH, HEIGHT, FPS = 1080, 1920, 30

FFMPEG_STDERR = """
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'in.mp4':
  Duration: 00:00:18.00, start: 0.000000, bitrate: 5000 kb/s
[blackdetect @ 0x1] black_start:1.200 black_end:2.000 black_duration:0.800
[blackdetect @ 0x1] black_start:5.000 black_end:6.000 black_duration:1.000
[silencedetect @ 0x2] silence_start: 3.500
[silencedetect @ 0x2] silence_end: 6.400 | silence_duration: 2.900
[freezedetect @ 0x3] freeze_start: 8.000
[freezedetect @ 0x3] freeze_end: 12.500
[Parsed_loudnorm_0 @ 0x4]
Input Integrated:    -21.3 LUFS
Input True Peak:      -0.2 dBFS
"""


def test_parse_signals_reads_all_channels() -> None:
    signals = parse_signals(FFMPEG_STDERR)
    assert [round(segment.start, 3) for segment in signals.black] == [1.2, 5.0]
    assert round(signals.black[0].duration, 3) == 0.8
    assert round(signals.silence[0].start, 3) == 3.5
    assert round(signals.silence[0].duration, 3) == 2.9
    assert round(signals.freeze[0].start, 3) == 8.0
    assert round(signals.freeze[0].duration, 3) == 4.5
    assert signals.loudness_lufs == -21.3
    assert signals.true_peak_dbfs == -0.2
    assert signals.duration_seconds == 18.0


def test_parse_signals_roundtrip_dict() -> None:
    signals = parse_signals(FFMPEG_STDERR)
    restored = type(signals).from_dict(signals.as_dict())
    assert restored == signals


def _black_video(seconds: float = 3.0) -> bytes:
    with tempfile.TemporaryDirectory() as temp_dir:
        output = Path(temp_dir) / "black.mp4"
        subprocess.run(
            [get_ffmpeg_exe(), "-y", "-f", "lavfi", "-i", f"color=c=black:s={WIDTH}x{HEIGHT}:d={seconds}",
             "-f", "lavfi", "-i", "anullsrc", "-shortest", "-r", str(FPS),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(output)],
            check=True, capture_output=True, errors="replace",
        )
        return output.read_bytes()


def _grey_video(seconds: float = 3.0) -> bytes:
    image = Image.new("RGB", (WIDTH, HEIGHT), (180, 185, 190))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return render_base_video(
        image_bytes=buffer.getvalue(), mode="product", template_id="clean",
        duration_seconds=seconds, width=WIDTH, height=HEIGHT, fps=FPS,
    )


def test_probe_signals_detects_black_segments() -> None:
    signals = probe_signals(_black_video())
    assert signals.black, "全黑视频必须被检出黑帧"
    assert signals.black[0].duration >= 2.0
    clean = probe_signals(_grey_video())
    assert not clean.black


def test_splice_timestamps_cover_boundaries_and_edges() -> None:
    stamps = splice_timestamps([5.0, 10.0], duration_seconds=15.0)
    assert stamps[0] == 0.0
    assert any(abs(stamp - 4.8) < 0.01 for stamp in stamps)
    assert any(abs(stamp - 5.2) < 0.01 for stamp in stamps)
    assert stamps == sorted(stamps)
    assert all(0 <= stamp <= 15.0 for stamp in stamps)


def test_contact_sheet_tiles_frames() -> None:
    sheet = build_contact_sheet(_grey_video(6.0), timestamps=[0.0, 1.0, 2.0, 3.0], columns=2, thumb_width=180)
    with Image.open(BytesIO(sheet)) as image:
        assert image.width == 2 * (180 + 16)
        assert image.height == 2 * (int(180 * HEIGHT / WIDTH) + 16 + 26)


def test_ad_words_scan_reports_positions() -> None:
    hits = ad_words.scan("这是全网最低的价格，绝对最好用", where="script")
    words = [hit.word for hit in hits]
    assert "全网最低" in words and "最好" in words
    assert all(hit.where == "script" for hit in hits)
    assert hits == sorted(hits, key=lambda hit: hit.index)
    assert ad_words.scan("这支杯子容量合适，颜色好看", where="script") == []


def test_platform_rules_cover_three_known_risks() -> None:
    warnings = platform_rules.evaluate(
        style="comparison", product_text="美白祛斑精华", copy_text="我亲测有效，用了一周就白",
    )
    ids = {warning.id for warning in warnings}
    assert {"ai_review_style", "digital_human_category", "personal_testimony"} <= ids


def test_platform_rules_are_silent_for_safe_content() -> None:
    assert platform_rules.evaluate(
        style="scene", product_text="保温杯", copy_text="日常通勤都能用"
    ) == []


def test_personal_testimony_is_a_pure_copy_rule() -> None:
    """M4-04 合规口径：`personal_testimony` 是**纯文案规则**，恒判定。

    它原先被 `has_ai_person` 门控 —— 即"只有 avatar 档位才检查"。档位下线后系统无法知道
    画面里有没有人，但这条规则与画面无关，所以必须**照样触发**（否则等于被静默关掉）。
    这里刻意用一个与类目完全无关的商品，确保命中的只有文案。
    """
    warnings = platform_rules.evaluate(style="scene", product_text="保温杯", copy_text="我亲测有效")
    ids = {warning.id for warning in warnings}
    assert "personal_testimony" in ids, "文案含「亲测」必须命中，不能被静默关掉"
    assert "digital_human_category" not in ids


def test_digital_human_category_warns_for_all_five_categories_with_confirmation_wording() -> None:
    """M4-04 合规口径：五类目**恒触发**，且文案已改写为"确认后放行"（让 warn 成为人工确认入口）。"""
    for category, keywords in platform_rules.DIGITAL_HUMAN_BANNED_CATEGORIES.items():
        warnings = platform_rules.evaluate(style="scene", product_text=keywords[0], copy_text="")
        hit = next((w for w in warnings if w.id == "digital_human_category"), None)
        assert hit is not None, f"「{category}」类目未触发：{keywords[0]}"
        assert "请确认后放行" in hit.message, hit.message
        assert category in hit.message, hit.message


def _composed_with_label(*, label: bool) -> bytes:
    settings = Settings(
        mock_providers=False, composition_provider="local",
        aigc_label_enabled=label, aigc_label_source="local", native_feel_enabled=False,
    )
    return LocalCompositionAdapter(settings=settings).compose(CompositionRequest(
        base_video_bytes=_grey_video(3.0), audio_bytes=None, srt_bytes=None,
        duration_seconds=3.0, width=WIDTH, height=HEIGHT, fps=FPS,
    ))


def test_aigc_label_assertion_distinguishes_burned_and_clean_video() -> None:
    present, message = assert_aigc_label(_composed_with_label(label=True), width=WIDTH, height=HEIGHT)
    assert present is True, message
    missing, message2 = assert_aigc_label(_composed_with_label(label=False), width=WIDTH, height=HEIGHT)
    assert missing is False, message2


def _plan() -> ContentPlan:
    scene = ContentScene(
        "scene_1", 1, "hook", "测试文案", 0.0, 3.0, "product_motion", "保持商品不变",
        True, "center", "clean", "clean", [1], ["product_visible"],
    )
    now = __import__("datetime").datetime.now(__import__("datetime").UTC)
    return ContentPlan("cpl_1", "prj_1", "scr_1", "sub_1", "confirmed", "rules", "rules-v1",
                       [ContentVariant("var_clean", "干净展示", "clean", [scene])], 0, 3.0, None, now, now, now)


def _qa_request(video: bytes, *, expected_audio: bool) -> QaRequest:
    # 直接构造元数据：这里只验证客观信号条目，不需要走成片规格校验（18~25s 那套）
    metadata = VideoMetadata(3.0, WIDTH, HEIGHT, float(FPS), "h264", "aac" if expected_audio else None)
    return QaRequest(plan=_plan(), metadata=metadata, size_bytes=len(video), expected_audio=expected_audio,
                     subtitle_embedded=False, product_layered=True, video_bytes=video)


def test_objective_signals_are_warn_level_and_do_not_score() -> None:
    """冻结/静音这类信号只出 warn，不参与评分，也不影响 passed（它们是风格问题，不是坏片）。"""
    video = _composed_with_label(label=False)
    result = RuleContentQaAdapter().evaluate(_qa_request(video, expected_audio=False))
    by_id = {check.check_id: check for check in result.checks}
    assert {"black_frames", "silence", "freeze", "loudness", "duration_drift"} <= set(by_id)
    for check_id in ("silence", "freeze", "loudness", "duration_drift"):
        check = by_id[check_id]
        assert check.weight == 0
        assert check.critical is False
        assert check.level in {LEVEL_OK, LEVEL_WARN}
    assert result.signals is not None
    assert by_id["black_frames"].weight == 15