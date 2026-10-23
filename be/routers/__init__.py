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
    realtime_router,
    custom_voice_router,
]
