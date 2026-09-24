from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictRequestSchema(BaseModel):
    """예상하지 않은 필드를 거부해 mass assignment를 막는 요청 모델 기반 클래스입니다."""
    model_config = ConfigDict(extra="forbid")


class HouseholdCreateSchema(StrictRequestSchema):
    name: str = Field(min_length=1, max_length=100)


class HouseholdJoinSchema(StrictRequestSchema):
    invite_code: str = Field(min_length=4, max_length=12)


class FridgeItemInputSchema(StrictRequestSchema):
    ingredient_id: int | None = None
    name: str | None = Field(default=None, max_length=100)
    quantity: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    unit: str = Field(min_length=1, max_length=20)


class FridgeItemUpdateSchema(StrictRequestSchema):
    quantity: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    unit: str = Field(min_length=1, max_length=20)


class AvailabilitySchema(StrictRequestSchema):
    servings: int = Field(gt=0, le=50)


class PurchaseRequestCreateSchema(StrictRequestSchema):
    recipe_id: int | None = None
    servings: int | None = Field(default=None, gt=0, le=50)
    items: list[FridgeItemInputSchema] = Field(min_length=1)


class PurchaseRequestStatusSchema(StrictRequestSchema):
    status: Literal["approved", "rejected"]
