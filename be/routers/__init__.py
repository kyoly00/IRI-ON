from .users import router as users_router
from .recipes import router as recipes_router

all_routers = [users_router, recipes_router]
