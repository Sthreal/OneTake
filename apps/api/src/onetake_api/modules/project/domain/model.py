from dataclasses import dataclass
from datetime import datetime

from onetake_api.modules.project.domain.errors import ProjectValidationError

PROJECT_STATUS_DRAFT = "draft"


@dataclass(frozen=True)
class Project:
    id: str
    product_name: str
    product_note: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


def normalize_product_name(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ProjectValidationError("商品名称不能为空")
    if len(normalized) > 80:
        raise ProjectValidationError("商品名称不能超过 80 个字符")
    return normalized


def normalize_product_note(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > 240:
        raise ProjectValidationError("补充说明不能超过 240 个字符")
    return normalized


def create_project_entity(
    *,
    project_id: str,
    product_name: str,
    product_note: str | None,
    now: datetime,
    expires_at: datetime,
) -> Project:
    return Project(
        id=project_id,
        product_name=normalize_product_name(product_name),
        product_note=normalize_product_note(product_note),
        status=PROJECT_STATUS_DRAFT,
        created_at=now,
        updated_at=now,
        expires_at=expires_at,
    )