from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL, TIMESTAMP
from sqlalchemy.orm import relationship
from db.base import Base

class UserTool(Base):
    __tablename__ = "user_tool"

    user_id = Column(BIGINT, ForeignKey("user.user_id"), primary_key=True)
    tool_id = Column(BIGINT, ForeignKey("tool.tool_id"), primary_key=True)

    quantity = Column(DECIMAL(6, 2))
    expiration_date = Column(TIMESTAMP)

    user = relationship("User", backref="user_tools")
    tool = relationship("Tool", backref="user_tools")
