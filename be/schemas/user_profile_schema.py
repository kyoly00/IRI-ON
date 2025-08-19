from pydantic import BaseModel

class UserProfileSchema(BaseModel):
    name: str
    can_use_fire: bool
    can_use_knife: bool
    can_use_peeler: bool
    can_use_scissors: bool
    allergy: str

    class Config:
        orm_mode = True  # ORM 객체도 자동 변환 가능
