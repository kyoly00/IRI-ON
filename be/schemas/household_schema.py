from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class HouseholdCreateSchema(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class HouseholdJoinSchema(BaseModel):
    invite_code: str = Field(min_length=4, max_length=12)


class FridgeItemInputSchema(BaseModel):
    ingredient_id: int | None = None
    name: str | None = Field(default=None, max_length=100)
    quantity: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    unit: str = Field(min_length=1, max_length=20)


class FridgeItemUpdateSchema(BaseModel):
    quantity: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    unit: str = Field(min_length=1, max_length=20)


class AvailabilitySchema(BaseModel):
    servings: int = Field(gt=0, le=50)


class PurchaseRequestCreateSchema(BaseModel):
    recipe_id: int | None = None
    servings: int | None = Field(default=None, gt=0, le=50)
    items: list[FridgeItemInputSchema] = Field(min_length=1)


class PurchaseRequestStatusSchema(BaseModel):
    status: Literal["approved", "rejected"]
