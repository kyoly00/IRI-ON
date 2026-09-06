from db.session import engine
from db.base import Base
from models import *
from sqlalchemy import inspect, text


def _add_missing_video_columns():
    """create_all이 기존 테이블을 변경하지 않는 문제를 보완하는 소규모 마이그레이션."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    statements = []

    if "recipe" in tables:
        columns = {column["name"] for column in inspector.get_columns("recipe")}
        if "video_url" not in columns:
            statements.append("ALTER TABLE recipe ADD COLUMN video_url VARCHAR(512) NULL")

    if "recipe_step" in tables:
        columns = {column["name"] for column in inspector.get_columns("recipe_step")}
        definitions = {
            "video_id": "VARCHAR(32) NULL",
            "start_url": "VARCHAR(512) NULL",
            "start_seconds": "INTEGER NULL",
            "step_len": "INTEGER NULL",
        }
        for name, definition in definitions.items():
            if name not in columns:
                statements.append(
                    f"ALTER TABLE recipe_step ADD COLUMN {name} {definition}"
                )

    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))

def init_db():
    Base.metadata.create_all(bind=engine)
    _add_missing_video_columns()
