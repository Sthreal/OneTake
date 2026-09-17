from dataclasses import dataclass


@dataclass(frozen=True)
class CreateProjectCommand:
    product_name: str
    product_note: str | None = None