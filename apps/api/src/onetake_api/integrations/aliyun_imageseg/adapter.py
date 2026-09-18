from __future__ import annotations

from io import BytesIO

import httpx
from PIL import Image, UnidentifiedImageError

from onetake_api.platform.errors import DomainError

REQUEST_TIMEOUT_SECONDS = 60
MAX_MASK_BYTES = 20 * 1024 * 1024
MAX_INPUT_BYTES = 20 * 1024 * 1024


class AliyunCommodityMattingError(DomainError):
    code = "MATTING_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class AliyunCommodityMattingAdapter:
    provider_name = "aliyun-imageseg-segmentcommodity"

    def __init__(
        self,
        *,
        access_key_id: str,
        access_key_secret: str,
        region_id: str,
        endpoint: str,
    ) -> None:
        self._access_key_id = access_key_id
        self._access_key_secret = access_key_secret
        self._region_id = region_id
        self._endpoint = endpoint

    def remove_background(self, *, image_bytes: bytes) -> bytes:
        if not self._access_key_id or not self._access_key_secret:
            raise AliyunCommodityMattingError("阿里云图像分割 AccessKey 未配置")
        if not image_bytes:
            raise AliyunCommodityMattingError("去背输入为空")
        if len(image_bytes) > MAX_INPUT_BYTES:
            raise AliyunCommodityMattingError("去背输入超过 20 MB")
        try:
            response = self._segment(image_bytes)
            mask_url = response.body.data.image_url
        except AliyunCommodityMattingError:
            raise
        except Exception as exc:
            raise AliyunCommodityMattingError("阿里云 SegmentCommodity 调用失败") from exc
        if not mask_url:
            raise AliyunCommodityMattingError("阿里云 SegmentCommodity 未返回 mask")
        try:
            mask_response = httpx.get(mask_url, timeout=REQUEST_TIMEOUT_SECONDS)
            mask_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AliyunCommodityMattingError("阿里云 mask 下载失败") from exc
        return self._compose_rgba(image_bytes=image_bytes, mask_bytes=mask_response.content)

    def _segment(self, image_bytes: bytes):
        from alibabacloud_imageseg20191230 import models as imageseg_models
        from alibabacloud_imageseg20191230.client import Client as ImageSegClient
        from alibabacloud_tea_openapi import models as open_api_models
        from alibabacloud_tea_util import models as util_models

        client = ImageSegClient(
            open_api_models.Config(
                access_key_id=self._access_key_id,
                access_key_secret=self._access_key_secret,
                region_id=self._region_id,
                endpoint=self._endpoint,
                protocol="HTTPS",
            )
        )
        request = imageseg_models.SegmentCommodityAdvanceRequest(
            image_urlobject=BytesIO(image_bytes),
            return_form="mask",
        )
        runtime = util_models.RuntimeOptions(
            read_timeout=REQUEST_TIMEOUT_SECONDS * 1000,
            connect_timeout=REQUEST_TIMEOUT_SECONDS * 1000,
            autoretry=False,
            max_attempts=1,
        )
        return client.segment_commodity_advance(request, runtime)

    @staticmethod
    def _compose_rgba(*, image_bytes: bytes, mask_bytes: bytes) -> bytes:
        if not mask_bytes:
            raise AliyunCommodityMattingError("阿里云返回空 mask")
        if len(mask_bytes) > MAX_MASK_BYTES:
            raise AliyunCommodityMattingError("阿里云返回 mask 超过 20 MB")
        try:
            with Image.open(BytesIO(image_bytes)) as source:
                product = source.convert("RGB")
            with Image.open(BytesIO(mask_bytes)) as mask_source:
                mask = mask_source.convert("L")
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise AliyunCommodityMattingError("阿里云返回内容不是有效图片") from exc
        if mask.size != product.size:
            mask = mask.resize(product.size, Image.Resampling.LANCZOS)
        if mask.getbbox() is None:
            raise AliyunCommodityMattingError("阿里云 mask 没有可见商品")
        product.putalpha(mask)
        output = BytesIO()
        product.save(output, format="PNG", optimize=True)
        return output.getvalue()
