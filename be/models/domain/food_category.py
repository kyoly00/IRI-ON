from sqlalchemy import Column, String
from sqlalchemy.dialects.mysql import BIGINT
from db.base import Base

class FoodCategory(Base):
    __tablename__ = "food_category"

    category_id = Column(BIGINT, primary_key=True, autoincrement=True, index=True)
    
    name = Column(String(20), nullable=False)
