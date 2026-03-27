from db.base import Base
from db import models  # noqa: F401
from db.session import engine
from sqlalchemy import inspect
from db.session import engine


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def start_db():
    init_db()
    inspector = inspect(engine)
    print(inspector.get_table_names())
    print("Database initialized.")