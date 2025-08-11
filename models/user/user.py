from sqlalchemy import Column, String, Enum, func
from sqlalchemy.dialects.mysql import BIGINT, TINYINT, TIMESTAMP
from db.base import Base
import enum

class Role(str, enum.Enum):
    DONOR = "DONOR"
    RECIPIENT = "RECIPIENT"

class Status(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"

class User(Base):
    __tablename__ = "users"

    user_id = Column(BIGINT, primary_key=True, autoincrement=True, index=True)

    nickname = Column(String(20), nullable=False, unique=True)
    email = Column(String(255), nullable=False)
    password = Column(String(255), nullable=False)
    role = Column(Enum(Role), nullable=False, default=Role.RECIPIENT)
    status = Column(Enum(Status), nullable=False, default=Status.ACTIVE)
    warning_count = Column(TINYINT, nullable=False, default=0)
    created_at = Column(TIMESTAMP, nullable=False, default=func.now())
    updated_at = Column(TIMESTAMP, nullable=False, default=func.now(), onupdate=func.now())
