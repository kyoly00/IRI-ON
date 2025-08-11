from sqlalchemy import Column, ForeignKey, Enum, String
from sqlalchemy.dialects.mysql import BIGINT, TIMESTAMP
from sqlalchemy.orm import relationship
from db.base import Base
import enum

class Status(str, enum.Enum):
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"

class Receipt(Base):
    __tablename__ = "receipt"

    receipt_id = Column(BIGINT, primary_key=True, autoincrement=True, index=True)
    
    item_id = Column(BIGINT, ForeignKey("item.item_id"), nullable=False)
    status = Column(Enum(Status), nullable=False, default=Status.ISSUED)
    url = Column(String(255), nullable=False)
    issued_at = Column(TIMESTAMP, nullable=False)

    item = relationship("Item", backref="receipt")
