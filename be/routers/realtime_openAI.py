"""OpenAI Realtime 브릿지를 FastAPI에서 담당한다.

핵심 개념
----------
1. 브라우저 ⇄ OpenAI WebRTC 연결은 전적으로 TypeScript(프론트)에서 처리한다.
2. FastAPI는
   - OpenAI Realtime용 에페메럴 세션 토큰 발급 (HTTP)
   - 세션 정보(프롬프트, 사용자/레시피 정보) 조회 (HTTP)
   만 담당한다. 즉, 음성 오디오 스트림은 Python 서버를 거치지 않는다.
   나머지 모든 로직(타이머, 단계 감지 등)은 TypeScript에서 처리한다.
"""

import os
from pathlib import Path
from typing import Any, List, Dict, Optional
from dotenv import load_dotenv

import requests
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from crud import recipe_crud, user_crud
from db.session import get_db
from difflib import SequenceMatcher
import re

from services.conversation_logger import get_conversation_logger, ConversationEntry

env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=env_path)

router = APIRouter(prefix="/assistant", tags=["assistant"])

# --------- HTTP: 세션 정보 조회 ---------
@router.get("/session-info/{user_id}/{recipe_id}")
async def get_session_info(
    user_id: int,
    recipe_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """사용자/레시피 정보 조회 및 시스템 프롬프트 생성하여 반환."""
    
    profile = user_crud.get_user_by_id(db, user_id)
    print(profile)
    recipe = recipe_crud.get_recipe_by_id(db, recipe_id)
    print(recipe)

    if not profile or not recipe:
        raise HTTPException(status_code=404, detail="User or recipe not found")
    
    user_profile = {
        "knife_skill": "사용 가능" if getattr(profile, "can_use_knife", False) else "서툼",
        "stove_skill": "사용 가능" if getattr(profile, "can_use_fire", False) else "서툼",
        "scissors_skill": "사용 가능" if getattr(profile, "can_use_scissors", False) else "서툼",
        "peeler_skill": "사용 가능" if getattr(profile, "can_use_peeler", False) else "서툼",
        "allergy": getattr(profile, "allergy", "") or "없음",
        "menu": getattr(recipe, "name", "요리"),
    }
    
    ingredients_text = getattr(recipe, "materials", "") or ""
    tools_text = getattr(recipe, "tools", "") or ""
    
    # 레시피 단계 조회
    from models.recipe.recipe_step import RecipeStep
    steps = db.query(RecipeStep).filter(RecipeStep.recipe_id == recipe_id).order_by(RecipeStep.step).all()
    recipe_steps = [{"step": step.step, "text": step.text or ""} for step in steps]
    
    # 시스템 프롬프트 생성
    if recipe_steps:
        recipe_steps_text = ",\n            ".join([f'{s["step"]}: "{s["text"]}"' for s in recipe_steps])
    else:
        recipe_steps_text = getattr(recipe, "instructions", "") or "레시피 단계 정보가 없습니다."

    system_prompt = f"""너는 아동을 위한 친절한 요리 보조 AI "셰프얌"이야. 모든 입출력은 한국어로만 해. 존댓말은 쓰지마.
    ### 단계 진행 규칙
    1. 사용자가 여러 단계를 이미 완료했다고 말하면 해당 단계들을 모두 완료한 것으로 인정하고, 다음 해야 할 단계로 바로 넘어가.
    예) "손 씻고 도구도 준비해왔어" → 1, 2단계 완료로 인정 후 3단계 안내
    예) "불 켜고 기름도 뒀어" → 6, 7단계 완료로 인정 후 8단계 안내
    2. 사용자가 현재 단계보다 앞선 단계를 이미 했다고 하면 그대로 인정하고 이후 단계를 안내해. 단계 순서에 과하게 집착하지 마.
    3. 현재 단계에 대한 추가 설명(타이머, 팁, 대체재료 등)을 줄 때는 다음 단계를 먼저 말하지 마.
    4. 사용자가 재료를 쿠팡에서 구매하길 원하면 open_coupang 도구를 호출해서 검색 페이지를 열어줘.
    5. 사용자가 요리나 식재료의 영양 정보(칼로리, 탄수화물, 지방, 단백질 등)를 물어보면 searchFoodNutrition 도구를 사용하여 정확한 정보를 검색 후 친절하게 알려줘.

    오늘 만들 요리: {user_profile["menu"]}
    사용할 재료: {ingredients_text}
    사용할 조리도구: {tools_text}
    알레르기: {user_profile["allergy"]}
    요리 단계:
        {recipe_steps_text}
    ### 답변 규칙
    - 한 번에 단계 하나만 말해. 여러 단계를 한 문단에 몰아서 말하지 마.
    - 각 단계 끝에는 "준비되면 말해줘."라고 항상 짧게 물어봐."""


    return {
        "system_prompt": system_prompt.strip(),
        "user_profile": user_profile,
        "ingredients": ingredients_text,
        "tools": tools_text,
    }

# --------- HTTP: Realtime 세션 토큰 발급 ---------
class RealtimeSessionRequest(BaseModel):
    """프론트에서 요청하는 모델/보이스/맞춤 인스트럭션 정보."""

    model: str = "gpt-4o-mini-realtime-preview"
    voice: str = "ash"
    instructions: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None  # 프론트엔드에서 전달받은 툴 정의

@router.post("/openai-realtime/session")
async def create_openai_realtime_session(payload: RealtimeSessionRequest) -> Dict[str, Any]:
    """Step 2. 브라우저가 WebRTC 제안을 만들기 전에 에페메럴 토큰을 발급받는다.
    
    If tools are not provided by frontend, loads tools from MCPClientsManager.
    """

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")

    # 프론트엔드에서 전달받은 툴 사용 (없으면 MCP 매니저에서 로드)
    tools = payload.tools if payload.tools else []
    
    # If no tools provided, try to load from MCP manager
    if not tools:
        try:
            from services.mcp_clients_manager import get_mcp_manager
            manager = await get_mcp_manager()
            mcp_tools = await manager.tools_for_openai()
            tools = mcp_tools
            print(f"📋 [Session] Loaded {len(tools)} tools from MCP manager")
        except Exception as e:
            print(f"⚠️ [Session] Failed to load MCP tools: {e}")
            tools = []

    body = {
        "model": payload.model,
        "voice": payload.voice or "ash",
        "modalities": ["text", "audio"],
        "input_audio_transcription": {
            "model": "whisper-1",
            "language": "ko",  # 한국어 고정 - 배경 소음을 영어/일본어로 오인식 방지
        },
        "turn_detection": {
            "type": "server_vad",
            "threshold": 0.85,           # 기본값 0.5 → 높일수록 발화 감지 덜 민감 (배경음 무시)
            "prefix_padding_ms": 300,   # 발화 시작 전 여백
            "silence_duration_ms": 700, # 침묵 700ms 후 발화 종료로 판단 (기본 500ms보다 여유)
        },
        "instructions": payload.instructions or "",
        "tools": tools,
        "tool_choice": "auto",
    }

    response = requests.post(
        "https://api.openai.com/v1/realtime/sessions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    session = response.json()
    return session

# --------- MCP Tool 엔드포인트 ---------
class StartTimerRequest(BaseModel):
    """타이머 시작 요청."""
    step: int
    duration: int
    message: Optional[str] = None

class SendVideoUrlRequest(BaseModel):
    """비디오 URL 조회 요청."""
    step: Optional[int] = None  # 선택사항 (텍스트 매칭 시 사용 안 함)
    recipe_id: Optional[int] = None
    text: Optional[str] = None  # LLM 출력 텍스트 (유사도 비교용)

def calculate_similarity(text1: str, text2: str) -> float:
    """두 텍스트 간의 유사도를 계산합니다 (0.0 ~ 1.0)."""
    # 공백 제거 및 소문자 변환
    text1_clean = re.sub(r'\s+', '', text1.lower())
    text2_clean = re.sub(r'\s+', '', text2.lower())
    
    # SequenceMatcher를 사용한 유사도 계산
    similarity = SequenceMatcher(None, text1_clean, text2_clean).ratio()
    
    # 키워드 매칭 보너스 (공통 키워드가 많을수록 높은 점수)
    words1 = set(re.findall(r'\w+', text1_clean))
    words2 = set(re.findall(r'\w+', text2_clean))
    if words1 and words2:
        keyword_overlap = len(words1 & words2) / len(words1 | words2)
        similarity = (similarity * 0.7) + (keyword_overlap * 0.3)
    
    return similarity

@router.post("/mcp/tools/start_timer")
async def mcp_start_timer(
    request: StartTimerRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    타이머 시작 요청을 처리합니다.
    실제 타이머는 클라이언트에서 실행되지만, 서버에서 검증 및 기록을 수행합니다.
    """
    step = request.step
    duration = request.duration
    message = request.message or f"{duration}초 타이머가 시작되었습니다."
    
    print(f"⏰ [Timer] Step {step} 타이머 시작: {duration}초")
    
    return {
        "success": True,
        "step": step,
        "duration": duration,
        "message": message,
    }

@router.post("/mcp/tools/send_video_url")
async def mcp_send_video_url(
    request: SendVideoUrlRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    특정 레시피 단계의 비디오 URL을 조회합니다.
    text 파라미터가 제공되면 텍스트 유사도 기반으로 가장 적합한 단계를 찾습니다.
    """
    recipe_id = request.recipe_id or 42  # 기본값
    
    try:
        from models.recipe.recipe_step import RecipeStep
        
        # 모든 단계 조회
        all_steps = db.query(RecipeStep).filter(
            RecipeStep.recipe_id == recipe_id
        ).order_by(RecipeStep.step).all()
        
        if not all_steps:
            return {
                "success": False,
                "step": request.step or 0,
                "url": "",
                "recipe_id": recipe_id,
                "error": "No steps found for this recipe",
            }
        
        # text가 제공된 경우: 유사도 기반 매칭
        if request.text:
            query_text = request.text.strip()
            print(f"🔍 [Video] 텍스트 기반 검색: '{query_text}'")
            
            best_match = None
            best_similarity = 0.0
            best_step = None
            
            for step in all_steps:
                if not step.text:
                    continue
                
                similarity = calculate_similarity(query_text, step.text)
                print(f"  Step {step.step}: 유사도 {similarity:.3f} - '{step.text[:30]}...'")
                
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = step
                    best_step = step.step
            
            if best_match and best_similarity > 0.3:  # 최소 유사도 임계값
                video_url = best_match.url or ""
                print(f"✅ [Video] 매칭된 Step {best_step}: 유사도 {best_similarity:.3f}, URL: {video_url or 'No URL'}")
                return {
                    "success": True,
                    "step": best_step,
                    "url": video_url,
                    "recipe_id": recipe_id,
                    "similarity": round(best_similarity, 3),
                    "matched_text": best_match.text,
                }
            else:
                print(f"⚠️ [Video] 유사도가 낮아 매칭 실패 (최고 유사도: {best_similarity:.3f})")
                # 유사도가 낮으면 step 파라미터로 폴백
                if request.step:
                    step_video = recipe_crud.get_step_video(db, recipe_id, request.step)
                    video_url = step_video.url if step_video and step_video.url else ""
                    return {
                        "success": True,
                        "step": request.step,
                        "url": video_url,
                        "recipe_id": recipe_id,
                        "similarity": 0.0,
                        "fallback": True,
                    }
        
        # text가 없거나 매칭 실패 시: step 번호로 직접 조회
        step = request.step
        if not step:
            # step도 없으면 첫 번째 단계 반환
            step = all_steps[0].step
        
        step_video = recipe_crud.get_step_video(db, recipe_id, step)
        video_url = step_video.url if step_video and step_video.url else ""
        
        print(f"🎥 [Video] Recipe {recipe_id}, Step {step}: {video_url or 'No video found'}")
        
        return {
            "success": True,
            "step": step,
            "url": video_url,
            "recipe_id": recipe_id,
        }
    except Exception as e:
        print(f"❌ [Video] Error loading step video: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "step": request.step or 0,
            "url": "",
            "recipe_id": recipe_id,
            "error": str(e),
        }


# --------- Tavily Web Search MCP Tool ---------
class WebSearchRequest(BaseModel):
    """웹 검색 요청."""
    query: str
    max_results: Optional[int] = 5


@router.post("/mcp/tools/web_search")
async def mcp_web_search(request: WebSearchRequest) -> Dict[str, Any]:
    """
    Tavily MCP를 통해 웹 검색을 수행합니다.
    요리 관련 정보, 재료 대체재, 구매처 등을 검색합니다.
    """
    from services.mcp_clients_manager import get_mcp_manager
    
    try:
        manager = await get_mcp_manager()
        result = await manager.tool_call(
            server_id="tavily-remote-mcp",
            tool_name="search",
            arguments={
                "query": request.query,
                "max_results": request.max_results or 5
            }
        )
        
        print(f"🔍 [WebSearch] Query: {request.query}")
        return {
            "success": True,
            "query": request.query,
            **result
        }
        
    except Exception as e:
        print(f"❌ [WebSearch] Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "query": request.query,
            "error": str(e),
            "results": [],
        }


# --------- Coupang 쇼핑 도구 (Selenium 기반) ---------
class OpenCoupangRequest(BaseModel):
    """쿠팡 검색 요청."""
    query: str  # 검색할 재료/상품명


@router.post("/mcp/tools/open_coupang")
async def mcp_open_coupang(request: OpenCoupangRequest) -> Dict[str, Any]:
    """
    Selenium을 사용하여 쿠팡에서 재료를 검색합니다.
    브라우저를 열어 쿠팡 검색 결과 페이지로 이동합니다.
    """
    from services.coupang_service import open_coupang_search
    
    try:
        result = await open_coupang_search(request.query)
        print(f"🛒 [Coupang] 검색: {request.query}")
        return result
    except Exception as e:
        print(f"❌ [Coupang] Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "query": request.query,
            "error": str(e),
            "message": f"쿠팡 검색 중 오류가 발생했어. 직접 쿠팡에서 '{request.query}'를 검색해봐.",
        }


# --------- Food Nutrition MCP Tool (k-mfds-fooddb) ---------
class SearchFoodNutritionRequest(BaseModel):
    foodNameKr: Optional[str] = None
    makerName: Optional[str] = None
    foodCategory1Name: Optional[str] = None
    pageNo: Optional[int] = 1
    numOfRows: Optional[int] = 5

@router.post("/mcp/tools/search_food_nutrition")
async def mcp_search_food_nutrition(request: SearchFoodNutritionRequest) -> Dict[str, Any]:
    """
    식약처 영양성분 DB를 검색합니다.
    """
    from services.mcp_clients_manager import get_mcp_manager
    
    try:
        manager = await get_mcp_manager()
        result = await manager.tool_call(
            server_id="k-mfds-fooddb",
            tool_name="searchFoodNutrition",
            arguments={
                "foodNameKr": request.foodNameKr,
                "makerName": request.makerName,
                "foodCategory1Name": request.foodCategory1Name,
                "pageNo": request.pageNo or 1,
                "numOfRows": request.numOfRows or 5,
            }
        )
        print(f"🥦 [Nutrition] 검색: {request.foodNameKr or request.foodCategory1Name or '전체'}")
        return {
            "success": True,
            **result
        }
    except Exception as e:
        print(f"❌ [Nutrition] Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "content": []
        }


# NOTE: Playwright MCP 엔드포인트 제거됨
# - browser_navigate, browser_search, browser_get_content
# - 이유: Playwright MCP는 browser_drag, browser_click 등 세부 함수가 많아
#   Realtime API에 연결 시 토큰 소비가 과도함


# --------- MCP Bridge Endpoints ---------
# Generic MCP tool calling via MCPClientsManager (better-chatbot pattern)

class MCPToolCallRequest(BaseModel):
    """Request to call a tool on an MCP server."""
    server_id: str  # MCP server ID (e.g., "playwright", "tavily")
    tool_name: str  # Tool name on that server
    arguments: Dict[str, Any] = {}


class MCPToolCallByIdRequest(BaseModel):
    """Request to call a tool using combined tool_id."""
    tool_id: str  # Combined ID in format "server_name:tool_name"
    arguments: Dict[str, Any] = {}


@router.post("/mcp/call")
async def mcp_call_tool(request: MCPToolCallRequest) -> Dict[str, Any]:
    """
    Generic endpoint to call any MCP server tool.
    
    This is the bridge endpoint that forwards tool calls from the frontend
    to the actual MCP servers via MCPClientsManager.
    
    Equivalent to better-chatbot's callMcpToolAction().
    """
    from services.mcp_clients_manager import get_mcp_manager
    
    try:
        manager = await get_mcp_manager()
        result = await manager.tool_call(
            server_id=request.server_id,
            tool_name=request.tool_name,
            arguments=request.arguments
        )
        
        print(f"🔧 [MCP] Called {request.server_id}:{request.tool_name}")
        return {
            "success": True,
            **result
        }
        
    except Exception as e:
        print(f"❌ [MCP] Tool call error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "isError": True,
            "error": {"name": "MCPToolCallError", "message": str(e)},
            "content": []
        }


@router.post("/mcp/call-by-id")
async def mcp_call_tool_by_id(request: MCPToolCallByIdRequest) -> Dict[str, Any]:
    """
    Call a tool using the combined tool_id (server_name:tool_name).
    
    This is useful when the frontend has the tool_id from the tools list.
    """
    from services.mcp_clients_manager import get_mcp_manager
    
    try:
        manager = await get_mcp_manager()
        result = await manager.tool_call_by_tool_id(
            tool_id=request.tool_id,
            arguments=request.arguments
        )
        
        print(f"🔧 [MCP] Called tool_id: {request.tool_id}")
        return {
            "success": True,
            **result
        }
        
    except Exception as e:
        print(f"❌ [MCP] Tool call error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "isError": True,
            "error": {"name": "MCPToolCallError", "message": str(e)},
            "content": []
        }


@router.get("/mcp/tools")
async def mcp_list_tools() -> Dict[str, Any]:
    """
    List all available tools from connected MCP servers.
    
    Returns tools in OpenAI Realtime session format for binding.
    """
    from services.mcp_clients_manager import get_mcp_manager
    
    try:
        manager = await get_mcp_manager()
        tools = await manager.tools_for_openai()
        
        print(f"📋 [MCP] Listed {len(tools)} tools")
        return {
            "success": True,
            "tools": tools,
            "count": len(tools)
        }
        
    except Exception as e:
        print(f"❌ [MCP] List tools error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "tools": [],
            "count": 0,
            "error": str(e)
        }


@router.get("/mcp/servers")
async def mcp_list_servers() -> Dict[str, Any]:
    """
    List all configured MCP servers and their status.
    """
    from services.mcp_clients_manager import get_mcp_manager
    
    try:
        manager = await get_mcp_manager()
        clients = manager.get_clients()
        
        servers = [
            {
                "id": c["id"],
                **c["client"].get_info()
            }
            for c in clients
        ]
        
        return {
            "success": True,
            "servers": servers,
            "count": len(servers)
        }
        
    except Exception as e:
        print(f"❌ [MCP] List servers error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "servers": [],
            "count": 0,
            "error": str(e)
        }


# --------- Conversation Logging Endpoints ---------
# 대화 로깅 API - 프롬프트, 사용자 음성, API 응답 저장

class StartConversationLogRequest(BaseModel):
    """대화 로그 세션 시작 요청."""
    session_id: str
    user_id: Optional[int] = None
    recipe_id: Optional[int] = None
    system_prompt: Optional[str] = None


class LogConversationEntryRequest(BaseModel):
    """대화 로그 항목 추가 요청."""
    session_id: str
    role: str  # "user", "assistant", "system", "tool_call", "tool_result"
    content: str
    metadata: Optional[Dict[str, Any]] = None


class LogToolCallRequest(BaseModel):
    """도구 호출 로그 요청."""
    session_id: str
    tool_name: str
    arguments: Dict[str, Any]
    call_id: str


class LogToolResultRequest(BaseModel):
    """도구 결과 로그 요청."""
    session_id: str
    tool_name: str
    result: Any
    call_id: str


class EndConversationLogRequest(BaseModel):
    """대화 로그 세션 종료 요청."""
    session_id: str
    token_usage: Optional[Dict[str, Any]] = None


@router.post("/conversation-log/start")
async def start_conversation_log(request: StartConversationLogRequest) -> Dict[str, Any]:
    """대화 로깅 세션을 시작합니다."""
    logger = get_conversation_logger()
    session = logger.start_session(
        session_id=request.session_id,
        user_id=request.user_id,
        recipe_id=request.recipe_id,
        system_prompt=request.system_prompt,
    )
    
    return {
        "success": True,
        "session_id": session.session_id,
        "started_at": session.started_at,
    }


@router.post("/conversation-log/entry")
async def log_conversation_entry(request: LogConversationEntryRequest) -> Dict[str, Any]:
    """대화 항목을 로그에 추가합니다."""
    logger = get_conversation_logger()
    success = logger.log_entry(
        session_id=request.session_id,
        role=request.role,
        content=request.content,
        metadata=request.metadata,
    )
    
    return {"success": success}


@router.post("/conversation-log/tool-call")
async def log_tool_call(request: LogToolCallRequest) -> Dict[str, Any]:
    """도구 호출을 로그에 추가합니다."""
    logger = get_conversation_logger()
    success = logger.log_tool_call(
        session_id=request.session_id,
        tool_name=request.tool_name,
        arguments=request.arguments,
        call_id=request.call_id,
    )
    
    return {"success": success}


@router.post("/conversation-log/tool-result")
async def log_tool_result(request: LogToolResultRequest) -> Dict[str, Any]:
    """도구 호출 결과를 로그에 추가합니다."""
    logger = get_conversation_logger()
    success = logger.log_tool_result(
        session_id=request.session_id,
        tool_name=request.tool_name,
        result=request.result,
        call_id=request.call_id,
    )
    
    return {"success": success}


@router.post("/conversation-log/end")
async def end_conversation_log(request: EndConversationLogRequest) -> Dict[str, Any]:
    """대화 로깅 세션을 종료하고 파일로 저장합니다."""
    logger = get_conversation_logger()
    
    # 토큰 사용량 설정 (있는 경우)
    if request.token_usage:
        logger.set_token_usage(
            session_id=request.session_id,
            token_usage=request.token_usage,
        )
    
    filepath = logger.end_session(request.session_id)
    
    return {
        "success": filepath is not None,
        "filepath": filepath,
    }


@router.get("/conversation-log/sessions")
async def list_conversation_sessions(limit: int = 20) -> Dict[str, Any]:
    """저장된 대화 세션 목록을 반환합니다."""
    logger = get_conversation_logger()
    sessions = logger.list_sessions(limit=limit)
    
    return {
        "success": True,
        "sessions": sessions,
        "count": len(sessions),
    }


@router.get("/conversation-log/session/{filename}")
async def get_conversation_session(filename: str) -> Dict[str, Any]:
    """특정 대화 세션 로그를 조회합니다."""
    logger = get_conversation_logger()
    session_data = logger.get_session_log(filename)
    
    if not session_data:
        raise HTTPException(status_code=404, detail="Session log not found")
    
    return {
        "success": True,
        "session": session_data,
    }
