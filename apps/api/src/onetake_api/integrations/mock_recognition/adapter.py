from __future__ import annotations

from onetake_api.config import get_settings
from onetake_api.modules.recognition.domain import CandidateDraft
from onetake_api.modules.recognition.port import RecognitionImage
from onetake_api.platform.errors import DomainError


class MockRecognitionError(DomainError):
    code = "RECOGNITION_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class MockRecognitionAdapter:
    provider_name = "mock-recognition"
    requires_images = False

    def recognize(
        self,
        *,
        project_name: str,
        product_note: str | None,
        images: list[RecognitionImage],
    ) -> list[CandidateDraft]:
        mode = get_settings().mock_recognition_mode
        if mode == "timeout":
            raise MockRecognitionError("模拟识别超时")
        if mode == "rate_limited":
            raise MockRecognitionError("模拟识别限流")
        if mode == "invalid_output":
            raise MockRecognitionError("模拟识别结果无效")
        return [
            CandidateDraft(
                asset_id=image.asset_id,
                label=image.original_filename.rsplit(".", 1)[0] or "商品候选",
                confidence=round(0.72 + (int(image.sha256[:2], 16) / 255) * 0.2, 2) if image.sha256 else 0.8,
                reason="Mock Provider 根据素材顺序生成候选",
            )
            for image in images
        ]
