from datetime import UTC, datetime, timedelta

import pytest

from onetake_api.modules.project.domain.errors import ProjectValidationError
from onetake_api.modules.project.domain.model import create_project_entity, update_project_entity


def _create(product_name: str, product_note: str | None = None):
    now = datetime.now(UTC)
    return create_project_entity(
        project_id="prj_test",
        product_name=product_name,
        product_note=product_note,
        now=now,
        expires_at=now + timedelta(hours=24),
    )


def test_create_project_normalizes_fields() -> None:
    project = _create("  便携式榨汁杯  ", "  白色杯身  ")
    assert project.product_name == "便携式榨汁杯"
    assert project.product_note == "白色杯身"
    assert project.status == "draft"


def test_empty_product_name_is_rejected() -> None:
    with pytest.raises(ProjectValidationError):
        _create("   ")


def test_blank_note_is_normalized_to_none() -> None:
    project = _create("榨汁杯", "   ")
    assert project.product_note is None


def test_long_product_name_is_rejected() -> None:
    with pytest.raises(ProjectValidationError):
        _create("a" * 81)


def test_long_product_note_is_rejected() -> None:
    with pytest.raises(ProjectValidationError):
        _create("榨汁杯", "a" * 241)

def test_update_project_entity_keeps_character_when_not_mentioned() -> None:
    project = _create("榨汁杯")
    updated = update_project_entity(
        project=project, product_name=None, product_note=None, update_product_note=False,
        now=project.updated_at + timedelta(minutes=1), character_id="chr_1", update_character_id=True,
    )
    # 先选上人，再改别的字段 —— 不能被悄悄清掉
    kept = update_project_entity(
        project=updated, product_name="榨汁杯 Pro", product_note=None, update_product_note=False,
        now=updated.updated_at + timedelta(minutes=1),
    )
    assert kept.character_id == "chr_1"


def test_update_project_entity_clears_character_with_empty_string() -> None:
    project = update_project_entity(
        project=_create("榨汁杯"), product_name=None, product_note=None, update_product_note=False,
        now=datetime.now(UTC), character_id="chr_1", update_character_id=True,
    )
    cleared = update_project_entity(
        project=project, product_name=None, product_note=None, update_product_note=False,
        now=project.updated_at + timedelta(minutes=1), character_id="", update_character_id=True,
    )
    assert cleared.character_id is None


def test_new_project_has_no_character_by_default() -> None:
    assert _create("榨汁杯").character_id is None


def test_update_project_entity_changes_fields_and_updated_at() -> None:
    project = _create("榨汁杯", "旧说明")
    updated = update_project_entity(
        project=project,
        product_name="榨汁杯 Pro",
        product_note="新说明",
        update_product_note=True,
        now=project.updated_at + timedelta(minutes=1),
    )
    assert updated.product_name == "榨汁杯 Pro"
    assert updated.product_note == "新说明"
    assert updated.updated_at > project.updated_at
