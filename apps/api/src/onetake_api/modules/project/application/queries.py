from dataclasses import dataclass


@dataclass(frozen=True)
class GetProjectQuery:
    project_id: str


@dataclass(frozen=True)
class ListProjectsQuery:
    limit: int