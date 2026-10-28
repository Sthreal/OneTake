"""M4-04：数字人（avatar）档位下线后的**契约测试**。

档位下线的口径是「**明确拒绝**」而不是「静默降级为 product」——所以这里锁的是
"传 avatar 必须被拒"，而且**三层都要拒**：请求 schema、接口（422）、领域服务
（绕过接口直接调也必须拒，否则 MCP / 内部调用会漏）。

> 文件名的由来：本文件原先是 avatar 链路的测试；档位下线后保留文件名，内容改为锁下线后的
> 契约 —— 因为 `AGENTS.md` §三 要求"绝不执行用户未明确要求的删除操作"，改名或删文件都不做。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from onetake_api.modules.video_plan.api import CreateVideoPlanRequest
from onetake_api.modules.video_plan.domain import MODE_PRODUCT, MODES
from onetake_api.modules.video_plan.service import (
    VideoPlanApplicationService,
    VideoPlanValidationError,
)

AVATAR = "avatar"


def test_mode_domain_has_only_product() -> None:
    """域层取值域收敛：只剩 product（`avatar` 不再是合法档位）。"""
    assert MODES == frozenset({MODE_PRODUCT})
    assert MODES == frozenset({"product"})


def test_product_mode_is_still_accepted() -> None:
    """收敛不得误伤：product 必须照常通过。"""
    assert CreateVideoPlanRequest(mode="product").mode == "product"


def test_avatar_is_rejected_by_the_request_schema() -> None:
    """请求层：传 avatar 直接过不了校验（FastAPI 会把这个 ValidationError 转成 422）。"""
    with pytest.raises(ValidationError) as excinfo:
        CreateVideoPlanRequest(mode=AVATAR)
    assert "mode" in str(excinfo.value)


def test_avatar_is_rejected_by_the_api_with_422(client) -> None:
    """接口层：必须是 422，而**不是**静默按 product 处理。

    路径里的项目 id 不存在也无妨 —— 体校验发生在业务逻辑之前，所以这条不需要造数据。
    """
    response = client.post(
        "/api/v1/projects/prj_contract_only/video-plan",
        json={"mode": AVATAR, "template_id": "clean"},
    )
    assert response.status_code == 422, response.text
    assert "mode" in response.text


def test_avatar_is_rejected_by_the_service_contract(monkeypatch) -> None:
    """领域层：即使绕过接口直接调服务也必须拒（MCP / 内部调用同样受约束）。"""
    import onetake_api.modules.video_plan.service as service_module

    service = VideoPlanApplicationService(composition=SimpleNamespace(provider_name="mock-video"))
    # 桩掉项目查询：本用例只关心"档位校验先于一切业务动作"
    monkeypatch.setattr(service, "_projects", SimpleNamespace(get_project=lambda *a, **k: SimpleNamespace(id="prj_x")))

    with pytest.raises(VideoPlanValidationError):
        service.create_plan(None, project_id="prj_x", mode=AVATAR, template_id="clean")


def test_silent_wav_has_expected_duration_header() -> None:
    """`_silent_wav` 仍保留（档位下线只摘 avatar 调用点，不删通用工具）。"""
    import wave
    from io import BytesIO

    payload = VideoPlanApplicationService._silent_wav(1.0)
    with wave.open(BytesIO(payload), "rb") as wav:
        assert wav.getframerate() == 48000
        assert wav.getnchannels() == 1
        assert wav.getnframes() == 48000


def test_mock_avatar_asset_is_available() -> None:
    """`avatar_assets.py` 按用户「暂时」口径**保留文件**，其资产自检继续有效。"""
    from onetake_api.integrations.product_scene.avatar_assets import load_mock_avatar

    assert load_mock_avatar()