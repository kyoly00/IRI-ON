from sqlalchemy import Column, ForeignKey, Enum
from sqlalchemy.dialects.mysql import BIGINT, TIMESTAMP
from sqlalchemy.orm import relationship
from db.base import Base
import enum

class Status(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"

class Reception(Base):
    __tablename__ = "reception"

    reception_id = Column(BIGINT, primary_key=True, autoincrement=True, index=True)
    
    item_id = Column(BIGINT, ForeignKey("item.item_id"), primary_key=True)
    recipient_id = Column(BIGINT, ForeignKey("users.user_id"), primary_key=True)
    status = Column(Enum(Status), nullable=False, default=Status.PENDING)
    created_at = Column(TIMESTAMP, nullable=False)
    received_at = Column(TIMESTAMP)
    method_id = Column(BIGINT, ForeignKey("reception_method.method_id"), nullable=False)

    item = relationship("Item", backref="receptions")
    recipient = relationship("User", backref="receptions")
    method = relationship("ReceptionMethod", backref="receptions")
