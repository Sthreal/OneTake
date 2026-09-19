from __future__ import annotations

import base64
import json
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, UnidentifiedImageError
from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.modules.content_qa.domain import QaCheck, QaRequest, SemanticQaResult
from onetake_api.platform.errors import DomainError

MAX_IMAGE_SIDE = 1600


class QwenVlQualityError(DomainError):
    code = "CONTENT_QA_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class QwenVlSemanticAdapter:
    provider_name = "qwen-vl-plus-quality"

    def __init__(self, *, api_key: str, endpoint: str, model: str, frame_count: int = 5, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self.model = model
        self._frame_count = max(3, min(frame_count, 5))
        self._client = client or httpx.Client(timeout=120)

    def evaluate(self, request: QaRequest) -> SemanticQaResult:
        if not self._api_key:
            raise QwenVlQualityError("DASHSCOPE_API_KEY 未配置")
        if not request.product_image_bytes:
            raise QwenVlQualityError("缺少原始商品图")
        images = [self._data_url(request.product_image_bytes)]
        images.extend(self._data_url(frame) for frame in self._extract_frames(request.video_bytes, request.metadata.duration_seconds))
        variant = request.plan.variants[request.plan.selected_variant_index]
        prompt = (
            "你是独立电商视频质检员。参考第一张原始商品图，检查后续视频关键帧。"
            "只输出严格 JSON，不得修改文案。格式："
            "{\"score\":0-100,\"passed\":true或false,\"issues\":[\"问题\"],"
            "\"checks\":[{\"check_id\":\"product_consistency\",\"label\":\"商品一致性\",\"passed\":true,\"weight\":30,\"message\":\"说明\"}]}。"
            "至少检查 product_consistency、script_fidelity、scene_relevance、visual_stability、brand_safety。"
            "商品颜色、形状、包装文字变化，或出现未确认价格、销量、认证、品牌文字时 passed=false。"
            f"分镜：{json.dumps([scene.prompt for scene in variant.scenes], ensure_ascii=False)}"
        )
        try:
            response = self._client.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "input": {"messages": [{"role": "user", "content": [{"image": image} for image in images] + [{"text": prompt}]}]}},
            )
            response.raise_for_status()
            body = response.json()
            text = body["output"]["choices"][0]["message"]["content"]
            if isinstance(text, list):
                text = "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in text)
            parsed = json.loads(self._extract_json(str(text)))
            checks = [QaCheck(str(item["check_id"]), str(item["label"]), bool(item["passed"]), int(item["weight"]), str(item["message"]), True) for item in parsed["checks"]]
            score = max(0, min(100, int(parsed["score"])))
            issues = [str(item) for item in parsed.get("issues", [])]
            passed = bool(parsed["passed"]) and score >= 85 and not issues
            if not checks:
                raise ValueError("checks empty")
            return SemanticQaResult(passed=passed, score=score, checks=checks, issues=issues)
        except QwenVlQualityError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise QwenVlQualityError("Qwen-VL-Plus 语义质检失败") from exc

    def _extract_frames(self, video_bytes: bytes, duration_seconds: float) -> list[bytes]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video_path = root / "candidate.mp4"
            video_path.write_bytes(video_bytes)
            times = [duration_seconds * index / (self._frame_count + 1) for index in range(1, self._frame_count + 1)]
            frames = []
            for index, seconds in enumerate(times):
                frame_path = root / f"frame-{index}.png"
                subprocess.run([get_ffmpeg_exe(), "-y", "-ss", f"{seconds:.3f}", "-i", str(video_path), "-frames:v", "1", str(frame_path)], check=True, capture_output=True, text=True)
                frames.append(frame_path.read_bytes())
            return frames

    @staticmethod
    def _data_url(content: bytes) -> str:
        try:
            with Image.open(BytesIO(content)) as source:
                image = source.convert("RGB")
                image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
                output = BytesIO()
                image.save(output, format="JPEG", quality=88, optimize=True)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise QwenVlQualityError("语义质检图片无效") from exc
        return f"data:image/jpeg;base64,{base64.b64encode(output.getvalue()).decode('ascii')}"

    @staticmethod
    def _extract_json(text: str) -> str:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise QwenVlQualityError("Qwen-VL-Plus 未返回 JSON")
        return text[start : end + 1]
