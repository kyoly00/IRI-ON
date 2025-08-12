from sqlalchemy import Column, ForeignKey, Enum, func
from sqlalchemy.dialects.mysql import BIGINT, TIMESTAMP, TEXT
from db.base import Base
import enum

class Status(str, enum.Enum):
    SENDED = "SENDED"
    READ = "READ"

class Notification(Base):
    __tablename__ = "notification"

    notification_id = Column(BIGINT, primary_key=True, autoincrement=True, index=True)

    user_id = Column(BIGINT, ForeignKey("user.user_id"), nullable=False)
    message = Column(TEXT, nullable=False)
    status = Column(Enum(Status), nullable=False, default=Status.SENDED)
    send_time = Column(TIMESTAMP, nullable=False, default=func.now())
