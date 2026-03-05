from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv
import os
import sys

# 1) .env 로드 (파일 위치가 애매하면 절대경로로 지정)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, "..", ".env")  # 필요에 맞게 경로 조정
load_dotenv(dotenv_path=ENV_PATH)  # 기존 './.env' 대신 절대/상대 안전 경로

# 2) 환경변수 읽기 + 검증
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "3306")  # 옵션
DB_NAME = os.getenv("DB_NAME")

missing = [k for k, v in {
    "DB_USER": DB_USER,
    "DB_PASS": DB_PASS,
    "DB_HOST": DB_HOST,
    "DB_NAME": DB_NAME
}.items() if not v]
if missing:
    print(f"[DB CONFIG ERROR] Missing env vars: {missing}")
    print(f"Checked .env at: {ENV_PATH}")
    sys.exit(1)

# 3) 안전한 DSN 구성(utf8mb4 권장, pool 옵션 추가)
DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    f"?charset=utf8mb4"
)

# 4) 엔진 생성(프리핑/리사이클로 연결 끊김 방지)
try:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=5,
        max_overflow=10,
        future=True,
    )
    # 디버깅용: 비밀번호 마스킹하여 출력
    masked_url = DATABASE_URL.replace(DB_PASS, "****")
    print(f"[DB] Using: {masked_url}")
except SQLAlchemyError as e:
    print("[DB ENGINE ERROR]", e)
    sys.exit(1)

# 5) 세션 팩토리
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

# 6) FastAPI 의존성으로 사용할 세션
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
