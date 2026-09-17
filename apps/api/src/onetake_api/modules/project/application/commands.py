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
