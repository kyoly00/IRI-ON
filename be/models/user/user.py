from sqlalchemy import Column, String, func
from sqlalchemy.dialects.mysql import BIGINT, TINYINT, TIMESTAMP, BOOLEAN, TEXT
from db.base import Base

class User(Base):
    __tablename__ = "user"

    user_id = Column(BIGINT, primary_key=True, autoincrement=True, index=True)

    id = Column(String(20), nullable=False, unique=True)
    password = Column(String(100), nullable=False)
    name = Column(String(20), default="셰프")
    can_use_fire = Column(BOOLEAN, nullable=False, default=False)
    can_use_knife = Column(BOOLEAN, nullable=False, default=False)
    can_use_peeler = Column(BOOLEAN, nullable=False, default=False)
    can_use_scissors = Column(BOOLEAN, nullable=False, default=False)
    created_at = Column(TIMESTAMP, nullable=False, default=func.now())
    updated_at = Column(TIMESTAMP, nullable=False, default=func.now(), onupdate=func.now())
    allergy = Column(TEXT, nullable=True, default=None)
