from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import relationship
from db.base import Base

class RecipeTool(Base):
    __tablename__ = "recipe_tool"

    recipe_id = Column(BIGINT, ForeignKey("recipe.recipe_id"), primary_key=True)
    tool_id = Column(BIGINT, ForeignKey("tool.tool_id"), primary_key=True)

    tool = relationship("Tool", backref="recipe_tools")
    recipe = relationship("Recipe", backref="recipe_tools")
