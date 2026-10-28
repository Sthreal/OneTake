from onetake_api.integrations.mock_video.renderer import VideoMetadata
from onetake_api.modules.content_plan.domain import ContentPlan, ContentScene, ContentVariant
from onetake_api.modules.content_qa.domain import QaRequest
from onetake_api.modules.content_qa.rules import RuleContentQaAdapter


def _plan() -> ContentPlan:
    scene = ContentScene("scene_1", 1, "hook", "测试文案", 0.0, 18.0, "product_motion", "保持商品不变", True, "center", "clean", "clean", [1], ["product_visible"])
    return ContentPlan("cpl_1", "prj_1", "scr_1", "sub_1", "confirmed", "rules", "rules-v1", [ContentVariant("var_clean", "干净展示", "clean", [scene])], 0, 18.0, None, __import__("datetime").datetime.now(__import__("datetime").UTC), __import__("datetime").datetime.now(__import__("datetime").UTC), __import__("datetime").datetime.now(__import__("datetime").UTC))


def test_rule_checks_reject_missing_product_and_black_frames() -> None:
    request = QaRequest(plan=_plan(), metadata=VideoMetadata(18.0, 1080, 1920, 30.0, "h264", "aac"), size_bytes=1000, expected_audio=True, subtitle_embedded=True, product_layered=False, video_bytes=b"not-video")
    result = RuleContentQaAdapter().evaluate(request)
    assert result.passed is False
    assert "product_layer" in result.critical_failures
    assert "black_frames" in result.critical_failures


# ==== S14 / M4-02 验收 4：慢速运镜不得被冻结检测误判 ====
#
# 冻结阈值是 freeze_noise_db=-60dB / freeze_min_seconds=4s（content_qa/signals.py）。
# 慢速运镜（每帧位移很小）有被误判的风险，所以本切片必须补一条端到端回归。


def _structured_png() -> bytes:
    """带高频细节的源图。

    冻结检测看的是**帧间差异**：纯色图即使加了运镜也测不出差异（那本来就该判冻结），
    用例会变成假绿。所以源图必须有网格与色块。
    """
    from io import BytesIO

    from PIL import Image, ImageDraw

    image = Image.new("RGB", (360, 640), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for x in range(0, 360, 24):
        draw.line([(x, 0), (x, 640)], fill=(30, 30, 30), width=2)
    for y in range(0, 640, 24):
        draw.line([(0, y), (360, y)], fill=(30, 30, 30), width=2)
    draw.rectangle([100, 200, 260, 420], fill=(200, 40, 40))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _render_motion_video(*, motion: str, seconds: float) -> bytes:
    """用**运镜模块**生成一段带（静音）音轨的素材；滤镜链与 renderer 的 dynamic 分支同构。"""
    import subprocess
    import tempfile
    from pathlib import Path

    from imageio_ffmpeg import get_ffmpeg_exe

    from onetake_api.integrations.mock_video.motion_filters import build_motion_filter

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source, output = root / "in.png", root / "out.mp4"
        source.write_bytes(_structured_png())
        canvas_w, canvas_h = 360 * 2, 640 * 2  # 与 renderer 一致：2× 画布
        motion_filter = build_motion_filter(
            motion, width=canvas_w, height=canvas_h, fps=30, duration_seconds=seconds,
        )
        video_filter = (
            f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
            f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color=white,"
            f"format=yuv420p,{motion_filter},scale=360:640:flags=lanczos"
        )
        subprocess.run(
            [
                get_ffmpeg_exe(), "-y", "-loop", "1", "-i", str(source),
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-vf", video_filter, "-t", f"{seconds:.3f}", "-r", "30",
                "-c:v", "libx264", "-b:v", "8M", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(output),
            ],
            check=True, capture_output=True, text=True,
        )
        return output.read_bytes()


def _frame_at(video_bytes: bytes, seconds: float):
    import subprocess
    import tempfile
    from pathlib import Path

    from imageio_ffmpeg import get_ffmpeg_exe
    from PIL import Image

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        video, frame = root / "in.mp4", root / "f.png"
        video.write_bytes(video_bytes)
        subprocess.run(
            [get_ffmpeg_exe(), "-y", "-ss", f"{seconds:.3f}", "-i", str(video), "-frames:v", "1", str(frame)],
            check=True, capture_output=True, text=True,
        )
        with Image.open(frame) as image:
            return image.convert("RGB").copy()


def test_slow_motion_is_not_flagged_as_freeze() -> None:
    """验收 4：≥4 秒慢速平移跑冻结检测不得告警。

    **为什么还需要"相对比较"守卫**：单看"没被判冻结"不足以证明运镜生效 ——
    实测 `static`（完全静止）**同样**得到 `freeze=[]`，因为有损编码的帧间噪声高于
    freezedetect 的 -60dB 门限（见本档案 S14「实测发现」）。所以这里用
    「平移的帧间平均差 vs 静止的帧间平均差」做**可证伪**的比较
    （实测：pan_left ≈ 33.5 / static ≈ 0.09，约 375 倍；阈值取 10 倍留足余量）。
    若运镜哪天失效，两者会回到同一量级 → 本条测试立刻变红。
    """
    from PIL import ImageChops, ImageStat

    from onetake_api.integrations.mock_video.renderer import inspect_video
    from onetake_api.modules.content_qa.signals import probe_signals

    def measure(motion: str) -> tuple[float, list]:
        video = _render_motion_video(motion=motion, seconds=4.5)
        duration = inspect_video(video).duration_seconds
        assert duration >= 4.0, f"{motion} 素材只有 {duration}s，冻结检测不会触发，用例将空转"
        diff = ImageChops.difference(_frame_at(video, 0.2), _frame_at(video, 4.2)).convert("L")
        return ImageStat.Stat(diff).mean[0], probe_signals(video).freeze

    pan_energy, pan_freeze = measure("pan_left")
    static_energy, _ = measure("static")

    assert pan_freeze == [], f"慢速平移被误判为冻结：{pan_freeze}"
    assert pan_energy > static_energy * 10, (
        f"运镜没有真正生效（平移帧间差 {pan_energy:.3f} vs 静止 {static_energy:.3f}）——"
        "那样本条测试会退化成假绿"
    )