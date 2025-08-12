from sqlalchemy import Column, ForeignKey, func, String
from sqlalchemy.dialects.mysql import BIGINT, TIMESTAMP
from sqlalchemy.orm import relationship
from db.base import Base

class CookingRecord(Base):
    __tablename__ = "cooking_record"

    record_id = Column(BIGINT, primary_key=True, autoincrement=True, index=True)

    recipe_id = Column(BIGINT, ForeignKey("recipe.recipe_id"), nullable=False)
    user_id = Column(BIGINT, ForeignKey("user.user_id"), nullable=False)
    url = Column(String(255))
    cooked_at = Column(TIMESTAMP, nullable=False, default=func.now())

    recipe = relationship("Recipe", backref="cooking_records")
    user = relationship("User", backref="cooking_records")
