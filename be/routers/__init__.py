from .users import router as users_router
from .recipes import router as recipes_router
from .realtime import router as realtime_router
from .cleanup import router as cleanup_router
from .ingredients import router as ingredients_router
from .tools import router as tools_router

all_routers = [users_router, recipes_router, realtime_router, cleanup_router, ingredients_router, tools_router]
