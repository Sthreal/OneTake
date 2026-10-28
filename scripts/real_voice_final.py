"""A 项：产出一条「带真实语音」的成片（真实 CosyVoice 配音 → 本地合成）。

    python scripts/real_voice_final.py --project prj_xxx            # dry-run，不产生任何付费调用
    python scripts/real_voice_final.py --project prj_xxx --execute   # 真正调一次 CosyVoice
    python scripts/real_voice_final.py --project prj_xxx --audio-file voice.wav   # 复用已有配音，0 费用

安全约束：`MOCK_PROVIDERS=true` 或配音 provider 落到 mock 时直接拒绝运行
（避免把 mock 音频当成「真实语音」证据）。

链路（两步都是产品代码本身，不是复刻）：
1. `VoiceApplicationService._adapter()` 选出的真实 `CosyVoiceV2Adapter.synthesize` → 真实 WAV
2. `LocalCompositionAdapter.compose` → 混音(loudnorm I=-14) → 字幕 → native-feel → AIGC 标识

判据不是「容器里有音轨」，而是：**音轨码率 > 0 且 volumedetect 实测 mean_volume 明显高于静音底噪**。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import wave
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# .env 里的 DATABASE_URL / MINIO_ENDPOINT 是容器内部主机名，宿主机跑脚本要覆盖成 localhost。
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://onetake:onetake_dev_password@localhost:5432/onetake")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_SECURE", "false")

from imageio_ffmpeg import get_ffmpeg_exe  # noqa: E402

from onetake_api.config import get_settings  # noqa: E402
from onetake_api.integrations.media.local_composer import LocalCompositionAdapter  # noqa: E402
from onetake_api.integrations.media.video_utils import (  # noqa: E402
    concatenate_videos,
    inspect_video_dimensions,
    inspect_video_duration,
)
from onetake_api.integrations.mock_video.renderer import validate_final_video  # noqa: E402
from onetake_api.integrations.object_storage.dependencies import get_object_storage  # noqa: E402
from onetake_api.modules.composition.port import CompositionRequest  # noqa: E402
from onetake_api.modules.content_plan.public import ContentPlanPublicService  # noqa: E402
from onetake_api.modules.content_qa.contact_sheet import build_contact_sheet, splice_timestamps  # noqa: E402
from onetake_api.modules.content_qa.public import ContentQaPublicService  # noqa: E402
from onetake_api.modules.subtitle.public import SubtitlePublicService  # noqa: E402
from onetake_api.modules.video_plan.gate import build_gate_report  # noqa: E402
from onetake_api.modules.video_plan.public import VideoPlanPublicService  # noqa: E402
from onetake_api.platform.database import SessionLocal  # noqa: E402
from onetake_api.platform.ids import new_id  # noqa: E402

OUT_DIR = Path(r"D:\download new\ai_coding\onetake-batch3")
WIDTH, HEIGHT, FPS = 1080, 1920, 30

# 与前端 VoicePanel 的可选音色一致（避免脚本里写一个前端给不出的音色）
ALLOWED_VOICES = {"longxiaochun_v2", "longwan_v2", "longcheng_v2"}
SILENCE_THRESHOLD_DB = -50.0
MAX_TARGET_SECONDS = 180.0

DEFAULT_TEXT = (
    "姐妹们，这支口红真的绝了。丝绒质地，上嘴一秒显白，黄皮也能稳稳驾驭。"
    "薄涂是清透的豆沙色，厚涂是高级的正红色。一整天不干不拔，吃饭喝水都不掉色，"
    "补涂一次就能撑到晚上。现在下单还送同色系唇线笔，喜欢的姐妹赶紧冲。"
)


def _wav_duration_seconds(audio: bytes) -> tuple[float, float]:
    """返回 (可信时长, 头部自报时长)。

    CosyVoice 返回的是**流式 WAV**：RIFF 头里的 data 长度是占位值，`getnframes()` 可能是真实
    值的几万倍（实测 20.9s 的音频自报 22369s）。所以按字节数反推实际帧数，只有头部不自相矛盾的
    时候才信头部 —— 与 CosyVoiceV2Adapter 内部用的是同一套判据。
    """
    with wave.open(BytesIO(audio), "rb") as handle:
        frame_rate = float(handle.getframerate())
        declared_frames = handle.getnframes()
        bytes_per_frame = max(1, handle.getnchannels() * handle.getsampwidth())
    actual_frames = max(0, len(audio) - 44) // bytes_per_frame
    declared = declared_frames / frame_rate
    trust_declared = declared_frames <= actual_frames * 2
    return (round(declared, 3) if trust_declared else round(actual_frames / frame_rate, 3)), round(declared, 3)


def _chain_steps():
    """复用 real_chain_steps.py 里的取片辅助函数（避免复制粘贴两份）。"""
    spec = importlib.util.spec_from_file_location("real_chain_steps", REPO_ROOT / "scripts" / "real_chain_steps.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_text(args) -> str:
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8").strip()
    if args.text:
        return args.text.strip()
    return DEFAULT_TEXT


def _resolve_voice_adapter():
    """走产品自己的适配器选择逻辑，确保拿到的是真实 CosyVoice（否则拒绝跑）。"""
    from onetake_api.modules.voice.service import _adapter

    adapter = _adapter()
    if getattr(adapter, "provider_name", "") != "cosyvoice-v2":
        raise SystemExit(
            f"当前配音 provider = {getattr(adapter, 'provider_name', '?')}，不是真实 CosyVoice；"
            "请确认 .env 里 MOCK_PROVIDERS=false、VOICE_PROVIDER=real"
        )
    return adapter


def _audio_facts(video_bytes: bytes) -> dict:
    """ffprobe 级事实：音轨 codec/码率 + volumedetect 实测电平（用来证明「真有声音」）。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        video_path = root / "in.mp4"
        video_path.write_bytes(video_bytes)
        probe = subprocess.run(
            [get_ffmpeg_exe(), "-hide_banner", "-i", str(video_path), "-f", "null", "-"],
            check=False, capture_output=True, text=True,
        )
        audio_line = next((line.strip() for line in probe.stderr.splitlines() if " Audio: " in line), "")
        level = subprocess.run(
            [get_ffmpeg_exe(), "-hide_banner", "-i", str(video_path), "-vn", "-af", "volumedetect", "-f", "null", "-"],
            check=False, capture_output=True, text=True,
        )

    def _value(marker: str) -> float | None:
        for line in level.stderr.splitlines():
            if marker in line:
                try:
                    return float(line.split(":")[-1].strip().split(" ")[0])
                except (ValueError, IndexError):
                    return None
        return None

    return {
        "has_audio_stream": bool(audio_line),
        "audio_stream": audio_line,
        "mean_volume_db": _value("mean_volume"),
        "max_volume_db": _value("max_volume"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="", help="要配音并合成的项目 id（缺省取 a/b/c 日志里的项目）")
    parser.add_argument("--text", default="", help="配音文案（缺省用内置带货文案）")
    parser.add_argument("--text-file", default="", help="从文件读配音文案（优先于 --text）")
    parser.add_argument("--voice", default="longxiaochun_v2", help="音色，须在前端可选列表内")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--seconds", type=float, default=0.0, help="成片时长；0 = 自动贴合配音时长")
    parser.add_argument("--audio-file", default="", help="复用已有 WAV 配音（跳过付费调用，0 费用）")
    parser.add_argument("--execute", action="store_true", help="真正调用付费配音接口（缺省 dry-run）")
    args = parser.parse_args()

    settings = get_settings()
    if args.voice not in ALLOWED_VOICES:
        raise SystemExit(f"音色 {args.voice} 不在前端可选列表 {sorted(ALLOWED_VOICES)} 内")
    if settings.mock_providers:
        raise SystemExit("MOCK_PROVIDERS=true：拒绝把 mock 配音当成真实语音证据")
    if settings.composition_provider != "local":
        raise SystemExit(f"COMPOSITION_PROVIDER={settings.composition_provider}，本脚本只验证本地合成链路")

    steps_module = _chain_steps()
    text = _load_text(args)
    chars = len(text.replace("\n", ""))
    reuse = Path(args.audio_file) if args.audio_file else None

    print(f"[A] 真实配音 → 本地合成｜voice={args.voice} speed={args.speed} 文案 {chars} 字")
    print(f"    voice_provider={settings.voice_provider} model={settings.voice_model} composition={settings.composition_provider}")
    if reuse is not None:
        print(f"    复用配音文件（0 费用）：{reuse}")
    elif not args.execute:
        print(f"    dry-run：将调用 CosyVoice V2 合成 1 次（按字符计费，本次仅 {chars} 字，费用可忽略，以阿里云账单为准）")
        print("    要真正执行：追加 --execute；已有 WAV 则用 --audio-file 复用")
        return 0

    started = time.time()
    log: dict = {"started_at": datetime.now(UTC).isoformat(), "steps": {}}
    session = SessionLocal()
    try:
        storage = get_object_storage()
        project_id = args.project or steps_module._last_project_id()
        if not project_id:
            raise SystemExit("需要 --project，或先跑过 a/b/c 生成日志")
        log["project_id"] = project_id
        print(f"    项目：{project_id}")

        # ---- 1) 真实 CosyVoice 配音（唯一的付费调用，可用 --audio-file 复用）----
        if reuse is not None:
            voice_bytes = reuse.read_bytes()
            tts_seconds, header_seconds = _wav_duration_seconds(voice_bytes)
            voice_key = None
            provider_name = "cosyvoice-v2"
            print(f"\n[1/3] 复用配音：{tts_seconds:.2f}s｜{len(voice_bytes) / 1024:.0f}KB")
        else:
            print("\n[1/3] 真实 CosyVoice V2 配音 …")
            t0 = time.time()
            adapter = _resolve_voice_adapter()
            provider_name = adapter.provider_name
            result = adapter.synthesize(text=text, voice_id=args.voice, language="zh", speed=args.speed)
            voice_bytes = result.audio_bytes
            tts_seconds, header_seconds = _wav_duration_seconds(voice_bytes)
            if header_seconds > tts_seconds * 2:
                print(f"    注意：WAV 头自报 {header_seconds:.0f}s，按字节数实为 {tts_seconds:.2f}s"
                      "（CosyVoice 流式 WAV 头长度是占位值，已按字节反推）")
            run_id = new_id("voi")
            voice_key = f"projects/{project_id}/voice/{run_id}/voice.wav"
            storage.put_bytes(object_key=voice_key, content=voice_bytes, mime_type=result.mime_type)
            print(f"    配音完成：{tts_seconds:.2f}s｜{len(voice_bytes) / 1024:.0f}KB｜耗时 {time.time() - t0:.1f}s")
            log["steps"]["voice"] = {
                "provider": provider_name, "model": settings.voice_model, "voice_id": args.voice,
                "language": "zh", "speed": args.speed, "chars": chars, "text": text,
                "duration_seconds": tts_seconds, "wav_header_seconds": header_seconds,
                "size_kb": round(len(voice_bytes) / 1024, 1), "object_key": voice_key,
                "seconds": round(time.time() - t0, 1),
                "cost_cny": f"按字符计费，本次 {chars} 字，可忽略（以阿里云账单为准）",
            }
            (OUT_DIR if OUT_DIR.exists() else OUT_DIR.parent).mkdir(parents=True, exist_ok=True)
            (OUT_DIR / "voice.wav").write_bytes(voice_bytes)

        # ---- 2) 底片：用已采用的分段候选循环到目标时长（与 step e 同一条取片逻辑）----
        target = float(args.seconds) if args.seconds > 0 else max(2.0, tts_seconds)
        if target > MAX_TARGET_SECONDS:
            raise SystemExit(f"目标时长 {target:.1f}s 超过上限 {MAX_TARGET_SECONDS:.0f}s，拒绝继续（防止无界循环）")
        steps_module._accept_latest_candidates(session, project_id)
        clips = steps_module._accepted_clips(session, storage, project_id)
        if not clips:
            raise SystemExit("该项目没有已采用的分段候选，先跑 a/b/c/d")
        clip_seconds = [round(inspect_video_duration(clip), 2) for clip in clips]
        if any(seconds <= 0 for seconds in clip_seconds):
            raise SystemExit(f"分段候选时长异常：{clip_seconds}")
        looped: list[bytes] = []
        total = 0.0
        while total < target:
            for clip, seconds in zip(clips, clip_seconds):
                looped.append(clip)
                total += seconds
                if total >= target:
                    break
        base = concatenate_videos(clips=looped, duration_seconds=target, fps=FPS)
        print(f"\n[2/3] 底片：{len(clips)} 个候选（{[f'{s}s' for s in clip_seconds]}）循环 {len(looped)} 段 → {target:.2f}s")

        # ---- 3) 本地合成（混音 + 字幕 + native-feel + AIGC 标识）----
        print("\n[3/3] 本地合成（混音 → 字幕 → native-feel → AIGC 标识）…")
        t0 = time.time()
        subtitle = SubtitlePublicService().latest(session, project_id)
        srt = b"".join(storage.read_object(object_key=subtitle.srt_object_key)) if subtitle and subtitle.srt_object_key else None
        final = LocalCompositionAdapter().compose(CompositionRequest(
            base_video_bytes=base, audio_bytes=voice_bytes, srt_bytes=srt,
            duration_seconds=target, width=WIDTH, height=HEIGHT, fps=FPS,
        ))
        metadata = validate_final_video(
            final, expected_width=WIDTH, expected_height=HEIGHT, expected_fps=FPS, expected_audio=True,
        )
        plan = VideoPlanPublicService().latest(session, project_id).plan
        report = ContentQaPublicService().evaluate_candidate(
            session, project_id=project_id, video_plan_id=plan.id if plan else "vid_manual",
            video_bytes=final, metadata=metadata, expected_audio=True,
            subtitle_embedded=srt is not None, product_layered=True,
        )
        content_plan = ContentPlanPublicService().latest(session, project_id)
        boundaries = [
            scene.end_seconds
            for scene in content_plan.variants[content_plan.selected_variant_index].scenes[:-1]
        ] if content_plan else []
        sheet = build_contact_sheet(final, timestamps=splice_timestamps(boundaries, duration_seconds=target))
        gate = build_gate_report(
            session, project_id=project_id, video_bytes=final, contact_sheet_url="local://contact-sheet.png",
            width=WIDTH, height=HEIGHT, composition_provider="local-ffmpeg",
        )

        facts = _audio_facts(final)
        voiced = (
            facts["has_audio_stream"]
            and facts["mean_volume_db"] is not None
            and facts["mean_volume_db"] > SILENCE_THRESHOLD_DB
        )

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "final-with-voice.mp4").write_bytes(final)
        (OUT_DIR / "voice-contact-sheet.png").write_bytes(sheet)
        log["steps"]["compose"] = {
            "clips_used": len(clips), "clip_seconds": clip_seconds, "looped_clips": len(looped),
            "target_seconds": round(target, 2), "audio_seconds": tts_seconds,
            "size": list(inspect_video_dimensions(final)), "duration": round(inspect_video_duration(final), 2),
            "size_mb": round(len(final) / 1024 / 1024, 2),
            "qa_status": report.status, "qa_score": report.score, "qa_signals": report.signals,
            "gate_status": gate.status,
            "gate_checks": [{"id": item.id, "level": item.level} for item in gate.checks],
            "audio_facts": facts, "has_real_voice": voiced, "seconds": round(time.time() - t0, 1),
            "cost_cny": 0.0,
        }
        print(f"    成片：{inspect_video_dimensions(final)} {inspect_video_duration(final):.2f}s "
              f"{len(final) / 1024 / 1024:.2f}MB｜耗时 {time.time() - t0:.1f}s")
        print(f"    音轨：{facts['audio_stream'] or '（无音轨）'}")
        print(f"    实测电平：mean={facts['mean_volume_db']}dB max={facts['max_volume_db']}dB"
              f"（静音阈值 {SILENCE_THRESHOLD_DB}dB）→ {'有真实语音 ✔' if voiced else '疑似静音 ✘'}")
        print(f"    质检={report.status}({report.score})｜交付门={gate.status}")
        print("    质检信号：" + json.dumps(report.signals, ensure_ascii=False))
        print(f"    产物：{OUT_DIR / 'final-with-voice.mp4'}、{OUT_DIR / 'voice.wav'}、{OUT_DIR / 'voice-contact-sheet.png'}")
        if not voiced:
            print("    ⚠ 未检出有效语音电平：本次产物不能作为「带语音成片」的证据")
    finally:
        session.close()

    log["total_seconds"] = round(time.time() - started, 1)
    log["finished_at"] = datetime.now(UTC).isoformat()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "steps-voice.json"
    out.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print("-" * 74)
    print(f"总耗时 {log['total_seconds']}s｜明细已写入：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())