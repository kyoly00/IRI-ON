from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.session import get_db
from crud import domain_crud
from schemas.tool_schema import ToolSchema

router = APIRouter(prefix="/tools", tags=["tools"])

# 전체 도구 조회
@router.get("/", response_model=List[ToolSchema])
def get_all_tools(db: Session = Depends(get_db)):
    tools = domain_crud.get_all_tools(db)
    return tools
