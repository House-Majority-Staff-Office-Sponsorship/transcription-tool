import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DEFAULT_DATABASE_URL = "sqlite:///data/db/transcription.db"


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def ensure_sqlite_directory_exists(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return

    db_path = database_url.removeprefix("sqlite:///")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


database_url = get_database_url()
ensure_sqlite_directory_exists(database_url)

engine = create_engine(database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)