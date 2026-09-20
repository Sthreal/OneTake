from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx

from onetake_api.platform.errors import DomainError


class DashScopeUploadError(DomainError):
    code = "DASHSCOPE_UPLOAD_ERROR"
    http_status = 502
    retryable = True


class DashScopeTemporaryUploader:
    def __init__(self, *, api_key: str, model: str, endpoint: str = "https://dashscope.aliyuncs.com/api/v1/uploads", client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._model = model
        self._endpoint = endpoint
        self._client = client or httpx.Client(timeout=120)

    def upload_image(self, content: bytes, filename: str = "input.png") -> str:
        return self._upload(content, filename=filename, content_type="application/octet-stream", empty_message="上传图片为空")

    def upload_audio(self, content: bytes, filename: str = "voice.wav") -> str:
        return self._upload(content, filename=filename, content_type="audio/wav", empty_message="上传音频为空")

    def _upload(self, content: bytes, *, filename: str, content_type: str, empty_message: str) -> str:
        if not self._api_key:
            raise DashScopeUploadError("DASHSCOPE_API_KEY 未配置")
        if not content:
            raise DashScopeUploadError(empty_message)
        try:
            policy_response = self._client.get(
                self._endpoint,
                params={"action": "getPolicy", "model": self._model},
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            policy_response.raise_for_status()
            policy = policy_response.json()["data"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise DashScopeUploadError("获取 DashScope 上传凭证失败") from exc
        safe_name = f"{uuid4().hex}-{Path(filename).name}"
        key = f"{policy['upload_dir']}/{safe_name}"
        try:
            upload_response = self._client.post(
                str(policy["upload_host"]),
                data={
                    "OSSAccessKeyId": str(policy["oss_access_key_id"]),
                    "Signature": str(policy["signature"]),
                    "policy": str(policy["policy"]),
                    "x-oss-object-acl": str(policy["x_oss_object_acl"]),
                    "x-oss-forbid-overwrite": str(policy["x_oss_forbid_overwrite"]),
                    "key": key,
                    "success_action_status": "200",
                },
                files={"file": (safe_name, content, content_type)},
            )
            upload_response.raise_for_status()
        except (httpx.HTTPError, KeyError) as exc:
            raise DashScopeUploadError("DashScope 临时文件上传失败") from exc
        return f"oss://{key}"