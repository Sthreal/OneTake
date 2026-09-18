import json

import httpx

from onetake_api.integrations.shotstack.adapter import ShotstackCompositionAdapter
from onetake_api.modules.composition.port import CompositionRequest


def test_shotstack_adapter_uploads_assets_and_returns_rendered_video(monkeypatch) -> None:
    burned: list[dict[str, object]] = []

    def fake_burn(**kwargs):
        burned.append(kwargs)
        return b"captioned-base"

    monkeypatch.setattr("onetake_api.integrations.shotstack.adapter.burn_subtitles", fake_burn)
    uploads: list[dict[str, object]] = []
    render_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/ingest/stage/upload":
            upload_id = f"upload_{len(uploads) + 1}"
            uploads.append({"id": upload_id, "body": None})
            return httpx.Response(200, json={"data": {"id": upload_id, "attributes": {"url": f"https://upload.example/{upload_id}"}}})
        if request.method == "PUT" and request.url.host == "upload.example":
            upload = next(item for item in uploads if item["id"] == request.url.path.rsplit("/", 1)[-1])
            upload["body"] = request.content
            return httpx.Response(200)
        if request.method == "GET" and path.startswith("/ingest/stage/sources/"):
            source_id = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"data": {"id": source_id, "attributes": {"status": "ready", "source": f"https://source.example/{source_id}.bin"}}})
        if request.method == "POST" and path == "/edit/stage/render":
            render_payloads.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(201, json={"success": True, "response": {"id": "render_1"}})
        if request.method == "GET" and path == "/edit/stage/render/render_1":
            return httpx.Response(200, json={"success": True, "response": {"status": "done", "url": "https://cdn.example/final.mp4"}})
        if request.method == "GET" and str(request.url) == "https://cdn.example/final.mp4":
            return httpx.Response(200, content=b"shotstack-final")
        return httpx.Response(404, json={"error": "not found"})

    adapter = ShotstackCompositionAdapter(
        api_key="stage-key",
        environment="stage",
        api_base="https://api.shotstack.io",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.compose(CompositionRequest(
        base_video_bytes=b"base-video",
        audio_bytes=b"voice-audio",
        srt_bytes="1\n00:00:00,000 --> 00:00:02,000\n字幕\n".encode("utf-8"),
        product_image_bytes=b"product-image",
        overlay_product=True,
        duration_seconds=18,
        width=1080,
        height=1920,
        fps=30,
    ))

    assert result == b"shotstack-final"
    assert adapter.provider_name == "shotstack-stage"
    assert len(uploads) == 3
    assert [upload["body"] for upload in uploads] == [b"captioned-base", b"voice-audio", b"product-image"]
    payload = render_payloads[0]
    assert payload["output"] == {"format": "mp4", "fps": 30, "size": {"width": 1080, "height": 1920}}
    track_types = [track["clips"][0]["asset"]["type"] for track in payload["timeline"]["tracks"]]
    assert track_types == ["image", "video", "audio"]
    assert burned[0]["base_video_bytes"] == b"base-video"
    assert burned[0]["srt_bytes"] == "1\n00:00:00,000 --> 00:00:02,000\n字幕\n".encode("utf-8")
