import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "..", ".env"))


def database_url() -> str:
    """배포용 DATABASE_URL을 우선 사용하고 로컬 개발용 설정을 보조로 지원합니다."""
    value = os.getenv("DATABASE_URL")
    if value:
        return value
    required = {key: os.getenv(key) for key in ("DB_USER", "DB_PASS", "DB_NAME")}
    missing = [key for key, item in required.items() if not item]
    if missing:
        raise RuntimeError(f"Database configuration missing: {', '.join(missing)}")
    return "mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4".format(
        user=required["DB_USER"], password=required["DB_PASS"], host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "3306"), name=required["DB_NAME"],
    )


# 선택 CA 인증서로 로컬 설정을 바꾸지 않고 관리형 MySQL TLS 연결을 지원합니다.
DATABASE_URL = database_url()
connect_args = {"ssl": {"ca": os.getenv("DB_SSL_CA")}} if os.getenv("DB_SSL_CA") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600, pool_size=5,
                       max_overflow=10, pool_timeout=30, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def get_db():
    """요청마다 SQLAlchemy 세션 하나를 만들고, 끝나면 항상 닫습니다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
