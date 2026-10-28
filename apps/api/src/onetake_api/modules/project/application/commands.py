from dataclasses import dataclass


@dataclass(frozen=True)
class CreateProjectCommand:
    product_name: str
    product_note: str | None = None

@dataclass(frozen=True)
class UpdateProjectCommand:
    project_id: str
    product_name: str | None
    product_note: str | None
    update_product_note: bool
    # 出镜人（人物库）：update_character_id=False → 不动；True 时 character_id 为 None/"" → 清空
    character_id: str | None = None
    update_character_id: bool = False
