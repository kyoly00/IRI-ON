from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import relationship
from db.base import Base

class RecipeCategory(Base):
    __tablename__ = "recipe_category"

    recipe_id = Column(BIGINT, ForeignKey("recipe.recipe_id"), primary_key=True)
    category_id = Column(BIGINT, ForeignKey("food_category.category_id"), primary_key=True)

    recipe = relationship("Recipe", backref="recipe_categories")
    category = relationship("FoodCategory", backref="recipe_categories")
