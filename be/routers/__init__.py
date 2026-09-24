import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from .users import router as users_router
from .recipes import router as recipes_router
from .realtime_openAI import router as realtime_router
from .ingredients import router as ingredients_router
from .tools import router as tools_router
from .households import router as households_router
from .system import router as system_router
from custom_voice.router import router as custom_voice_router

all_routers = [
    users_router,
    recipes_router,
    ingredients_router,
    tools_router,
    households_router,
    system_router,
]

# 레거시 assistant/음성 라우터는 WebSocket 토큰 인증 전환 전까지 운영(production) 환경에서 기본 비공개입니다.
# 개발 환경이거나 ENABLE_LEGACY_ASSISTANT가 명시적으로 true인 경우 라우터를 등록합니다.
_default_enable_assistant = "false" if os.getenv("ENVIRONMENT") == "production" else "true"
if os.getenv("ENABLE_LEGACY_ASSISTANT", _default_enable_assistant).lower() == "true":
    all_routers.extend([realtime_router, custom_voice_router])
