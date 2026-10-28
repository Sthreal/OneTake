"""批次 4a-2 单测：素材归一化与"填充空镜"编排。

网络层用 MockTransport 打桩；归一化用 ffmpeg 真跑（不联网、不花钱）。
关键一条：素材片段的产物形状必须与 `GeneratedCandidate` 一致（尺寸/时长/静音/首尾帧），
否则接进分段管线会以"尺寸不一致"之类的错误失败。
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

import httpx
import pytest
from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.integrations.media.video_utils import inspect_video_dimensions, inspect_video_duration
from onetake_api.integrations.stock import clip, registry
from onetake_api.integrations.stock.domain import SOURCE_WIKIMEDIA, StockAsset, StockError, StockLicense
from onetake_api.integrations.stock.fill import fill_from_stock
from onetake_api.modules.content_plan.generator import default_stock_query, generate_rule_variants

WIDTH, HEIGHT, FPS = 1080, 1920, 30


def _source_clip(*, seconds: float = 1.0, width: int = 640, height: int = 360, with_audio: bool = True) -> bytes:
    """造一段"平台素材样"的短片：非目标尺寸 + 非目标时长 + **带音轨**。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        output = Path(temp_dir) / "source.mp4"
        command = [
            get_ffmpeg_exe(), "-y",
            "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:rate=24:duration={seconds}",
        ]
        if with_audio:
            command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-shortest"]
        command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)]
        subprocess.run(command, check=True, capture_output=True)
        return output.read_bytes()


