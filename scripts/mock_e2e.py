from __future__ import annotations

import argparse
import hashlib
import io
import time
from collections.abc import Callable

import httpx
from PIL import Image, ImageDraw


def wait_for(path: str, predicate: Callable[[dict], bool], *, timeout: float = 90.0, interval: float = 0.3) -> dict:
    deadline = time.time() + timeout
    last: dict | None = None
    while time.time() < deadline:
        response = httpx.get(f"{BASE_URL}{path}", timeout=30.0)
        response.raise_for_status()
        last = response.json()
        if predicate(last):
            return last
        time.sleep(interval)
    raise TimeoutError(f"等待超时: {path}; 最后响应: {last}")


def post(path: str, *, json: dict | None = None) -> dict:
    response = httpx.post(f"{BASE_URL}{path}", json=json, timeout=60.0)
    response.raise_for_status()
    return response.json()


def product_png() -> bytes:
    image = Image.new("RGB", (900, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((220, 120, 680, 780), radius=70, fill=(35, 110, 220))
    draw.rounded_rectangle((285, 170, 615, 300), radius=25, fill=(245, 245, 245))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="One Take Mock P0 全流程验收")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()
    global BASE_URL
    BASE_URL = args.base_url.rstrip("/")

    project = post("/api/v1/projects", json={"product_name": "Mock验收商品", "product_note": "自动化验收项目"})["data"]
    project_id = project["project_id"]
    print(f"project_id={project_id}")

    image_bytes = product_png()
    sha256 = hashlib.sha256(image_bytes).hexdigest()
    presign = post(
        f"/api/v1/projects/{project_id}/assets/presign",
        json={
            "original_filename": "product.png",
            "mime_type": "image/png",
            "size_bytes": len(image_bytes),
            "width": 900,
            "height": 900,
            "sha256": sha256,
        },
    )["data"]
    upload = httpx.put(presign["upload_url"], content=image_bytes, headers=presign["required_headers"], timeout=60.0)
    upload.raise_for_status()
    asset = post(
        f"/api/v1/projects/{project_id}/assets/{presign['asset_id']}/complete",
        json={
            "original_filename": "product.png",
            "mime_type": "image/png",
            "size_bytes": len(image_bytes),
            "width": 900,
            "height": 900,
            "sha256": sha256,
        },
    )["data"]
    print(f"asset_id={asset['asset_id']}")

    post(f"/api/v1/projects/{project_id}/recognition")
    recognition = wait_for(
        f"/api/v1/projects/{project_id}/recognition",
        lambda body: bool(body["data"]["candidates"]) and body["data"]["run"]["status"] in {"ready", "confirmed"},
        timeout=args.timeout,
    )
    candidate = recognition["data"]["candidates"][0]
    post(
        f"/api/v1/projects/{project_id}/recognition/{recognition['data']['run']['run_id']}/confirm",
        json={"asset_id": candidate["asset_id"], "candidate_id": candidate["candidate_id"]},
    )

    post(f"/api/v1/projects/{project_id}/main-image")
    wait_for(
        f"/api/v1/projects/{project_id}/main-image",
        lambda body: body["data"]["version"] and body["data"]["version"]["status"] in {"ready", "confirmed"},
        timeout=args.timeout,
    )
    post(f"/api/v1/projects/{project_id}/main-image/confirm")

    post(
        f"/api/v1/projects/{project_id}/script/generate",
        json={
            "pain_point": "果汁口感不真实",
            "selling_points": ["便携", "易清洗", "口感真实"],
            "usage_scenario": "外出携带",
            "offer": "限时优惠",
        },
    )
    wait_for(
        f"/api/v1/projects/{project_id}/script",
        lambda body: body["data"]["version"] and body["data"]["version"]["status"] in {"ready", "confirmed"},
        timeout=args.timeout,
    )
    post(f"/api/v1/projects/{project_id}/script/confirm")

    post(
        f"/api/v1/projects/{project_id}/voice",
        json={"enabled": True, "subtitle_enabled": True, "voice_id": "女声", "language": "zh", "speed": 1.0},
    )
    wait_for(
        f"/api/v1/projects/{project_id}/audio-subtitle",
        lambda body: body["data"]["voice"]["run"]
        and body["data"]["voice"]["run"]["status"] == "ready"
        and body["data"]["subtitle"]["version"]
        and body["data"]["subtitle"]["version"]["status"] in {"ready", "confirmed"},
        timeout=args.timeout,
    )
    post(f"/api/v1/projects/{project_id}/audio-subtitle/confirm")
    post(f"/api/v1/projects/{project_id}/content-plan")
    post(f"/api/v1/projects/{project_id}/content-plan/confirm")

    results = []
    for mode, template_id in (("avatar", None), ("product", "clean"), ("product", "dynamic"), ("product", "lifestyle")):
        plan = post(
            f"/api/v1/projects/{project_id}/video-plan",
            json={"mode": mode, "template_id": template_id},
        )["data"]["plan"]
        plan_id = plan["plan_id"]
        post(f"/api/v1/projects/{project_id}/video")
        final = wait_for(
            f"/api/v1/projects/{project_id}/video",
            lambda body: body["data"]["plan"] and body["data"]["plan"]["status"] in {"completed", "failed"},
            timeout=args.timeout * 2,
        )["data"]["plan"]
        if final["status"] != "completed":
            raise RuntimeError(f"视频生成失败: mode={mode} template={template_id} error={final['error_code']}")
        output = httpx.get(f"{BASE_URL}/api/v1/projects/{project_id}/output", timeout=30.0).json()["data"]
        results.append({
            "mode": mode,
            "template_id": template_id,
            "plan_id": plan_id,
            "video_url": output["download_url"],
            "duration_seconds": output["duration_seconds"],
            "video_width": output["video_width"],
            "video_height": output["video_height"],
        })
        print(f"completed mode={mode} template={template_id} plan_id={plan_id}")

    print("E2E_OK")
    for result in results:
        print(result)


if __name__ == "__main__":
    main()