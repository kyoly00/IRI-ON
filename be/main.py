from fastapi import FastAPI
from db.init_db import init_db
from db.seed import seed
from contextlib import asynccontextmanager
from routers import all_routers

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 앱 시작 시 실행
    init_db()
    seed()
    yield  # 여기가 앱이 실행되는 시점
    # 앱 종료 시 실행 (필요하면 여기에 종료 코드 작성)

app = FastAPI(lifespan=lifespan)

# ✅ CORS 허용 (개발용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # 프론트 주소
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in all_routers:
    app.include_router(router)