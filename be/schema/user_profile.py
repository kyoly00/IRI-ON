from pydantic import BaseModel

class UserProfileCreate(BaseModel):
    user_id: int
    name: str
    can_use_fire: bool
    can_use_knife: bool
    allergy: str
