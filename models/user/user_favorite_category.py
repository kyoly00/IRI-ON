from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import relationship
from db.base import Base

class UserFavoriteCategory(Base):
    __tablename__ = "user_favorite_category"

    user_id = Column(BIGINT, ForeignKey("user.user_id"), primary_key=True)
    category_id = Column(BIGINT, ForeignKey("food_category.category_id"), primary_key=True)

    user = relationship("User", backref="user_favorite_categories")
    category = relationship("FoodCategory", backref="user_favorite_categories")
