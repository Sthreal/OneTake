from __future__ import annotations

import base64
from dataclasses import dataclass
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

"""逐镜 VLM 评分的维度与提示词（批次 5）。

维度只有 5 个，且都能在**一段镜头的画面**上判：
- `visual`（画面质量：清晰/构图/曝光）
- `temporal`（时序：这一镜内动作连贯、无跳变）
- `script_fidelity`（脚本遵循：画面是否在讲这一句文案）
- `product_fidelity`（商品保真：与商品主图一致、没变形、没多出别的商品）
- `continuity`（连续性：与相邻镜的色调/空间/光线一致）

**证据必须是可核对的**：模型只能引用我抽给它的那些帧的时刻（提示词里给了时刻表），
不允许它编一个"第 12 秒"（那种证据没法用来定位问题）。
"""

SEGMENT_QUALITY_DIMENSIONS: tuple[str, ...] = (
    "visual", "temporal", "script_fidelity", "product_fidelity", "continuity",
)

# 维度权重（合计 100）：商品保真最高，因为它是"能不能卖"的底线
SEGMENT_QUALITY_WEIGHTS: dict[str, int] = {
    "product_fidelity": 30, "visual": 25, "script_fidelity": 20, "temporal": 15, "continuity": 10,
}


# 采样温度：0 = 贪心解码（实测默认温度下，同一内容的逐镜分数会大幅抖动）
SEGMENT_SCORE_TEMPERATURE = 0.0

@dataclass(frozen=True)
class SegmentScoreResult:
    scores: dict[str, int]
    issues: list[str]
    evidence_seconds: list[float]
    # DashScope 返回的真实用量（`usage`）：用来**校准单价**，不再靠估
    usage: dict | None = None


def _is_number(value: object) -> bool:
    try:
        float(value)  # type: ignore[arg-type]
        return True
    except (TypeError, ValueError):
        return False


_SEGMENT_PROMPT = (
    "你是独立电商视频质检员。第一张是原始商品图，后面是这个视频**第 {order} 镜（共 {total} 镜）**的抽帧，"
    "抽帧时刻为：{times} 秒。\n"
    "这一镜的文案：{excerpt}\n这一镜的镜头目标：{shot}\n"
    "请只看这一镜，按 5 个维度打分（0-100）："
    "visual（画面质量）、temporal（时序连贯）、script_fidelity（是否在讲这句文案）、"
    "product_fidelity（商品是否与主图一致、无变形/无多余商品）、continuity（与相邻镜的色调空间是否一致）。\n"
    "**证据**：issues 里每条问题都要写清「哪一帧（从上面给的时刻里选）+ 看到了什么」，"
    "并把用到的时刻填进 evidence_seconds（只能从给定时刻里选）。\n"
    "只输出严格 JSON："
    '{{"scores":{{"visual":0,"temporal":0,"script_fidelity":0,"product_fidelity":0,"continuity":0}},'
    '"issues":["第 x.xx 秒：…"],"evidence_seconds":[0.0]}}'
)
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
                json={
                    "model": self.model,
                    "input": {"messages": [{"role": "user", "content": [{"image": image} for image in images] + [{"text": prompt}]}]},
                    # 采样温度 0 = 贪心解码。批次 5 实测：同一批内容（1/2/3 镜素材完全相同）单次评分拿到
                    # 50 / 90 / 0 —— 抖动到这个程度就没法当"可比较的分数"用，所以两次调用都压到 0。
                    "parameters": {"temperature": SEGMENT_SCORE_TEMPERATURE},
                },
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

    # ---- 批次 5：逐镜评分 ----

    def score_segment(
        self, *, video_bytes: bytes, duration_seconds: float, product_image_bytes: bytes,
        script_excerpt: str, shot_prompt: str, order_index: int, total_segments: int,
    ) -> SegmentScoreResult:
        """给**一个分段**打分：5 个维度 + 可核对证据（证据只能引用我给它的抽帧时刻）。

        为什么要逐镜而不是只看整片：整片打分只能得到"这条视频不行"，
        而逐镜能定位到"第 3 镜商品变形"——后者才可执行（重生成那一镜）。
        """
        if not self._api_key:
            raise QwenVlQualityError("DASHSCOPE_API_KEY 未配置")
        if not product_image_bytes:
            raise QwenVlQualityError("缺少原始商品图")
        with tempfile.TemporaryDirectory() as temp_dir:
            frame_paths = self._extract_frame_files(video_bytes, duration_seconds, Path(temp_dir))
            times = [seconds for seconds, _ in frame_paths]
            frames = [path.read_bytes() for _, path in frame_paths]
        images = [self._data_url(product_image_bytes)]
        images.extend(self._data_url(frame) for frame in frames)
        prompt = _SEGMENT_PROMPT.format(
            order=order_index, total=total_segments, excerpt=script_excerpt or "（无）",
            shot=shot_prompt or "（无）",
            times=", ".join(f"{seconds:.2f}" for seconds in times),
        )
        try:
            response = self._client.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "input": {"messages": [{"role": "user", "content": [{"image": image} for image in images] + [{"text": prompt}]}]},
                    # 采样温度 0 = 贪心解码。批次 5 实测：同一批内容（1/2/3 镜素材完全相同）单次评分拿到
                    # 50 / 90 / 0 —— 抖动到这个程度就没法当"可比较的分数"用，所以两次调用都压到 0。
                    "parameters": {"temperature": SEGMENT_SCORE_TEMPERATURE},
                },
            )
            response.raise_for_status()
            body = response.json()
            text = body["output"]["choices"][0]["message"]["content"]
            if isinstance(text, list):
                text = "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in text)
            parsed = json.loads(self._extract_json(str(text)))
            scores = {str(key): max(0, min(100, int(value))) for key, value in dict(parsed["scores"]).items()}
            missing = [dimension for dimension in SEGMENT_QUALITY_DIMENSIONS if dimension not in scores]
            if missing:
                raise ValueError(f"缺维度：{missing}")
            issues = [str(item) for item in parsed.get("issues", [])]
            evidence = [float(item) for item in parsed.get("evidence_seconds", []) if _is_number(item)]
            usage = body.get("usage") if isinstance(body.get("usage"), dict) else None
            return SegmentScoreResult(scores=scores, issues=issues, evidence_seconds=evidence, usage=usage)
        except QwenVlQualityError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise QwenVlQualityError("Qwen-VL 逐镜评分失败") from exc

    def _extract_frame_files(self, video_bytes: bytes, duration_seconds: float, root: Path) -> list[tuple[float, Path]]:
        video_path = root / "segment.mp4"
        video_path.write_bytes(video_bytes)
        times = [duration_seconds * index / (self._frame_count + 1) for index in range(1, self._frame_count + 1)]
        extracted: list[tuple[float, Path]] = []
        for index, seconds in enumerate(times):
            frame_path = root / f"frame-{index}.png"
            subprocess.run(
                [get_ffmpeg_exe(), "-y", "-ss", f"{seconds:.3f}", "-i", str(video_path), "-frames:v", "1", str(frame_path)],
                check=True, capture_output=True, text=True,
            )
            extracted.append((seconds, frame_path))
        return extracted
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
