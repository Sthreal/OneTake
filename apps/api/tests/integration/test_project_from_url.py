"""S13 提交 5 集成测试：商品 URL 导入端到端。

**零出网**：`fetch_html` / `fetch_image` 全部替换为桩函数 ——
- 正常路径：桩函数返回离线样本，不碰网络
- SSRF 路径：桩函数换成"一旦被调用就报错"的探针，于是"返回 4xx"本身就**证明了没有发出请求**
  （比"用假传输层看请求数"更直接：真有请求就当场炸）
"""
from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy.orm import Session

import onetake_api.modules.project.url_import as url_import
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.integrations.url_fetch.fetcher import FetchedBinary, FetchedPage
from onetake_api.integrations.url_fetch.parser import parse_product_page
from onetake_api.modules.asset.application.commands import PresignUploadCommand
from onetake_api.modules.asset.domain.errors import AssetDuplicateError
from onetake_api.modules.asset.public import AssetPublicService
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService

# ---- 三种真实站点形态的离线样本（第三个刻意"没有 OG"）----

OG_PAGE = (
    '<html><head><meta property="og:title" content="丝绒口红 A">'
    '<meta property="og:image" content="/img/a.png">'
    '<meta property="product:price:amount" content="99"></head></html>'
)
JSONLD_PAGE = (
    '<html><head><script type="application/ld+json">'
    '{"@type":"Product","name":"口红 B","image":"/img/b.png","offers":{"price":88}}'
    "</script></head></html>"
)
BARE_PAGE = (
    "<html><head><title>口红 C</title></head><body>"
    '<img src="/img/c.png" width="900" height="900"></body></html>'
)


