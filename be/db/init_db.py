from db.session import engine
from db.base import Base
from models import *
from sqlalchemy import inspect, text


def _add_missing_columns():
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

    if "recipe_ingredient" in tables:
        columns = {column["name"] for column in inspector.get_columns("recipe_ingredient")}
        if "unit" not in columns:
            statements.append("ALTER TABLE recipe_ingredient ADD COLUMN unit VARCHAR(20) NULL")

    if "user" in tables:
        columns = {column["name"] for column in inspector.get_columns("user")}
        user_table = '"user"' if engine.dialect.name == "postgresql" else "`user`"
        definitions = {
            "fire_skill": "VARCHAR(20) NOT NULL DEFAULT 'with_help'",
            "knife_skill": "VARCHAR(20) NOT NULL DEFAULT 'with_help'",
            "peeler_skill": "VARCHAR(20) NOT NULL DEFAULT 'with_help'",
            "scissors_skill": "VARCHAR(20) NOT NULL DEFAULT 'with_help'",
            "cooking_level": "SMALLINT NOT NULL DEFAULT 1",
            "age_group": "VARCHAR(20) NULL",
            "supervision_level": "VARCHAR(30) NOT NULL DEFAULT 'sometimes_help'",
            "avatar_type": "VARCHAR(20) NOT NULL DEFAULT 'preset'",
            "avatar_value": "VARCHAR(512) NOT NULL DEFAULT 'baby1'",
            "photo_consent_confirmed": "BOOLEAN NOT NULL DEFAULT FALSE",
            "allergy_status": "VARCHAR(20) NOT NULL DEFAULT 'unknown'",
            "dietary_restrictions": "TEXT NULL",
            "disliked_ingredients": "TEXT NULL",
        }
        for name, definition in definitions.items():
            if name not in columns:
                statements.append(f"ALTER TABLE {user_table} ADD COLUMN {name} {definition}")

    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))

def init_db():
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
