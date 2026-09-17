from dataclasses import dataclass


@dataclass(frozen=True)
class ListAssetsQuery:
    project_id: str