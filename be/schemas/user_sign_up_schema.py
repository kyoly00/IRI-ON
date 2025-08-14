from pydantic import BaseModel

class UserSignUpSchema(BaseModel):
    id: str
    password: str

    class Config:
        orm_mode = True  # ORM 객체도 자동 변환 가능
