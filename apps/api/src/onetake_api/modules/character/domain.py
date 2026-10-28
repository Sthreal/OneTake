"""出镜人（人物库）：**跨项目复用**的资产。

为什么要有它：出镜人母版（人物四视角/照片）生成或上传一次，就应当沉淀进一个**库**，
以后任何项目选这个人就**直接用**（不再重新生成、不再重复花钱）。

设计边界（2026-10-15 拍板）：
- 母版图存在**独立前缀** `characters/{id}/sheet.png`，**不挂在任何项目下** → 项目只引用 id；
- 因此项目的媒体清理（DELETE /projects/{id}/media）**不得**动这些图（清理逻辑要排除该前缀）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from onetake_api.platform.errors import DomainError


class CharacterNotFoundError(DomainError):
    code = "CHARACTER_NOT_FOUND"
    http_status = 404
    retryable = False


class CharacterValidationError(DomainError):
    code = "CHARACTER_VALIDATION_ERROR"
    http_status = 422
    retryable = False


@dataclass(frozen=True)
class Character:
    id: str
    name: str
    appearance: str
    voice_style: str | None
    sheet_object_key: str
    # generated = 用模型生成的四视角母版；uploaded = 用户自带的真人照片（0 成本、更可靠）
    source: str
    created_at: datetime
