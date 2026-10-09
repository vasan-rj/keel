import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str


# Dev default points at the docker-compose db (host port 5433). Override with
# DATABASE_URL for any other environment (prod/GCP sets it explicitly).
_DEFAULT_DATABASE_URL = "postgresql://keel:keel@localhost:5433/keel"


def get_settings() -> Settings:
    return Settings(database_url=os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL))
