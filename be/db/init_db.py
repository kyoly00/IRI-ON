from db.session import engine
from db.base import Base
from models import *

def init_db():
    Base.metadata.create_all(bind=engine)
