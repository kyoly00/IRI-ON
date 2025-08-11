from sqlalchemy import Column, String, Enum, func, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT, TIMESTAMP, TEXT, BOOLEAN
from sqlalchemy.orm import relationship
from db.base import Base
import enum

class ConditionGrade(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class Status(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"

class Item(Base):
    __tablename__ = "item"

    item_id = Column(BIGINT, primary_key=True, autoincrement=True, index=True)

    donor_id = Column(BIGINT, ForeignKey("users.user_id"), nullable=False)
    title = Column(String(100), nullable=False)
    description = Column(TEXT)
    category = Column(String(50), nullable=False)
    condition_grade = Column(Enum(ConditionGrade), nullable=False)
    donation_for_tax = Column(BOOLEAN, nullable=False)
    status = Column(Enum(Status), nullable=False, default=Status.OPEN)
    created_at = Column(TIMESTAMP, nullable=False)
    updated_at = Column(TIMESTAMP, nullable=False, default=func.now(), onupdate=func.now())

    donor = relationship("User", backref="items")
