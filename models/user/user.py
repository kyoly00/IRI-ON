from sqlalchemy import Column, String, Enum, func
from sqlalchemy.dialects.mysql import BIGINT, TINYINT, TIMESTAMP, BOOLEAN
from db.base import Base

class User(Base):
    __tablename__ = "user"

    user_id = Column(BIGINT, primary_key=True, autoincrement=True, index=True)

    name = Column(String(20), nullable=False, unique=True)
    age = Column(TINYINT, nullable=False)
    can_use_fire = Column(BOOLEAN, nullable=False, default=False)
    can_use_knife = Column(BOOLEAN, nullable=False, default=False)
    created_at = Column(TIMESTAMP, nullable=False, default=func.now())
    updated_at = Column(TIMESTAMP, nullable=False, default=func.now(), onupdate=func.now())
