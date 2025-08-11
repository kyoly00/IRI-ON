from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import relationship
from db.base import Base

class ItemImage(Base):
    __tablename__ = "item_image"

    item_id = Column(BIGINT, ForeignKey("item.item_id"), primary_key=True)

    url = Column(String(255), nullable=False)

    item = relationship("Item", backref="item_images")
