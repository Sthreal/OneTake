"""批次 7 集成测：CLI 打**真实端点**（同进程：TestClient 当传输层，不假装）。

这样测的意义：CLI 里的每个判断（能不能下载、导出结果）都必须来自服务端字段；
如果哪天端点改了字段名，这些用例会先红，而不是等用户在命令行里发现。
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[4]   # apps/api/tests/integration → 仓库根
CLI_SRC = REPO_ROOT / "apps" / "cli" / "src"
if str(CLI_SRC) not in sys.path:
    sys.path.insert(0, str(CLI_SRC))

from onetake_cli.client import ApiClient                     # noqa: E402
from onetake_cli.main import EXIT_API_ERROR, EXIT_GATE_BLOCKED, EXIT_OK, EXIT_USAGE, main  # noqa: E402

from test_export_endpoints import _seed                       # noqa: E402


def _api(app_client: TestClient) -> ApiClient:
    def transport(method: str, url: str, body: bytes | None) -> tuple[int, bytes]:
        response = app_client.request(method, url, content=body, headers={"Content-Type": "application/json"})
        return response.status_code, response.content

    return ApiClient("http://testserver", transport=transport)


def test_cli_project_create_then_list(client: TestClient, capsys) -> None:
    api = _api(client)
    assert main(["project", "create", "--name", "CLI 项目"], client=api) == EXIT_OK
    out = capsys.readouterr().out
    assert "项目已创建" in out
    assert main(["project", "list", "--json"], client=api) == EXIT_OK   # --json 在子命令之后也认
    assert "CLI 项目" in capsys.readouterr().out
    assert main(["--json", "project", "list"], client=api) == EXIT_OK   # 放在前面同样成立
    assert capsys.readouterr().out.strip().startswith("{")


def test_cli_usage_error_exit_code(capsys) -> None:
    api = ApiClient("http://testserver", transport=lambda *_: (200, b"{}"))
    assert main(["project", "create"], client=api) == EXIT_USAGE
    assert "需要 --name" in capsys.readouterr().err


def test_cli_gate_exit_code_follows_download_allowed(
    client: TestClient, db_session: Session, object_storage, capsys
) -> None:
    project_id, plan = _seed(db_session, object_storage, "CLI 交付门", with_final=True, gate=None)
    api = _api(client)

    assert main(["gate", project_id, "--json"], client=api) == EXIT_OK          # ok → 0
    assert '"download_allowed": true' in capsys.readouterr().out

    warn_gate = {
        "project_id": project_id, "status": "warn", "mode": "enforce",
        "checks": [{"id": "contact_sheet", "level": "warn", "label": "抽帧复核", "message": "缺抽帧拼图"}],
    }
    from dataclasses import replace

    from onetake_api.modules.video_plan.repository import VideoPlanRepository

    VideoPlanRepository().update(db_session, replace(plan, gate_report=warn_gate))
    db_session.commit()

    assert main(["gate", project_id], client=api) == EXIT_GATE_BLOCKED         # 未确认 warn → 3
    out = capsys.readouterr().out
    assert "可交付：否" in out and "contact_sheet" in out

    assert main(["gate", project_id, "--ack", "contact_sheet"], client=api) == EXIT_OK   # ack 后放行
    assert "已确认警告项：contact_sheet" in capsys.readouterr().out


def test_cli_export_profiles_and_video(client: TestClient, db_session: Session, object_storage, capsys) -> None:
    project_id, _plan = _seed(db_session, object_storage, "CLI 导出", with_final=True, gate=None)
    api = _api(client)

    assert main(["export", project_id, "--profiles", "--json"], client=api) == EXIT_OK
    assert "xiaohongshu" in capsys.readouterr().out

    assert main(["export", project_id, "--profile", "douyin"], client=api) == EXIT_OK
    out = capsys.readouterr().out
    assert "导出完成：douyin" in out and "1080x1920" in out


def test_cli_encodes_non_ascii_path_segments(capsys) -> None:
    """非 ASCII 的 id 必须被 URL 编码后再发出去（真机上 urllib 会因未编码而抛 UnicodeEncodeError）。"""
    seen: list[str] = []

    def transport(method: str, url: str, body: bytes | None) -> tuple[int, bytes]:
        seen.append(url)
        return 404, '{"error": {"code": "PROJECT_NOT_FOUND", "message": "项目不存在"}}'.encode("utf-8")

    api = ApiClient("http://testserver", transport=transport)
    assert main(["gate", "prj_不存在"], client=api) == EXIT_API_ERROR
    assert seen and seen[0].isascii(), seen
    assert "PROJECT_NOT_FOUND" in capsys.readouterr().err


def test_cli_surfaces_api_error(client: TestClient, capsys) -> None:
    api = _api(client)
    assert main(["gate", "prj_不存在"], client=api) == EXIT_API_ERROR
    assert "[error]" in capsys.readouterr().err


def test_cli_keyframes_and_segments_list_from_real_endpoints(
    client: TestClient, db_session: Session, object_storage, capsys
) -> None:
    """列表类命令打的是真端点（不 mock）：至少要能拿到结构正确的响应。

    这里用"有已确认内容方案"的种子（`test_video_stock_fill._seed`）—— 分段列表要求方案已确认，
    否则端点本身就会 409（那是正确行为，不该由 CLI 掩饰）。
    """
    from test_video_stock_fill import _seed as _seed_with_content_plan

    project_id, _plan = _seed_with_content_plan(db_session, object_storage, "CLI 列表")
    api = _api(client)
    assert main(["keyframes", project_id, "--json"], client=api) == EXIT_OK
    assert "data" in capsys.readouterr().out
    assert main(["segments", project_id, "--json"], client=api) == EXIT_OK
    assert "data" in capsys.readouterr().out