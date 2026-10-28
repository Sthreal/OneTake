"""BGM（批次 4b：0 成本路径）。

**默认关闭**：只有 `BGM_ENABLED=true` 才会叠 BGM；且**只有存在旁白轨时才叠** ——
沿用 `local_composer` 的既有契约「用户关闭语音 → 成片必须无音轨」，不给它偷偷加音轨。

**顺序**（沿用 `local_composer` 的硬顺序纪律）：BGM 挂在混音这一步，
所以天然在 native-feel 与 AIGC 标识**之前**（那两步都在混音之后）。

**混音做法**：旁白链保持既有 `loudnorm + alimiter` **一个字不改**，外加
`sidechaincompress`（音乐被旁白压下去）+ `amix(normalize=0)` + 末尾 `alimiter`（NaN 兜底）。
音乐用 `-stream_loop -1` 循环到成片长度，末尾由外层 `-t` 兜底。

**来源（免 Key 优先）**：`BGM_TRACK_PATH` 指定的本地文件 → `assets/bgm/` 内置库 → 都没有则不叠（如实跳过，不伪造）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from onetake_api.platform.errors import DomainError

BGM_ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "bgm"
SUPPORTED_SUFFIXES = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".oga", ".opus", ".flac")
SOURCE_LOCAL_PATH = "local-path"
SOURCE_BUNDLED = "bundled"


@dataclass(frozen=True)
class BgmMixSettings:
    """混音参数（从 Settings 取，打包成不可变小对象，避免 `_mix_audio` 参数膨胀）。"""

    gain_db: float = -20.0
    duck_threshold: float = 0.03
    duck_ratio: float = 12.0

    @classmethod
    def from_settings(cls, settings) -> "BgmMixSettings":
        return cls(
            gain_db=float(getattr(settings, "bgm_gain_db", -20.0)),
            duck_threshold=float(getattr(settings, "bgm_duck_threshold", 0.03)),
            duck_ratio=float(getattr(settings, "bgm_duck_ratio", 12.0)),
        )


class BgmError(DomainError):
    code = "COMPOSITION_PROVIDER_ERROR"
    http_status = 502
    retryable = True


@dataclass(frozen=True)
class BgmTrack:
    name: str
    content: bytes
    source: str
    suffix: str = ".mp3"
    attribution: str | None = None


def available_bundled_tracks() -> list[Path]:
    if not BGM_ASSET_DIR.is_dir():
        return []
    return sorted(
        path for path in BGM_ASSET_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def resolve_bgm_track(*, settings, seed: int | None = None) -> BgmTrack | None:
    """按"本地指定 → 内置库 → 无"的顺序取一条音轨。

    - 配了 `BGM_TRACK_PATH` 但文件不存在 → **显式报错**（不静默跳过，否则用户以为叠上了）。
    - 内置库多轨时按 `seed` 稳定取模（`seed=None` 取第一条，保证默认可复现）。
    """
    configured = (getattr(settings, "bgm_track_path", "") or "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise BgmError(f"BGM_TRACK_PATH 指向的文件不存在：{configured}")
        return BgmTrack(
            name=path.name, content=path.read_bytes(), source=SOURCE_LOCAL_PATH,
            suffix=path.suffix.lower() or ".mp3",
        )
    tracks = available_bundled_tracks()
    if not tracks:
        return None
    index = 0 if seed is None else seed % len(tracks)
    picked = tracks[index]
    return BgmTrack(
        name=picked.name, content=picked.read_bytes(), source=SOURCE_BUNDLED,
        suffix=picked.suffix.lower(), attribution=picked.stem,
    )


def build_ducked_mix_filter(
    *, voice_index: int, bgm_index: int, duration_seconds: float, gain_db: float,
    threshold: float, ratio: float,
) -> str:
    """旁白链（响度部分一个字不改）+ 音乐链（循环已由 `-stream_loop` 负责，这里只裁长与控音量）+ 闪避 + 混音。

    ⚠️ 两条链都显式 `aformat=48kHz/立体声` —— **这不是装饰**：
    `loudnorm` 内部会把音频重采样到 192kHz，若把它的输出直接当 sidechain，`sidechaincompress`
    会因为两条输入格式/长度不一致而**在旁白静音处把音乐整段变成静音**（实测：尾巴 -91dB）。
    统一格式后实测尾巴 -28dB（有音乐）、旁白段与不叠 BGM 时相差 ≤0.2dB（人声不被压）。
    """
    return ";".join([
        f"[{voice_index}:a]loudnorm=I=-14:TP=-1.5:LRA=11,alimiter=limit=0.95:level=false,"
        "aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[voice][sc]",
        f"[{bgm_index}:a]atrim=0:{duration_seconds:.3f},volume={gain_db:.1f}dB,"
        "aformat=sample_rates=48000:channel_layouts=stereo[bgm]",
        f"[bgm][sc]sidechaincompress=threshold={threshold}:ratio={ratio}:attack=20:release=350[bgmduck]",
        "[voice][bgmduck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=false[a]",
    ])