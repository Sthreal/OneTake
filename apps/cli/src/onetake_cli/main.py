"""One Take 命令行（批次 7）：把既有 HTTP 端点包成命令，**不重写任何业务逻辑**。

设计约束（来自方案）：
- 只包既有端点（端点清单以 `GET /openapi.json` 为准，本文件不新增服务器行为）；
- `gate` 命令按服务端的 `download_allowed` 返回非零退出码 —— 便于接 CI / 定时任务；
- **不在 CLI 里复算业务规则**：能不能下载、要不要审批、费用多少，全部来自服务端字段。

退出码：`0` 成功｜`1` 用法/参数错误｜`2` 服务端拒绝或调用失败｜`3` 交付门未放行。

用法示例（先起服务端，再）：
    onetake project create --name "口红测试"
    onetake recognize <project_id> --confirm
    onetake plan <project_id> --confirm
    onetake keyframes <project_id> --generate <scene_id> --accept-scene <scene_id> --candidate <keyframe_id>
    onetake segments <project_id> --generate <segment_id> --accept <segment_id>
    onetake compose <project_id>
    onetake gate <project_id> --ack <check_id>
    onetake export <project_id> --profiles
    onetake export <project_id> --profile xiaohongshu --kind cover --at 0.5
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from onetake_cli.client import DEFAULT_BASE_URL, ApiClient, CliApiError

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_API_ERROR = 2
EXIT_GATE_BLOCKED = 3


class _Printer:
    """统一输出：默认人读，`--json` 打原始响应（便于接管道）。"""

    def __init__(self, *, raw: bool) -> None:
        self.raw = raw

    def payload(self, payload: dict[str, Any]) -> None:
        if self.raw:
            print(json.dumps(payload, ensure_ascii=False))
            return
        data = payload.get("data")
        if isinstance(data, dict):
            print(json.dumps(data, ensure_ascii=False, indent=1))
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=1))

    def line(self, text: str) -> None:
        if not self.raw:
            print(text)

    def missing(self, payload: dict[str, Any], expected: str) -> None:
        """响应结构与预期不同时：如实说明并打印原始响应，不假装成功也不崩。"""
        if not self.raw:
            print(f"[warn] 响应里没有 {expected}，下面是原始响应：", file=sys.stderr)
            print(json.dumps(payload, ensure_ascii=False, indent=1), file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onetake", description="One Take 命令行（只包既有 HTTP 端点）")
    parser.add_argument("--base-url", default=os.environ.get("ONETAKE_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("ONETAKE_TIMEOUT", "30")))
    parser.add_argument("--json", action="store_true", help="输出原始 JSON（便于脚本处理）")
    commands = parser.add_subparsers(dest="command", required=True)
    # `--json` 在子命令后也认（`onetake gate <id> --json` 是更常见的写法）。
    # 用 SUPPRESS 默认值：子命令没显式给时不覆盖全局那份，于是两种位置都成立。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)

    project = commands.add_parser("project", parents=[common], help="项目：创建 / 列表 / 查看")
    project.add_argument("action", choices=("create", "list", "show"))
    project.add_argument("project_id", nargs="?")
    project.add_argument("--name")
    project.add_argument("--note")

    recognize = commands.add_parser("recognize", parents=[common], help="商品识别：发起 / 确认")
    recognize.add_argument("project_id")
    recognize.add_argument("--confirm", action="store_true")

    plan = commands.add_parser("plan", parents=[common], help="内容方案：生成 / 确认")
    plan.add_argument("project_id")
    plan.add_argument("--confirm", action="store_true")

    keyframes = commands.add_parser("keyframes", parents=[common], help="关键帧：列表 / 生成候选 / 采用")
    keyframes.add_argument("project_id")
    keyframes.add_argument("--generate", metavar="SCENE_ID")
    keyframes.add_argument("--accept-scene", metavar="SCENE_ID")
    keyframes.add_argument("--candidate", metavar="KEYFRAME_ID")

    segments = commands.add_parser("segments", parents=[common], help="分段：列表 / 生成候选 / 采用 / 定向返修")
    segments.add_argument("project_id")
    segments.add_argument("--generate", metavar="SEGMENT_ID")
    segments.add_argument("--accept", metavar="SEGMENT_ID")
    segments.add_argument("--retake", metavar="SEGMENT_ID")
    segments.add_argument("--symptom")

    compose = commands.add_parser("compose", parents=[common], help="合成成片")
    compose.add_argument("project_id")

    gate = commands.add_parser("gate", parents=[common], help="交付门结论（未放行时退出码 3）")
    gate.add_argument("project_id")
    gate.add_argument("--ack", action="append", default=[], metavar="CHECK_ID")

    export = commands.add_parser("export", parents=[common], help="多平台导出：档位 / 导出视频 / 导出封面")
    export.add_argument("project_id")
    export.add_argument("--profiles", action="store_true")
    export.add_argument("--profile", default="douyin")
    export.add_argument("--kind", choices=("video", "cover"), default="video")
    export.add_argument("--at", type=float, dest="at_seconds", default=None)

    return parser


def main(argv: list[str] | None = None, *, client: ApiClient | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    api = client or ApiClient(args.base_url, timeout=args.timeout)
    printer = _Printer(raw=args.json)
    try:
        handler = {
            "project": _project, "recognize": _recognize, "plan": _plan, "keyframes": _keyframes,
            "segments": _segments, "compose": _compose, "gate": _gate, "export": _export,
        }[args.command]
        return handler(api, args, printer)
    except CliApiError as exc:
        print(f"[error] {exc.message}", file=sys.stderr)
        return EXIT_API_ERROR
    except Exception as exc:  # noqa: BLE001 - 任何意外都如实报一行，不给用户看裸 traceback
        print(f"[error] {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_API_ERROR


# ---- 各命令 ----


def _project(api: ApiClient, args, printer: _Printer) -> int:
    if args.action == "create":
        if not args.name:
            print("[usage] project create 需要 --name", file=sys.stderr)
            return EXIT_USAGE
        payload = api.post("/api/v1/projects", body={"product_name": args.name, "product_note": args.note})
        project_id = (payload.get("data") or {}).get("project_id")
        printer.line(f"项目已创建：{project_id}")
        if project_id is None:
            printer.missing(payload, "data.project_id")
        printer.payload(payload)
        return EXIT_OK
    if args.action == "list":
        payload = api.get("/api/v1/projects")
        printer.payload(payload)
        return EXIT_OK
    if not args.project_id:
        print("[usage] project show 需要 project_id", file=sys.stderr)
        return EXIT_USAGE
    printer.payload(api.get(f"/api/v1/projects/{args.project_id}"))
    return EXIT_OK


def _recognize(api: ApiClient, args, printer: _Printer) -> int:
    payload = api.post(f"/api/v1/projects/{args.project_id}/recognition")
    run = (payload.get("data") or {}).get("run") or {}
    run_id = run.get("id")
    printer.line(f"识别任务：{run_id}（状态 {run.get('status')}）")
    if args.confirm:
        if not run_id:
            printer.missing(payload, "data.run.id")
            return EXIT_API_ERROR
        payload = api.post(f"/api/v1/projects/{args.project_id}/recognition/{run_id}/confirm")
        printer.line("识别结果已确认")
    printer.payload(payload)
    return EXIT_OK


def _plan(api: ApiClient, args, printer: _Printer) -> int:
    payload = api.post(f"/api/v1/projects/{args.project_id}/content-plan")
    plan = (payload.get("data") or {}).get("plan") or {}
    printer.line(f"内容方案：{plan.get('id')}（状态 {plan.get('status')}）")
    if args.confirm:
        payload = api.post(f"/api/v1/projects/{args.project_id}/content-plan/confirm")
        printer.line("内容方案已确认")
    printer.payload(payload)
    return EXIT_OK


def _keyframes(api: ApiClient, args, printer: _Printer) -> int:
    if args.generate:
        payload = api.post(f"/api/v1/projects/{args.project_id}/video/keyframes/{args.generate}/candidates")
    elif args.accept_scene:
        if not args.candidate:
            print("[usage] --accept-scene 需要同时给 --candidate", file=sys.stderr)
            return EXIT_USAGE
        payload = api.post(
            f"/api/v1/projects/{args.project_id}/video/keyframes/{args.accept_scene}/accept",
            body={"keyframe_id": args.candidate},
        )
        printer.line(f"关键帧已采用：{args.candidate}")
    else:
        payload = api.get(f"/api/v1/projects/{args.project_id}/video/keyframes")
    printer.payload(payload)
    return EXIT_OK


def _segments(api: ApiClient, args, printer: _Printer) -> int:
    base = f"/api/v1/projects/{args.project_id}/video/segments"
    if args.generate:
        payload = api.post(f"{base}/{args.generate}/candidates")
        printer.line(f"已生成分段候选：{args.generate}")
    elif args.accept:
        payload = api.post(f"{base}/{args.accept}/accept")
        printer.line(f"分段已采用：{args.accept}")
    elif args.retake:
        payload = api.post(f"{base}/{args.retake}/retake", body={"symptom": args.symptom})
        printer.line(f"已按症状定向返修：{args.retake}（{args.symptom}）")
    else:
        payload = api.get(base)
    printer.payload(payload)
    return EXIT_OK


def _compose(api: ApiClient, args, printer: _Printer) -> int:
    payload = api.post(f"/api/v1/projects/{args.project_id}/compose")
    data = payload.get("data") or {}
    printer.line(f"合成：{data.get('status') or data.get('plan_id') or '已发起'}")
    printer.payload(payload)
    return EXIT_OK


def _gate(api: ApiClient, args, printer: _Printer) -> int:
    for check_id in args.ack:
        api.post(f"/api/v1/projects/{args.project_id}/video/gate/ack", body={"check_ids": [check_id]})
        printer.line(f"已确认警告项：{check_id}")
    payload = api.get(f"/api/v1/projects/{args.project_id}/video/gate")
    data = payload.get("data") or {}
    allowed = bool(data.get("download_allowed"))
    pending = [item.get("id") for item in (data.get("checks") or []) if item.get("level") == "warn" and item.get("id") not in set(data.get("acknowledged") or [])]
    printer.line(f"交付门：{data.get('status')}｜可交付：{'是' if allowed else '否'}")
    if pending:
        printer.line("待确认：" + "、".join(str(item) for item in pending))
    printer.payload(payload)
    return EXIT_OK if allowed else EXIT_GATE_BLOCKED


def _export(api: ApiClient, args, printer: _Printer) -> int:
    if args.profiles:
        printer.payload(api.get(f"/api/v1/projects/{args.project_id}/export/profiles"))
        return EXIT_OK
    payload = api.post(
        f"/api/v1/projects/{args.project_id}/export",
        body={"profile": args.profile, "kind": args.kind, "at_seconds": args.at_seconds},
    )
    data = payload.get("data") or {}
    printer.line(
        f"导出完成：{data.get('profile')}｜{data.get('width')}x{data.get('height')}"
        f"｜{data.get('bitrate_kbps')} kbps｜{data.get('download_url')}"
    )
    printer.payload(payload)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - 由 `python -m onetake_cli.main` 调用
    raise SystemExit(main())