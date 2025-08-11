from sqlalchemy import Column, ForeignKey, Enum
from sqlalchemy.dialects.mysql import BIGINT, TEXT, TIMESTAMP
from sqlalchemy.orm import relationship
from db.base import Base
import enum

class Rating(str, enum.Enum):
    GOOD = "GOOD"
    BAD = "BAD"

class Feedback(Base):
    __tablename__ = "feedback"

    reception_id = Column(BIGINT, ForeignKey("reception.reception_id"), primary_key=True)

    rating = Column(Enum(Rating), nullable=False)
    comment = Column(TEXT)
    created_at = Column(TIMESTAMP, nullable=False)

    reception = relationship("Reception", backref="feedback")
