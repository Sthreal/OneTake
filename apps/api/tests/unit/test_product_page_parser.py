"""S13 提交 2 单测：商品页三级回退解析（离线 HTML 样本，不发任何网络请求）。

覆盖档案 S13 的三级优先级：OpenGraph → JSON-LD → 裸标签，以及"抓不全也要有结果"的降级语义。
"""
from __future__ import annotations

from onetake_api.integrations.url_fetch.parser import PageDraft, parse_product_page

BASE = "https://shop.example/p/1"


def test_open_graph_wins_and_resolves_relative_image() -> None:
    html = (
        '<html><head>'
        '<meta property="og:title" content="丝绒口红 A">'
        '<meta property="og:image" content="/img/a.jpg">'
        '<meta property="product:price:amount" content="99">'
        "</head></html>"
    )
    draft = parse_product_page(html, base_url=BASE)
    assert draft.source == "og"
    assert draft.title == "丝绒口红 A"
    assert draft.price == "99"
    assert draft.image_url == "https://shop.example/img/a.jpg"


def test_open_graph_accepts_name_attribute_and_partial_data() -> None:
    """`<meta name="og:image">` 这种写法真实网站也在用；只有图片没有标题也算 OG 命中。"""
    html = '<meta name="og:image" content="https://cdn.example/x.png">'
    draft = parse_product_page(html, base_url=BASE)
    assert draft.source == "og"
    assert draft.title is None
    assert draft.image_url == "https://cdn.example/x.png"


def test_json_ld_used_when_open_graph_is_absent() -> None:
    html = (
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Product","name":"口红 B",'
        '"image":["/i/b.png"],"offers":{"@type":"Offer","price":88}}'
        "</script>"
    )
    draft = parse_product_page(html, base_url=BASE)
    assert draft.source == "jsonld"
    assert draft.title == "口红 B"
    assert draft.price == "88"          # 数字价格也要取到（JSON-LD 常见写法）
    assert draft.image_url == "https://shop.example/i/b.png"


def test_json_ld_found_inside_graph_and_type_list() -> None:
    """@graph 嵌套 + `@type` 是数组 —— 都是真实站点会出现的形态。"""
    html = (
        '<script type="application/ld+json">'
        '{"@graph":[{"@type":"BreadcrumbList"},'
        '{"@type":["Product","Thing"],"name":"口红 D","image":"https://cdn.example/d.png"}]}'
        "</script>"
    )
    draft = parse_product_page(html, base_url=BASE)
    assert draft.source == "jsonld"
    assert draft.title == "口红 D"
    assert draft.image_url == "https://cdn.example/d.png"


def test_broken_json_ld_does_not_crash_and_falls_through() -> None:
    html = '<script type="application/ld+json">{ 这不是 JSON </script><title>口红 E</title>'
    draft = parse_product_page(html, base_url=BASE)
    assert draft.source == "fallback"
    assert draft.title == "口红 E"


def test_fallback_prefers_image_with_declared_large_size() -> None:
    html = (
        "<title>口红 C</title>"
        '<img src="/icon.png" width="64" height="64">'
        '<img src="/hero.png" width="800" height="600">'
    )
    draft = parse_product_page(html, base_url=BASE)
    assert draft.source == "fallback"
    assert draft.title == "口红 C"
    assert draft.image_url == "https://shop.example/hero.png"
    assert draft.warnings == ()


def test_fallback_warns_when_no_image_declares_its_size() -> None:
    html = "<title>口红 F</title><img src=\"/a.png\">"
    draft = parse_product_page(html, base_url=BASE)
    assert draft.image_url == "https://shop.example/a.png"
    assert any("尺寸" in item for item in draft.warnings), draft.warnings


def test_empty_page_yields_none_source_with_warning() -> None:
    for html in ("", "<html><body>nothing here</body></html>"):
        draft = parse_product_page(html, base_url=BASE)
        assert draft.source == "none"
        assert draft.title is None and draft.image_url is None
        assert draft.warnings, "抓不到任何东西时必须留下原因"


def test_relative_url_without_base_is_kept_as_is() -> None:
    draft = parse_product_page("<title>X</title><img src=\"rel.png\" width=\"500\">")
    assert draft.image_url == "rel.png"


def test_draft_defaults_are_all_empty() -> None:
    """降级语义的基础：所有字段都可为空，上层据此走"手动上传"。"""
    draft = PageDraft()
    assert (draft.title, draft.price, draft.image_url) == (None, None, None)
    assert draft.source == "none"