def _has_audio(video_bytes: bytes) -> bool:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "v.mp4"
        path.write_bytes(video_bytes)
        result = subprocess.run([get_ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    return "Audio:" in result.stderr


# ---- 检索词 ----


def test_default_stock_query_mapping() -> None:
    assert default_stock_query("pain_point") == "morning desk workspace light"
    assert default_stock_query("未知目标") == ""


def test_rule_variants_only_give_queries_to_absent_scenes() -> None:
    """批次 2 起：空镜检索词由**钩子库**给出（不再来自 `ABSENT_STOCK_QUERIES` 固定表）。"""
    from onetake_api.modules.content_plan.hook_library import HOOK_IDS, HOOK_PATTERNS

    variants = generate_rule_variants(segments=[{"index": 1, "text": "测试文案。", "start": 0.0, "end": 18.0}])
    hook_queries = {pattern.stock_query for pattern in HOOK_PATTERNS}
    assert len(HOOK_IDS) == len(HOOK_PATTERNS)
    for variant in variants:
        absent = [scene for scene in variant.scenes if scene.product_mode == "absent"]
        assert len(absent) == 1, [scene.product_mode for scene in variant.scenes]
        assert absent[0].stock_query in hook_queries and absent[0].stock_query.isascii()
        assert all(scene.stock_query == "" for scene in variant.scenes if scene.product_mode != "absent")


# ---- 归一化 ----


def test_normalize_clip_fills_frame_loops_duration_and_strips_audio() -> None:
    source = _source_clip(seconds=1.0, with_audio=True)
    normalized = clip.normalize_clip(
        source_bytes=source, duration_seconds=3.5, width=WIDTH, height=HEIGHT, fps=FPS
    )
    assert inspect_video_dimensions(normalized) == (WIDTH, HEIGHT)          # 铺满裁切到目标规格
    assert abs(inspect_video_duration(normalized) - 3.5) <= 0.2             # 1 秒素材循环补到 3.5 秒
    assert _has_audio(normalized) is False                                  # 素材音轨被剥掉（成片音轨只由旁白/BGM 决定）


def test_normalize_clip_rejects_empty_source() -> None:
    with pytest.raises(StockError):
        clip.normalize_clip(source_bytes=b"", duration_seconds=3, width=WIDTH, height=HEIGHT, fps=FPS)


def test_head_and_tail_frames_are_png() -> None:
    normalized = clip.normalize_clip(
        source_bytes=_source_clip(seconds=1.5), duration_seconds=2.0, width=WIDTH, height=HEIGHT, fps=FPS
    )
    head, tail = clip.head_and_tail_frames(normalized)
    assert head.startswith(b"\x89PNG") and tail.startswith(b"\x89PNG")


# ---- 下载体积上限 ----


def test_download_asset_enforces_size_cap() -> None:
    payload = b"x" * 2048
    asset = StockAsset(
        asset_id="a", kind="video", source=SOURCE_WIKIMEDIA, provider="wikimedia-commons",
        title="big", download_url="https://cdn.example/big.webm",
        license=StockLicense("CC BY 4.0"),
    )
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, headers={"Content-Length": str(len(payload))})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(StockError):
            clip.download_asset(asset, client=client, max_bytes=1024)
        assert clip.download_asset(asset, client=client, max_bytes=8192) == payload


# ---- 编排 ----


def _asset(url: str) -> StockAsset:
    return StockAsset(
        asset_id="pageid-1", kind="video", source=SOURCE_WIKIMEDIA, provider="wikimedia-commons",
        title="Morning desk", download_url=url, landing_url="https://commons.example/File:Morning_desk.webm",
        creator="Someone", license=StockLicense("CC BY-SA 4.0"),
    )


def test_fill_from_stock_returns_none_without_results(monkeypatch) -> None:
    monkeypatch.setattr(registry, "find_video", lambda *args, **kwargs: None)
    assert fill_from_stock(
        query="morning desk", duration_seconds=3, width=WIDTH, height=HEIGHT, fps=FPS
    ) is None


def test_fill_from_stock_returns_none_for_blank_query() -> None:
    assert fill_from_stock(
        query="   ", duration_seconds=3, width=WIDTH, height=HEIGHT, fps=FPS
    ) is None


def test_fill_from_stock_propagates_search_error(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise StockError("源挂了")

    monkeypatch.setattr(registry, "find_video", boom)
    with pytest.raises(StockError):
        fill_from_stock(query="morning desk", duration_seconds=3, width=WIDTH, height=HEIGHT, fps=FPS)


def test_fill_from_stock_end_to_end(monkeypatch) -> None:
    """检索（打桩）→ 下载（MockTransport）→ 归一化（真 ffmpeg）→ 首尾帧。"""
    source = _source_clip(seconds=1.0)
    monkeypatch.setattr(registry, "find_video", lambda *args, **kwargs: _asset("https://cdn.example/clip.mp4"))

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://cdn.example/clip.mp4"
        return httpx.Response(200, content=source, headers={"Content-Length": str(len(source))})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fill = fill_from_stock(
            query="morning desk", duration_seconds=3.0, width=WIDTH, height=HEIGHT, fps=FPS, client=client,
        )
    assert fill is not None
    assert fill.provider == "stock:wikimedia"
    assert (fill.width, fill.height, fill.fps) == (WIDTH, HEIGHT, FPS)
    assert inspect_video_dimensions(fill.video_bytes) == (WIDTH, HEIGHT)
    assert abs(inspect_video_duration(fill.video_bytes) - 3.0) <= 0.2
    assert fill.head_frame_bytes.startswith(b"\x89PNG") and fill.tail_frame_bytes.startswith(b"\x89PNG")
    assert "Morning desk" in fill.attribution and "CC BY-SA 4.0" in fill.attribution
    assert re.search(r"CC BY-SA 4\.0", fill.attribution)


# ---- 交付门的素材署名检查（批次 4a）----


class _FakeStorage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self._objects = objects

    def read_object(self, *, object_key: str):
        return [self._objects[object_key]]     # 与真实存储一致：返回可 join 的分块序列


def _candidate(provider: str, video_key: str):
    from types import SimpleNamespace

    return SimpleNamespace(provider=provider, video_object_key=video_key)


def test_stock_sources_check_reads_attribution_sidecar() -> None:
    from types import SimpleNamespace

    from onetake_api.modules.video_plan.gate import stock_sources_check

    video_key = "projects/p/video/v/segments/0/can_1/video.mp4"
    sidecar = video_key.replace("/video.mp4", "/stock-attribution.json")
    storage = _FakeStorage({sidecar: json.dumps(
        {"license": "CC BY-SA 4.0", "attribution": '"Morning desk" by Someone (CC BY-SA 4.0) — https://commons.example/x'},
        ensure_ascii=False,
    ).encode("utf-8")})
    segments = [SimpleNamespace(candidates=[_candidate("stock:wikimedia", video_key)])]

    check = stock_sources_check(segments=segments, storage=storage)
    assert check is not None
    assert check.id == "stock_sources" and check.level == "ok"
    assert "CC BY-SA 4.0" in check.message and "署名" in check.message


def test_stock_sources_check_skips_when_nothing_to_credit() -> None:
    from types import SimpleNamespace

    from onetake_api.modules.video_plan.gate import stock_sources_check

    assert stock_sources_check(segments=[SimpleNamespace(candidates=[_candidate("wan-i2v", "x/video.mp4")])], storage=_FakeStorage({})) is None
    # 有素材候选但 sidecar 读不到 → 跳过（不阻断、也不伪装）
    missing = [SimpleNamespace(candidates=[_candidate("stock:wikimedia", "x/video.mp4")])]
    assert stock_sources_check(segments=missing, storage=_FakeStorage({})) is None