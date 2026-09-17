import enum

from sqlalchemy import Column, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL, TIMESTAMP
from sqlalchemy.orm import relationship

from db.base import Base


class HouseholdRole(str, enum.Enum):
    PARENT = "parent"
    CHILD = "child"


class RequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Household(Base):
    __tablename__ = "household"

    household_id = Column(BIGINT, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    invite_code = Column(String(12), nullable=False, unique=True, index=True)
    created_at = Column(TIMESTAMP, nullable=False, default=func.now())


class HouseholdMember(Base):
    __tablename__ = "household_member"
    __table_args__ = (UniqueConstraint("user_id", name="uq_household_member_user"),)

    household_id = Column(BIGINT, ForeignKey("household.household_id"), primary_key=True)
    user_id = Column(BIGINT, ForeignKey("user.user_id"), primary_key=True)
    role = Column(Enum(HouseholdRole), nullable=False)
    joined_at = Column(TIMESTAMP, nullable=False, default=func.now())

    household = relationship("Household", backref="members")


class FridgeItem(Base):
    __tablename__ = "fridge_item"
    __table_args__ = (UniqueConstraint("household_id", "ingredient_id", name="uq_fridge_item"),)

    fridge_item_id = Column(BIGINT, primary_key=True, autoincrement=True)
    household_id = Column(BIGINT, ForeignKey("household.household_id"), nullable=False, index=True)
    ingredient_id = Column(BIGINT, ForeignKey("ingredient.ingredient_id"), nullable=False)
    quantity = Column(DECIMAL(10, 2), nullable=False, default=0)
    unit = Column(String(20), nullable=False, default="piece")
    source = Column(String(20), nullable=False, default="manual")
    updated_at = Column(TIMESTAMP, nullable=False, default=func.now(), onupdate=func.now())

    ingredient = relationship("Ingredient")


class PurchaseRequest(Base):
    __tablename__ = "purchase_request"

    purchase_request_id = Column(BIGINT, primary_key=True, autoincrement=True)
    household_id = Column(BIGINT, ForeignKey("household.household_id"), nullable=False, index=True)
    requester_id = Column(BIGINT, ForeignKey("user.user_id"), nullable=False)
    recipe_id = Column(BIGINT, ForeignKey("recipe.recipe_id"), nullable=True)
    servings = Column(BIGINT, nullable=True)
    status = Column(Enum(RequestStatus), nullable=False, default=RequestStatus.PENDING)
    reviewed_by = Column(BIGINT, ForeignKey("user.user_id"), nullable=True)
    created_at = Column(TIMESTAMP, nullable=False, default=func.now())
    updated_at = Column(TIMESTAMP, nullable=False, default=func.now(), onupdate=func.now())

    requester = relationship("User", foreign_keys=[requester_id])
    recipe = relationship("Recipe")


class PurchaseRequestItem(Base):
    __tablename__ = "purchase_request_item"

    purchase_request_item_id = Column(BIGINT, primary_key=True, autoincrement=True)
    purchase_request_id = Column(BIGINT, ForeignKey("purchase_request.purchase_request_id"), nullable=False, index=True)
    ingredient_id = Column(BIGINT, ForeignKey("ingredient.ingredient_id"), nullable=False)
    quantity = Column(DECIMAL(10, 2), nullable=False)
    unit = Column(String(20), nullable=False)

    ingredient = relationship("Ingredient")