def _png(width: int = 600, height: int = 800, color=(200, 40, 40)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _install_page(monkeypatch, html: str, *, image: bytes | None = None, base: str = "https://shop.example/p/1") -> list[str]:
    """把抓取层换成桩；返回被请求过的 URL 列表（用于断言"只请求了该请求的"）。"""
    seen: list[str] = []

    def fake_html(url: str, *, client=None) -> FetchedPage:  # noqa: ANN001
        seen.append(url)
        return FetchedPage(url=base, html=html, content_type="text/html")

    def fake_image(url: str, *, client=None) -> FetchedBinary:  # noqa: ANN001
        seen.append(url)
        if image is None:
            raise AssertionError("本用例不该去取图片")
        return FetchedBinary(url=url, content=image, content_type="image/png")

    monkeypatch.setattr(url_import, "fetch_html", fake_html)
    monkeypatch.setattr(url_import, "fetch_image", fake_image)
    return seen


@pytest.mark.parametrize(
    "html,expect_source,expect_title",
    ((OG_PAGE, "og", "丝绒口红 A"), (JSONLD_PAGE, "jsonld", "口红 B"), (BARE_PAGE, "fallback", "口红 C")),
)
def test_import_creates_project_with_main_image(
    client, db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch,
    html: str, expect_source: str, expect_title: str,
) -> None:
    """验收 1：三种站点形态（**含没有 OG 的那种**）都能建好项目并落到 ≥1 张主图。"""
    _install_page(monkeypatch, html, image=_png())

    response = client.post("/api/v1/projects/from-url", json={"url": "https://shop.example/p/1"})
    assert response.status_code == 201, response.text
    data = response.json()["data"]

    assert data["source"] == expect_source
    assert data["product_name"] == expect_title
    assert len(data["asset_ids"]) == 1
    assert data["warning"] is None

    # 资产真的落进了既有链路，而不是只写了个 id
    assets = AssetPublicService().list_assets(db_session, project_id=data["project_id"])
    assert len(assets) == 1
    stored = b"".join(object_storage.read_object(object_key=assets[0].object_key))
    assert stored == _png()
    assert assets[0].sha256 == hashlib.sha256(_png()).hexdigest()


def test_import_matches_parser_output_for_the_imported_html() -> None:
    """桩与解析器之间不能有两套口径：页面 → 解析结果必须一致。"""
    draft = parse_product_page(OG_PAGE, base_url="https://shop.example/p/1")
    assert (draft.source, draft.title, draft.price, draft.image_url) == (
        "og", "丝绒口红 A", "99", "https://shop.example/img/a.png",
    )


@pytest.mark.parametrize(
    "url",
    (
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8000/api/v1/projects",
        "http://10.0.0.1/",
    ),
)
def test_dangerous_urls_are_rejected_without_any_request(
    client, db_session: Session, monkeypatch, url: str
) -> None:
    """验收 2：内网/环回/云元数据地址 → **4xx 且零出网**。

    桩函数被换成"一旦被调用就失败"的探针 —— 所以"返回 4xx"本身就是没有发请求的证据。
    """

    def explode(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("SSRF 防护必须在发请求之前就拒绝")

    monkeypatch.setattr(url_import, "fetch_html", explode)
    monkeypatch.setattr(url_import, "fetch_image", explode)

    before = len(ProjectPublicService().list_projects(db_session, limit=200))
    response = client.post("/api/v1/projects/from-url", json={"url": url})
    assert response.status_code == 422, response.text
    # 也确实没有偷偷建出一个项目（与重定向用例同口径：比数量，不假设库是空的）
    assert len(ProjectPublicService().list_projects(db_session, limit=200)) == before


def test_redirect_to_internal_address_is_rejected(
    client, db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """验收 5：页面合法但**跳转**指向内网 → 同样拒绝、不建项目。

    这条走真实的 `fetcher`（只把 httpx 换成假传输层），验证"逐跳过 guard"确实生效。
    """
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/x"})

    from onetake_api.integrations.url_fetch import fetcher

    original_fetch_html = fetcher.fetch_html

    def fetch_with_fake_transport(url: str, *, client=None) -> FetchedPage:  # noqa: ANN001
        fake = httpx.Client(transport=httpx.MockTransport(handler))
        return original_fetch_html(url, client=fake)

    monkeypatch.setattr(url_import, "fetch_html", fetch_with_fake_transport)

    before = len(ProjectPublicService().list_projects(db_session, limit=200))
    response = client.post("/api/v1/projects/from-url", json={"url": "https://shop.example/redirects"})
    assert response.status_code == 422, response.text
    assert len(ProjectPublicService().list_projects(db_session, limit=200)) == before, "SSRF 被拒时不该建项目"


def test_fetch_failure_still_creates_project_with_warning(
    client, db_session: Session, monkeypatch
) -> None:
    """验收 3：抓取失败（超时/404/非 HTML）→ **仍然 201** + warning，用户可继续手动上传。"""
    from onetake_api.integrations.url_fetch.fetcher import UrlFetchError

    def failing_html(url: str, *, client=None) -> FetchedPage:  # noqa: ANN001
        raise UrlFetchError("目标返回 404")

    monkeypatch.setattr(url_import, "fetch_html", failing_html)

    response = client.post("/api/v1/projects/from-url", json={"url": "https://shop.example/gone"})
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["asset_ids"] == []
    assert data["warning"] and "手动上传" in data["warning"]
    # 项目确实建好了，且拿得到
    project = ProjectPublicService().get_project(db_session, project_id=data["project_id"])
    assert project.product_name


def test_missing_main_image_still_creates_project(
    client, monkeypatch
) -> None:
    """页面能抓但没有可用主图 → 项目照样建好，只提示补图。"""
    _install_page(monkeypatch, "<html><head><title>无图商品</title></head></html>")

    response = client.post("/api/v1/projects/from-url", json={"url": "https://shop.example/no-image"})
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["asset_ids"] == []
    assert data["warning"] and "主图" in data["warning"]


def test_same_image_is_not_registered_twice_in_one_project(
    client, db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """验收 4：同一张图再进同一个项目 → 命中 `uq_asset_project_sha256`，不产生重复资产。"""
    _install_page(monkeypatch, OG_PAGE, image=_png())
    created = client.post("/api/v1/projects/from-url", json={"url": "https://shop.example/p/1"}).json()["data"]
    project_id = created["project_id"]

    image = _png()
    command = PresignUploadCommand(
        original_filename="again.png", mime_type="image/png", size_bytes=len(image),
        width=600, height=800, sha256=hashlib.sha256(image).hexdigest(),
    )
    # 同一个项目、同一张图（同 sha256）→ 必须被既有唯一约束挡住
    with pytest.raises(AssetDuplicateError):
        AssetPublicService().presign_upload(
            db_session, project_id=project_id, command=command, storage=object_storage
        )
    assert len(AssetPublicService().list_assets(db_session, project_id=project_id)) == 1


def test_import_marks_assets_ready_on_the_pipeline(
    client, db_session: Session, monkeypatch
) -> None:
    """导入的素材要走完既有链路（`pipeline.mark_assets_ready`），否则前端阶段不会前进。"""
    _install_page(monkeypatch, OG_PAGE, image=_png())
    created = client.post("/api/v1/projects/from-url", json={"url": "https://shop.example/p/1"}).json()["data"]

    run = PipelinePublicService().get_or_create(db_session, created["project_id"])
    assert run.status == "assets_ready"