from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL
from sqlalchemy.orm import relationship
from db.base import Base

class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredient"

    recipe_id = Column(BIGINT, ForeignKey("recipe.recipe_id"), primary_key=True)
    ingredient_id = Column(BIGINT, ForeignKey("ingredient.ingredient_id"), primary_key=True)

    quantity = Column(DECIMAL(6, 2))

    ingredient = relationship("Ingredient", backref="recipe_ingredients")
    recipe = relationship("Recipe", backref="recipe_ingredients")
