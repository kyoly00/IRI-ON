from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from dotenv import load_dotenv
import os

load_dotenv(dotenv_path='./.env')

# ✅ DB URL
DATABASE_URL = f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:3306/{os.getenv('DB_NAME')}"

# ✅ DB 연결 설정
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# FastAPI 의존성으로 쓸 DB 세션 생성 함수
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
