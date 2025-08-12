from fastapi import FastAPI
from models.user.user import User
from db.init_db import init_db

init_db()  # 테이블 생성

app = FastAPI()
app.include_router(User.router)
