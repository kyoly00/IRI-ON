from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL, TIMESTAMP
from sqlalchemy.orm import relationship
from db.base import Base

class UserIngredient(Base):
    __tablename__ = "user_ingredient"

    user_id = Column(BIGINT, ForeignKey("user.user_id"), primary_key=True)
    ingredient_id = Column(BIGINT, ForeignKey("ingredient.ingredient_id"), primary_key=True)

    quantity = Column(DECIMAL(6, 2))
    expiration_date = Column(TIMESTAMP)

    user = relationship("User", backref="user_ingredients")
    ingredient = relationship("Ingredient", backref="user_ingredients")
