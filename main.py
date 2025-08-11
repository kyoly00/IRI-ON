from fastapi import FastAPI, Depends
from models.user.user import User
from sqlalchemy.exc import OperationalError
from db.session import engine, get_db
from sqlalchemy.orm import Session

app = FastAPI()

from db.init_db import init_db
init_db()  # 테이블 생성

@app.get("/")
def get():
    try:
        with engine.connect() as connection:
            return {"message": "✅ 데이터베이스 연결 성공!"}
    except OperationalError as e:
        return {"message": "❌ 데이터베이스 연결 실패:"}
    return {"message": "hi"}

@app.get("/users")
def list_users(db: Session = Depends(get_db)):
    return db.query(User).all()

@app.get("/clear")
def clear_users(db: Session = Depends(get_db)):
    db.query(User).delete()
    db.commit()
    return {"message": "✅ 모든 사용자 데이터가 삭제되었습니다."}
