"""批次 3（G1）：真实供应商链路 a/b/c 三步验证（每步留档 + 费用对账）。

    python scripts/real_chain_steps.py --product <商品图.png> --steps a,b,c --execute

不带 `--execute` 时是 dry-run：只打印将要做什么与预估费用，不产生任何调用。
安全约束：`MOCK_PROVIDERS=true` 时直接拒绝运行（避免把 mock 结果当成真实链路证据）。

a = 单镜关键帧（qwen-image-2.0-pro，1 张）
b = 1 段 i2v（wan2.6-i2v-flash，首帧 = 已采用关键帧）
c = 1 段 kf2v（wan2.2-kf2v-flash，首帧/尾帧 = 相邻两镜关键帧）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import wave
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# .env 里的 DATABASE_URL / MINIO_ENDPOINT 是给容器内部用的主机名（postgres / minio），
# 宿主机跑这个脚本要覆盖成 localhost —— 进程环境变量优先于 .env 文件。
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://onetake:onetake_dev_password@localhost:5432/onetake")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_SECURE", "false")

from PIL import Image  # noqa: E402

from onetake_api.config import Settings  # noqa: E402
from onetake_api.integrations.media.local_composer import LocalCompositionAdapter  # noqa: E402
from onetake_api.integrations.media.video_utils import (  # noqa: E402
    concatenate_videos,
    inspect_video_dimensions,
    inspect_video_duration,
)
from onetake_api.integrations.mock_video.renderer import validate_final_video  # noqa: E402
from onetake_api.modules.composition.port import CompositionRequest  # noqa: E402
from onetake_api.modules.content_plan.public import ContentPlanPublicService  # noqa: E402
from onetake_api.modules.content_qa.contact_sheet import build_contact_sheet, splice_timestamps  # noqa: E402
from onetake_api.modules.content_qa.public import ContentQaPublicService  # noqa: E402
from onetake_api.modules.subtitle.public import SubtitlePublicService  # noqa: E402
from onetake_api.modules.video_plan.gate import build_gate_report  # noqa: E402
from onetake_api.modules.video_plan.public import VideoPlanPublicService  # noqa: E402
from onetake_api.modules.voice.public import VoicePublicService  # noqa: E402
from onetake_api.integrations.object_storage.dependencies import get_object_storage  # noqa: E402
from onetake_api.modules.content_plan.domain import (  # noqa: E402
    STATUS_CONFIRMED,
    ContentPlan,
    ContentScene,
    ContentVariant,
)
from onetake_api.modules.content_plan.repository import ContentPlanRepository  # noqa: E402
from onetake_api.modules.main_image.domain import MainImageVersion  # noqa: E402
from onetake_api.modules.main_image.repository import MainImageRepository  # noqa: E402
from onetake_api.modules.pipeline.public import PipelinePublicService  # noqa: E402
from onetake_api.modules.project.public import ProjectPublicService  # noqa: E402
from onetake_api.modules.subtitle.domain import SUBTITLE_CONFIRMED, SubtitleVersion  # noqa: E402
from onetake_api.modules.subtitle.repository import SubtitleRepository  # noqa: E402
from onetake_api.modules.video_plan.keyframe_service import VideoKeyframeApplicationService  # noqa: E402
from onetake_api.modules.video_plan.segment_public import VideoSegmentPublicService  # noqa: E402
from onetake_api.modules.video_plan.service import VideoPlanApplicationService  # noqa: E402
from onetake_api.modules.voice.domain import VOICE_CONFIRMED, VoiceRun  # noqa: E402
from onetake_api.modules.voice.repository import VoiceRepository  # noqa: E402
from onetake_api.platform.database import SessionLocal  # noqa: E402
from onetake_api.platform.ids import new_id  # noqa: E402

SCENE_SECONDS = 5.0
OFFICIAL_PRICES = {"i2v_1080p": 0.5, "kf2v_1080p": 0.48, "image_per_piece": 0.5}


def _price(value) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _product_png(path: Path) -> bytes:
    with Image.open(path) as source:
        image = source.convert("RGBA")
    if "A" not in source.mode:
        raise SystemExit(f"商品图需要带透明通道（当前 {source.mode}）：{path}")
    box = image.getbbox()
    if box:
        image = image.crop(box)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _silent_wav(seconds: float) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(b"\x00\x00" * int(48000 * seconds))
    return buffer.getvalue()


def _scene(order: int, start: float) -> ContentScene:
    return ContentScene(
        scene_id=f"scene_{order}", order=order, purpose="展示", script_excerpt=f"第{order}句台词",
        start_seconds=start, end_seconds=start + SCENE_SECONDS, shot_type="medium", prompt="",
        overlay_product=True, product_position="center", background_style="clean", template_id="clean",
        subtitle_segment_ids=[order], qa_rules=[], visual_goal="product_reveal", subject_action="展示商品",
        camera_move="push_in", product_mode="integrated", transition="fade",
    )


def seed(session, storage, product_png: bytes, label: str) -> str:
    project = ProjectPublicService().create_project(session, product_name=label, product_note="真实链路验证")
    now = datetime.now(UTC)
    image_key = f"projects/{project.id}/main.png"
    voice_key = f"projects/{project.id}/voice.wav"
    srt_key = f"projects/{project.id}/subtitle.srt"
    storage.put_bytes(object_key=image_key, content=product_png, mime_type="image/png")
    storage.put_bytes(object_key=voice_key, content=_silent_wav(SCENE_SECONDS * 2), mime_type="audio/wav")
    storage.put_bytes(
        object_key=srt_key,
        content=f"1\n00:00:00,000 --> 00:00:{int(SCENE_SECONDS):02d},000\n真实链路验证字幕\n".encode("utf-8"),
        mime_type="application/x-subrip",
    )
    MainImageRepository().add(session, MainImageVersion(
        new_id("miv"), project.id, new_id("ast"), "confirmed", new_id("edt"), new_id("mat"), image_key, None,
        2000, 2000, 1000, 1000, 1000, 0.82, None, now, now, now, now,
    ))
    VoiceRepository().add(session, VoiceRun(
        new_id("voi"), project.id, new_id("scr"), VOICE_CONFIRMED, True, True, "mock", "cosyvoice-v2",
        "female", "zh", 1.0, "真实链路验证。", voice_key, "audio/wav", SCENE_SECONDS * 2, [], None,
        now, now, now, now,
    ))
    SubtitleRepository().add(session, SubtitleVersion(
        new_id("sub"), project.id, new_id("scr2"), new_id("voi2"), SUBTITLE_CONFIRMED, True, "zh",
        [{"index": 1, "text": "真实链路验证字幕", "start": 0, "end": SCENE_SECONDS}], srt_key, None,
        now, now, now, now,
    ))
    PipelinePublicService().mark_audio_subtitle_confirmed(session, project.id)
    ContentPlanRepository().add(session, ContentPlan(
        id=new_id("cpl"), project_id=project.id, script_version_id=new_id("scr3"), subtitle_version_id=new_id("sub3"),
        status=STATUS_CONFIRMED, provider="rules", model="rules-v1",
        variants=[ContentVariant("var_real", "标准", "clean", [_scene(1, 0.0), _scene(2, SCENE_SECONDS)])],
        selected_variant_index=0, total_duration_seconds=SCENE_SECONDS * 2, error_code=None,
        created_at=now, updated_at=now, confirmed_at=now,
    ))
    session.commit()
    return project.id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", default="", help="带透明通道的商品 PNG（a/b/c 需要；纯 e 可省略）")
    parser.add_argument("--steps", default="a,b,c")
    parser.add_argument("--execute", action="store_true", help="真正调用付费接口（缺省为 dry-run）")
    parser.add_argument("--label", default="真实链路验证")
    parser.add_argument("--project", default="", help="step e 要合成的项目 id（缺省取上一次 a/b/c 的日志）")
    parser.add_argument("--e-seconds", type=float, default=18.0, help="step e 成片目标时长")
    parser.add_argument("--plan-only", action="store_true", help="step d：只做零费用预检（打印将发出的请求与费用），不调用供应商")
    args = parser.parse_args()

    settings = Settings()
    steps = [item.strip().lower() for item in args.steps.split(",") if item.strip()]
    product_path = Path(args.product) if args.product else None

    image_price = _price(settings.qwen_image_price_per_call)
    i2v_price = _price(settings.wan_i2v_price_per_second)
    kf2v_price = _price(settings.wan_kf2v_price_per_second)
    estimate = {
        "a": f"1 张关键帧 × {image_price} = {round((image_price or 0) * 1, 2)} 元（官方 1080P ≈ {OFFICIAL_PRICES['image_per_piece']} 元/张）",
        "b": f"1 段 {SCENE_SECONDS:.0f}s i2v × {i2v_price} = {round((i2v_price or 0) * SCENE_SECONDS, 2)} 元（官方 1080P ≈ {round(OFFICIAL_PRICES['i2v_1080p'] * SCENE_SECONDS, 2)} 元）",
        "c": f"1 段 {SCENE_SECONDS:.0f}s kf2v × {kf2v_price} = {round((kf2v_price or 0) * SCENE_SECONDS, 2)} 元（官方 1080P ≈ {round(OFFICIAL_PRICES['kf2v_1080p'] * SCENE_SECONDS, 2)} 元）",
    }
    print("=" * 74)
    print(f"批次 3 · 真实链路 a/b/c｜步骤：{steps}｜执行：{'是' if args.execute else '否（dry-run）'}")
    print("=" * 74)
    for step in steps:
        if step in estimate:
            print(f"  {step}: {estimate[step]}")
    print("-" * 74)

    if settings.mock_providers:
        print("❌ MOCK_PROVIDERS=true：这里拒绝运行（否则会用 mock 结果冒充真实链路证据）")
        return 2
    if not settings.dashscope_api_key:
        print("❌ 缺少 DASHSCOPE_API_KEY")
        return 2
    if not args.execute:
        print("（dry-run 结束。加 --execute 才会真正调用付费接口）")
        return 0

    storage = get_object_storage()
    session = SessionLocal()
    log: dict = {"started_at": datetime.now(UTC).isoformat(), "steps": {}, "product": str(product_path)}
    started = time.time()
    try:
        needs_seed = bool({"a", "b", "c"} & set(steps))
        if needs_seed:
            if product_path is None or not product_path.is_file():
                raise SystemExit(f"商品图不存在：{args.product}")
            product_png = _product_png(product_path)
            project_id = seed(session, storage, product_png, args.label)
            print(f"项目：{project_id}｜商品图：{path_display(product_path)}")
        else:
            # 纯 e：复用已有项目（a/b/c 跑出来的那个），不新建、不产生任何调用
            project_id = args.project or _last_project_id()
            if not project_id:
                raise SystemExit("纯 e 需要 --project，或先跑过 a/b/c 以生成日志")
            print(f"项目：{project_id}（复用已有项目，不新建）")
        log["project_id"] = project_id

        keyframes = VideoKeyframeApplicationService(storage=storage)
        video = VideoPlanApplicationService(storage=storage, composition=LocalCompositionAdapter())

        if "a" in steps:
            print("\n[a] 生成 scene_1 关键帧（1 张候选）…")
            t0 = time.time()
            keyframes.generate_candidate(session, project_id=project_id, scene_id="scene_1", n=1)
            candidates = [item for item in keyframes.list_candidates(session, project_id=project_id) if item.scene_id == "scene_1"]
            latest = candidates[-1]
            keyframes.accept_candidate(session, project_id=project_id, keyframe_id=latest.id)
            log["steps"]["a"] = {
                "keyframe_id": latest.id, "status": latest.status, "provider": latest.provider,
                "seed": latest.seed, "product_match": latest.product_match, "text_intact": latest.text_intact,
                "fallback": latest.fallback, "issues": list(latest.issues),
                "size": [latest.width, latest.height], "seconds": round(time.time() - t0, 1),
                "cost_cny": image_price,
            }
            print(f"    结果：status={latest.status} product_match={latest.product_match} text_intact={latest.text_intact} "
                  f"fallback={latest.fallback} size={latest.width}x{latest.height} 耗时 {time.time() - t0:.1f}s")
            if latest.issues:
                print(f"    issues：{'；'.join(latest.issues)}")

        if "b" in steps or "c" in steps:
            plan = video.create_plan(session, project_id=project_id, mode="product", template_id="clean", path="segmented").plan
            segments = VideoSegmentPublicService().materialize_segments(session, project_id=project_id)
            segment = segments[0]

        if "b" in steps:
            print(f"\n[b] 生成第 1 段 i2v 候选（{SCENE_SECONDS:.0f}s，锚点=已采用关键帧）…")
            t0 = time.time()
            refreshed = VideoSegmentPublicService().generate_candidate(
                session, project_id=project_id, segment_id=segment.id
            )
            candidate = refreshed[0].candidates[-1]
            video_bytes = b"".join(storage.read_object(object_key=candidate.video_object_key))
            log["steps"]["b"] = {
                "candidate_id": candidate.id, "provider": candidate.provider, "anchor_source": candidate.anchor_source,
                "seed": candidate.seed, "size": list(inspect_video_dimensions(video_bytes)),
                "duration": round(inspect_video_duration(video_bytes), 2), "seconds": round(time.time() - t0, 1),
                "cost_cny": round((i2v_price or 0) * SCENE_SECONDS, 2),
            }
            print(f"    结果：provider={candidate.provider} anchor={candidate.anchor_source} "
                  f"size={inspect_video_dimensions(video_bytes)} duration={inspect_video_duration(video_bytes):.2f}s "
                  f"耗时 {time.time() - t0:.1f}s")

        if "c" in steps:
            print("\n[c] 生成 scene_2 关键帧并采用，然后重做第 1 段（期望走 kf2v 首尾帧）…")
            t0 = time.time()
            keyframes.generate_candidate(session, project_id=project_id, scene_id="scene_2", n=1)
            scene2 = [item for item in keyframes.list_candidates(session, project_id=project_id) if item.scene_id == "scene_2"][-1]
            keyframes.accept_candidate(session, project_id=project_id, keyframe_id=scene2.id)
            refreshed = VideoSegmentPublicService().generate_candidate(session, project_id=project_id, segment_id=segment.id)
            candidate = refreshed[0].candidates[-1]
            video_bytes = b"".join(storage.read_object(object_key=candidate.video_object_key))
            log["steps"]["c"] = {
                "keyframe2_id": scene2.id, "keyframe2_status": scene2.status,
                "candidate_id": candidate.id, "provider": candidate.provider, "anchor_source": candidate.anchor_source,
                "seed": candidate.seed, "size": list(inspect_video_dimensions(video_bytes)),
                "duration": round(inspect_video_duration(video_bytes), 2), "seconds": round(time.time() - t0, 1),
                "cost_cny": round((kf2v_price or 0) * SCENE_SECONDS + (image_price or 0), 2),
            }
            print(f"    结果：scene_2 关键帧 status={scene2.status} product_match={scene2.product_match}｜"
                  f"段候选 provider={candidate.provider} anchor={candidate.anchor_source} "
                  f"size={inspect_video_dimensions(video_bytes)} duration={inspect_video_duration(video_bytes):.2f}s "
                  f"耗时 {time.time() - t0:.1f}s")
        if "d" in steps:
            print("\n[d] r2v 整片一次生成…")
            d_project = args.project or project_id or _last_project_id()
            if not d_project:
                raise SystemExit("step d 需要 --project，或先跑过 a/b/c")
            content_plan = ContentPlanPublicService().latest(session, d_project)
            if content_plan is None:
                raise SystemExit("该项目没有已确认分镜，无法走整片路径")
            variant = content_plan.variants[content_plan.selected_variant_index]
            from onetake_api.modules.video_plan.one_shot import keyframe_refs_for_call, plan_one_shot_calls

            calls = plan_one_shot_calls(variant.scenes, max_seconds=settings.wan_r2v_max_seconds)
            keyframes = _accepted_keyframe_map(session, storage, d_project)
            r2v_price = _price(settings.wan_r2v_price_per_second) or 0.0
            total_seconds = sum(call.duration_seconds for call in calls)
            print(f"    分镜合计 {sum(s.end_seconds - s.start_seconds for s in variant.scenes):.0f}s → "
                  f"r2v 切分 {len(calls)} 次调用 / {total_seconds:.0f}s")
            for call in calls:
                refs = keyframe_refs_for_call(call, keyframes)
                print(f"      第 {call.order} 次：{call.duration_seconds:.0f}s，参考图 {len(refs)} 张"
                      f"（{', '.join(call.scene_ids)}）→ {call.duration_seconds * r2v_price:.2f} 元")
            print(f"    预计费用合计 {total_seconds * r2v_price:.2f} 元（单价 {r2v_price} 元/秒 × {total_seconds:.0f}s）")
            missing = [scene.scene_id for scene in variant.scenes if scene.scene_id not in keyframes]
            if missing:
                print(f"    ⚠️ 以下分镜还没有已采用关键帧，真实调用会在此之前失败：{', '.join(missing)}")
            if args.plan_only:
                print("    （--plan-only：零费用预检结束，未调用供应商）")
            else:
                plan_view = video.create_plan(session, project_id=d_project, mode="product", template_id="clean", path="one_shot").plan
                t0 = time.time()
                final = video._create_one_shot_video(session, plan_view)
                out_dir = Path(r"D:\download new\ai_coding\onetake-batch3")
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "r2v-one-shot.mp4").write_bytes(final)
                log["steps"]["d"] = {
                    "project_id": d_project, "calls": len(calls), "seconds": total_seconds,
                    "size": list(inspect_video_dimensions(final)), "duration": round(inspect_video_duration(final), 2),
                    "elapsed_seconds": round(time.time() - t0, 1), "cost_cny": round(total_seconds * r2v_price, 2),
                }
                print(f"    结果：{inspect_video_dimensions(final)} {inspect_video_duration(final):.2f}s｜耗时 {time.time() - t0:.1f}s"
                      f"｜产物 {out_dir / 'r2v-one-shot.mp4'}")

        if "e" in steps:
            print(f"\n[e] 本地合成（{args.e_seconds:.0f}s）…")
            t0 = time.time()
            e_project = args.project or project_id or _last_project_id()
            if not e_project:
                raise SystemExit("step e 需要 --project，或先跑过 a/b/c 以生成本地日志")
            _accept_latest_candidates(session, e_project)  # 免费：把各段最新 ready 候选置为已采用，便于合成
            clips = _accepted_clips(session, storage, e_project)
            if not clips:
                raise SystemExit("该项目的分段没有已采用候选，先跑 a/b/c")
            per_loop = sum(len(clip) for clip in clips)  # 仅用于日志
            target = float(args.e_seconds)
            looped: list[bytes] = []
            total = 0.0
            while total < target:
                for clip in clips:
                    looped.append(clip)
                    total += inspect_video_duration(clip)
                    if total >= target:
                        break
            base = concatenate_videos(clips=looped, duration_seconds=target, fps=30)

            voice = VoicePublicService().latest(session, e_project)
            subtitle = SubtitlePublicService().latest(session, e_project)
            audio = b"".join(storage.read_object(object_key=voice.run.audio_object_key)) if voice.run and voice.run.audio_object_key else None
            srt = b"".join(storage.read_object(object_key=subtitle.srt_object_key)) if subtitle and subtitle.srt_object_key else None
            final = LocalCompositionAdapter().compose(CompositionRequest(
                base_video_bytes=base, audio_bytes=audio, srt_bytes=srt,
                duration_seconds=target, width=1080, height=1920, fps=30,
            ))
            metadata = validate_final_video(
                final, expected_width=1080, expected_height=1920, expected_fps=30, expected_audio=audio is not None,
            )
            plan = VideoPlanPublicService().latest(session, e_project).plan
            report = ContentQaPublicService().evaluate_candidate(
                session, project_id=e_project, video_plan_id=plan.id if plan else "vid_manual",
                video_bytes=final, metadata=metadata, expected_audio=audio is not None,
                subtitle_embedded=srt is not None, product_layered=True,
            )
            content_plan = ContentPlanPublicService().latest(session, e_project)
            boundaries = [scene.end_seconds for scene in content_plan.variants[content_plan.selected_variant_index].scenes[:-1]] if content_plan else []
            sheet = build_contact_sheet(final, timestamps=splice_timestamps(boundaries, duration_seconds=target))
            gate = build_gate_report(
                session, project_id=e_project, video_bytes=final, contact_sheet_url="local://contact-sheet.png",
                width=1080, height=1920, composition_provider="local-ffmpeg",
            )
            out_dir = Path(r"D:\download new\ai_coding\onetake-batch3")
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "final-18s-local.mp4").write_bytes(final)
            (out_dir / "final-contact-sheet.png").write_bytes(sheet)
            log["steps"]["e"] = {
                "project_id": e_project, "clips_used": len(clips), "looped_clips": len(looped),
                "size": list(inspect_video_dimensions(final)), "duration": round(inspect_video_duration(final), 2),
                "size_mb": round(len(final) / 1024 / 1024, 2), "qa_status": report.status, "qa_score": report.score,
                "qa_signals": report.signals, "gate_status": gate.status,
                "gate_checks": [{"id": item.id, "level": item.level} for item in gate.checks],
                "seconds": round(time.time() - t0, 1), "cost_cny": 0.0,
            }
            print(f"    结果：{inspect_video_dimensions(final)} {inspect_video_duration(final):.2f}s "
                  f"{len(final) / 1024 / 1024:.2f}MB｜质检={report.status}({report.score})｜交付门={gate.status}｜耗时 {time.time() - t0:.1f}s")
            print(f"    质检项：" + "；".join(f"{item.id}={item.level}" for item in gate.checks))
            print(f"    产物：{out_dir / 'final-18s-local.mp4'}、{out_dir / 'final-contact-sheet.png'}")

    finally:
        session.close()

    log["total_seconds"] = round(time.time() - started, 1)
    log["finished_at"] = datetime.now(UTC).isoformat()
    # 按步骤集合命名，避免不同批次互相覆盖（此前 e 运行会覆盖 a/b/c 的日志）
    out = REPO_ROOT.parent / "onetake-batch3" / ("steps-" + "-".join(steps) + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print("-" * 74)
    print(f"总耗时 {log['total_seconds']}s｜明细已写入：{out}")
    return 0


def path_display(path: Path) -> str:
    return path.name


def _last_project_id() -> str:
    log_path = Path(r"D:\download new\ai_coding\onetake-batch3\a-b-c.json")
    if not log_path.is_file():
        return ""
    try:
        return str(json.loads(log_path.read_text(encoding="utf-8")).get("project_id") or "")
    except (ValueError, OSError):
        return ""


def _accepted_clips(session, storage, project_id: str) -> list[bytes]:
    """取该项目所有「已采用」分段候选的成片，按段序返回（用于 step e 合成）。"""
    from sqlalchemy import select

    from onetake_api.modules.video_plan.segment_repository import (
        VideoSegmentCandidateModel,
        VideoSegmentModel,
    )

    clips: list[bytes] = []
    segments = session.scalars(
        select(VideoSegmentModel).where(VideoSegmentModel.project_id == project_id).order_by(VideoSegmentModel.order_index)
    ).all()
    for segment in segments:
        if not segment.accepted_candidate_id:
            continue
        candidate = session.get(VideoSegmentCandidateModel, segment.accepted_candidate_id)
        if candidate and candidate.video_object_key:
            clips.append(b"".join(storage.read_object(object_key=candidate.video_object_key)))
    return clips


def _accept_latest_candidates(session, project_id: str) -> None:
    """把每个分段的最新 ready 候选置为已采用（纯 DB 操作，不产生任何调用）。"""
    from sqlalchemy import select

    from onetake_api.modules.video_plan.segment_public import VideoSegmentPublicService
    from onetake_api.modules.video_plan.segment_repository import (
        VideoSegmentCandidateModel,
        VideoSegmentModel,
    )

    service = VideoSegmentPublicService()
    segments = session.scalars(
        select(VideoSegmentModel).where(VideoSegmentModel.project_id == project_id).order_by(VideoSegmentModel.order_index)
    ).all()
    for segment in segments:
        if segment.accepted_candidate_id:
            continue
        latest = session.scalars(
            select(VideoSegmentCandidateModel)
            .where(
                VideoSegmentCandidateModel.segment_id == segment.id,
                VideoSegmentCandidateModel.status == "ready",
            )
            .order_by(VideoSegmentCandidateModel.created_at.desc())
        ).first()
        if latest is None:
            continue
        service.accept_candidate(session, project_id=project_id, candidate_id=latest.id)


def _accepted_keyframe_map(session, storage, project_id: str) -> dict[str, bytes]:
    """scene_id → 已采用关键帧图片字节（step d 用它构造 r2v 的参考图）。"""
    from onetake_api.modules.video_plan.keyframe_repository import VideoKeyframeCandidateRepository

    result: dict[str, bytes] = {}
    for candidate in VideoKeyframeCandidateRepository().list_for_project(session, project_id):
        if candidate.status == "accepted" and candidate.image_object_key:
            result.setdefault(
                candidate.scene_id, b"".join(storage.read_object(object_key=candidate.image_object_key))
            )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
