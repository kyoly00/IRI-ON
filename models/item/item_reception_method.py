from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import relationship
from db.base import Base

class ItemReceptionMethod(Base):
    __tablename__ = "item_reception_method"

    item_id = Column(BIGINT, ForeignKey("item.item_id"), primary_key=True)
    method_id = Column(BIGINT, ForeignKey("reception_method.method_id"), primary_key=True)

    item = relationship("Item", backref="item_reception_methods")
    method = relationship("ReceptionMethod", backref="item_reception_methods")
