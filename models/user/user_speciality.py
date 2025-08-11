from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import relationship
from db.base import Base

class UserSpeciality(Base):
    __tablename__ = "user_speciality"

    user_id = Column(BIGINT, ForeignKey("user.user_id"), primary_key=True)
    recipe_id = Column(BIGINT, ForeignKey("recipe.recipe_id"), primary_key=True)

    user = relationship("User", backref="user_specialities")
    recipe = relationship("Recipe", backref="user_specialities")
