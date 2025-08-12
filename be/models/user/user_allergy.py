from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import relationship
from db.base import Base

class UserAllergy(Base):
    __tablename__ = "user_allergy"

    user_id = Column(BIGINT, ForeignKey("user.user_id"), primary_key=True)
    ingredient_id = Column(BIGINT, ForeignKey("ingredient.ingredient_id"), primary_key=True)

    user = relationship("User", backref="user_allergies")
    ingredient = relationship("Ingredient", backref="user_allergies")
