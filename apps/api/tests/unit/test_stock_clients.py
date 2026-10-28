"""批次 4a 单测：免费素材客户端（Openverse / Wikimedia / registry）。

全部用 `httpx.MockTransport` 打桩（**不联网**）：网络层之外的行为（解析、许可命名、过滤、
去重、宽泛词回退、错误与"没结果"的区分）都在这里钉住。
"""
from __future__ import annotations

import json

import httpx
import pytest

from onetake_api.integrations.stock import openverse, registry, wikimedia
from onetake_api.integrations.stock.domain import StockAsset, StockError, StockLicense


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


OPENVERSE_BODY = {
    "results": [
        {
            "id": "img-1",
            "title": "Disposable coffee cups",
            "url": "https://live.staticflickr.com/x.jpg",
            "creator": "Matthew Paul Argall",
            "license": "by",
            "license_version": "2.0",
            "license_url": "https://creativecommons.org/licenses/by/2.0/",
            "width": 1024,
            "height": 679,
            "foreign_landing_url": "https://www.flickr.com/photos/x",
            "provider": "flickr",
        },
        {"id": "img-2", "title": "no url → 跳过"},
    ]
}

WIKIMEDIA_BODY = {
    "query": {
        "pages": {
            "1": {
                "pageid": 1,
                "title": "File:Sugar falling into coffee.webm",
                "imageinfo": [{
                    "url": "https://upload.wikimedia.org/wikipedia/commons/5/5a/Sugar.webm?utm_source=commons",
                    "mime": "video/webm", "width": 2904, "height": 2160, "duration": 17.634,
                    "extmetadata": {
                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "Artist": {"value": '<a href="//commons.wikimedia.org/wiki/User:X">The Answer</a>'},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"},
                    },
                }],
            },
            "2": {
                "pageid": 2,
                "title": "File:Some photo.jpg",
                "imageinfo": [{"url": "https://upload.wikimedia.org/x.jpg", "mime": "image/jpeg", "width": 10, "height": 10}],
            },
        }
    }
}


# ---- Openverse ----


def test_openverse_parses_images_and_names_licenses() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=OPENVERSE_BODY)

    assets = openverse.search_images("coffee cup", limit=5, client=_client(handler))
    assert len(assets) == 1                              # 缺 url 的那条被跳过
    asset = assets[0]
    assert asset.kind == "image" and asset.source == "openverse" and asset.provider == "flickr"
    assert asset.license.name == "CC BY 2.0" and asset.license.requires_attribution is True
    assert asset.width == 1024 and asset.height == 679
    assert "/v1/images" in str(seen[0].url)
    assert seen[0].url.params["q"] == "coffee cup" and seen[0].url.params["page_size"] == "5"


@pytest.mark.parametrize(
    ("license_id", "version", "expected"),
    [("by", "2.0", "CC BY 2.0"), ("cc0", "1.0", "CC0"), ("pdm", None, "Public domain"), (None, None, "Unknown")],
)
def test_openverse_license_naming(license_id, version, expected) -> None:
    assert openverse.license_name(license_id, version) == expected


def test_openverse_audio_duration_is_milliseconds() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{
            "id": "a1", "title": "calm loop", "url": "https://cdn/openverse/a1.mp3",
            "license": "cc0", "duration": 12500,
        }]})

    asset = openverse.search_audio("calm", client=_client(handler))[0]
    assert asset.kind == "audio" and asset.duration_seconds == 12.5
    assert asset.license.requires_attribution is False            # CC0 不需要署名（但仍记录来源）


def test_openverse_error_is_explicit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    with pytest.raises(StockError) as error:
        openverse.search_images("coffee", client=_client(handler))
    assert error.value.http_status == 502 and error.value.retryable is True


# ---- Wikimedia ----


def test_wikimedia_parses_videos_and_strips_html() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=WIKIMEDIA_BODY)

    assets = wikimedia.search_videos("coffee", client=_client(handler))
    assert len(assets) == 1                                        # 图片被 mime 过滤掉
    asset = assets[0]
    assert asset.kind == "video" and asset.source == "wikimedia"
    assert asset.title == "Sugar falling into coffee.webm"
    assert asset.download_url == "https://upload.wikimedia.org/wikipedia/commons/5/5a/Sugar.webm"   # utm 被剥掉
    assert asset.creator == "The Answer"                            # HTML 标签被剥掉
    assert asset.license.name == "CC BY-SA 4.0" and asset.duration_seconds == 17.634
    assert asset.landing_url and asset.landing_url.startswith("https://commons.wikimedia.org/wiki/File:")
    params = seen[0].url.params
    assert params["gsrsearch"] == "filetype:video coffee" and params["gsrnamespace"] == "6"


def test_wikimedia_empty_result_is_not_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"batchcomplete": ""})       # 无结果时没有 query.pages

    assert wikimedia.search_videos("zzz-no-such-thing", client=_client(handler)) == []


def test_wikimedia_error_is_explicit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(StockError):
        wikimedia.search_videos("coffee", client=_client(handler))


# ---- registry ----


def _asset(asset_id: str, *, source: str = "wikimedia") -> StockAsset:
    return StockAsset(
        asset_id=asset_id, kind="video", source=source, provider=source, title=asset_id,
        download_url=f"https://example/{asset_id}.webm", license=StockLicense("CC BY-SA 4.0"),
    )


def test_registry_uses_video_source_and_skips_excluded(monkeypatch) -> None:
    monkeypatch.setattr(registry.wikimedia, "search_videos", lambda query, **_: [_asset("a"), _asset("b")])
    assert registry.find_video("coffee").asset_id == "a"
    assert registry.find_video("coffee", exclude_ids={"a"}).asset_id == "b"     # 跨镜去重
    assert registry.find_video("coffee", exclude_ids={"a", "b"}) is None        # 全被用过 → None


def test_registry_falls_back_to_broadened_query(monkeypatch) -> None:
    queries: list[str] = []

    def fake_search(query: str, **_kwargs):
        queries.append(query)
        return [_asset("broad")] if query == "morning coffee" else []

    monkeypatch.setattr(registry.wikimedia, "search_videos", fake_search)
    asset = registry.find_video("morning coffee routine")
    assert asset is not None and asset.asset_id == "broad"
    assert queries == ["morning coffee routine", "morning coffee"]


def test_registry_separates_error_from_empty(monkeypatch) -> None:
    def failing(query: str, **_kwargs):
        raise StockError(f"源挂了：{query}")

    monkeypatch.setattr(registry.wikimedia, "search_videos", failing)
    with pytest.raises(StockError) as error:
        registry.find_video("coffee")
    assert "所有素材源都检索失败" in str(error.value)

    monkeypatch.setattr(registry.wikimedia, "search_videos", lambda query, **_: [])
    assert registry.find_video("coffee") is None            # 正常但没结果 → None（不是故障）


@pytest.mark.parametrize(
    ("query", "expected"),
    [("morning coffee routine", "morning coffee"), ("coffee shop", "coffee"), ("coffee", None), ("", None)],
)
def test_broaden_query(query: str, expected: str | None) -> None:
    assert registry.broaden_query(query) == expected


def test_attribution_line_and_requirements() -> None:
    assert _asset("a").attribution_line == '"a" (CC BY-SA 4.0) — https://example/a.webm'
    assert _asset("a").requires_attribution is True
    no_credit = StockAsset(
        asset_id="c", kind="audio", source="openverse", provider="openverse", title="loop",
        download_url="https://example/c.mp3", license=StockLicense("CC0"),
    )
    assert no_credit.requires_attribution is False