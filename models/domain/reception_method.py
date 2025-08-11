from sqlalchemy import Column, String
from sqlalchemy.dialects.mysql import BIGINT
from db.base import Base

class ReceptionMethod(Base):
    __tablename__ = "reception_method"

    method_id = Column(BIGINT, primary_key=True, autoincrement=True, index=True)

    name = Column(String(50), nullable=False)
