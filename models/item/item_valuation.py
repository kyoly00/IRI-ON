from sqlalchemy import Column, ForeignKey, func
from sqlalchemy.dialects.mysql import BIGINT, TEXT, TIMESTAMP, DECIMAL
from sqlalchemy.orm import relationship
from db.base import Base

class ItemValuation(Base):
    __tablename__ = "item_valuation"

    item_id = Column(BIGINT, ForeignKey("item.item_id"), primary_key=True)

    amount = Column(DECIMAL(12, 2), nullable=False)
    detail = Column(TEXT, nullable=False)
    created_at = Column(TIMESTAMP, nullable=False)
    updated_at = Column(TIMESTAMP, nullable=False, default=func.now(), onupdate=func.now())

    item = relationship("Item", backref="item_valuation")
