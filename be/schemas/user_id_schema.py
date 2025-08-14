from pydantic import BaseModel

class UserIDSchema(BaseModel):
    user_id: int

    class Config:
        orm_mode = True  # ORM 객체도 자동 변환 가능
