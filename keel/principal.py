from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    project_id: object
    person_id: object
    session_id: str | None = None
    scope: str = "full"
