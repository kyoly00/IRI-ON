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

import httpx
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
    recipe = recipe_crud.get_recipe_model_by_id(db, recipe_id)

    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    
    user_profile = {
        # 비로그인/개발 환경에서도 레시피 동행은 시작할 수 있게 보수적인 기본값을 쓴다.
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
    recipe_steps = [
        {
            "step": step.step,
            "text": step.text or "",
            "duration": step.step_len,
        }
        for step in steps
    ]

    # 아직 영상 타임라인을 만들지 않은 레시피는 원 레시피 단계를 음성 안내에 사용한다.
    if not recipe_steps:
        from services.youtube_recipe_timeline import parse_recipe_steps
        recipe_steps = [
            {"step": index, "text": text, "duration": None}
            for index, text in enumerate(parse_recipe_steps(recipe.instructions), start=1)
        ]
    
    # 시스템 프롬프트 생성
    if recipe_steps:
        recipe_steps_text = ",\n            ".join(
            [
                f'{s["step"]}: "{s["text"]}"'
                + (f' (영상 {s["duration"]}초)' if s["duration"] else "")
                for s in recipe_steps
            ]
        )
    else:
        recipe_steps_text = getattr(recipe, "instructions", "") or "레시피 단계 정보가 없습니다."

    system_prompt = f"""너는 아동(어린이)을 위한 다정하고 친절한 요리 친구 AI "셰프얌"이야.
모든 입출력은 한국어로만 해. 절대 존댓말(~해요, ~합니다)을 쓰지 말고, 항상 다정하고 신나는 반말(~해, ~야, ~하자!)을 써.

### 🌟 성격 및 어조 가이드
- 어린이가 쉽게 따라 할 수 있도록 쉬운 단어와 친절한 비유를 사용해.
- '필링', '시즈닝', '가니쉬', 'Ts' 같은 어려운 요리 용어는 쓰지 마.
  (예: '필링' -> '속재료', '1Ts' -> '밥숟가락 1큰술', '1ts' -> '작은 티스푼 1작은술')
- 어린이가 한 단계를 마칠 때마다 "와, 정말 멋져!", "참 잘했어!" 하고 칭찬과 격려를 아끼지 마.

### 📋 단계 진행 및 영상 도구 규칙
1. **시작 안내**: 대화 시작 시 손 씻기는 요리 전 위생 안내이며, 손을 씻고 나면 반드시 **요리 단계 1번(1단계)**부터 차근차근 시작해. (절대 1단계를 건너뛰고 2단계로 가지 마!)
2. **한 번에 딱 하나만**: 어린이가 헷갈리지 않게 한 번에 한 단계의 조리 행동만 안내해. 여러 단계를 한꺼번에 묶어서 설명하지 마.
3. **영상 제어 도구 호출 (중요)**:
   - 다음 단계로 넘어갈 때(사용자가 "다 했어", "다음 보여줘" 하거나 새로운 단계를 안내할 때): 반드시 `navigate_cooking_step(action="next")` 도구를 함께 호출해 화면 영상도 함께 넘겨줘.
   - 이전 단계로 돌아갈 때: `navigate_cooking_step(action="prev")` 도구를 호출해.
   - 특정 단계를 건너뛰거나 지정할 때: `navigate_cooking_step(action="set", target_step=N)` 도구를 호출해.
4. **마무리 확인 멘트**: 각 단계 설명을 마친 뒤에는 항상 "다 했으면 '다 했어'라고 말해줘!" 또는 "준비되면 말해줘!"라고 짧게 물어봐.
5. **안전 주의사항**: 불, 뜨거운 기름, 칼, 가위, 에어프라이어를 쓸 때는 "손 조심하고 천천히 해!"라고 꼭 안전 주의를 줘.
6. **쇼핑 및 영양**:
   - 재료 구매 질문: `open_coupang` 도구 호출
   - 영양 정보 질문: `searchFoodNutrition` 도구 호출

오늘 만들 요리: {user_profile["menu"]}
사용할 재료: {ingredients_text}
사용할 조리도구: {tools_text}
알레르기: {user_profile["allergy"]}
요리 단계:
    {recipe_steps_text}"""


    return {
        "system_prompt": system_prompt.strip(),
        "user_profile": user_profile,
        "ingredients": ingredients_text,
        "tools": tools_text,
    }

# --------- HTTP: Realtime 세션 토큰 발급 ---------
class RealtimeSessionRequest(BaseModel):
    """프론트에서 요청하는 모델/보이스/맞춤 인스트럭션 정보."""
    model: str = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime")
    voice: str = "ash"
    instructions: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None  # 프론트엔드에서 전달받은 툴 정의

@router.post("/openai-realtime/session")
async def create_openai_realtime_session(payload: RealtimeSessionRequest) -> Dict[str, Any]:
    """
    OpenAI Realtime WebRTC용 ephemeral client secret 발급.

    Frontend에서 tools를 전달하지 않은 경우
    MCPClientsManager에서 OpenAI function tool 형식으로 가져옵니다.
    """

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")

    # 1. Tools
    tools = payload.tools if payload.tools else []
    if not tools:
        try:
            from services.mcp_clients_manager import get_mcp_manager
            manager = await get_mcp_manager()
            tools = await manager.tools_for_openai()
            print(f"📋 [Realtime Session] Loaded {len(tools)} tools from MCP manager")
        except Exception as e:
            print(f"⚠️ [Realtime Session] Failed to load MCP tools: {e}")
            tools = []

    # 2. Model
    stt_model_name = os.getenv("OPENAI_REALTIME_STT_MODEL", "gpt-transcribe")

    # 3. Current Realtime session configuration
    session: Dict[str, Any] = {
        "type": "realtime",
        "model": payload.model,
        "output_modalities": ["audio"],
        "instructions": payload.instructions or "",
        "audio": {
            "input": {
                "transcription": {
                    "model": stt_model_name,
                    "language": "ko",
                    "prompt": (
                        "사용자는 한국어로 말합니다. "
                        "주변의 영어, 일본어 또는 배경 소음을 "
                        "사용자 발화로 오인하지 마세요."
                    ),
                },
                "noise_reduction": {
                    "type": "far_field",
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.85,           # 기본값 0.5 → 높일수록 발화 감지 덜 민감 (배경음 무시)
                    "prefix_padding_ms": 300,   # 발화 시작 전 여백
                    "silence_duration_ms": 700, # 침묵 700ms 후 발화 종료로 판단 (기본 500ms보다 여유)
                    "create_response": True,
                    "interrupt_response": True,
                },
            },
            "output": {
                "voice": payload.voice or "ash",
            },
        },
    }

    # 4. Tools
    if tools:
        session["tools"] = tools
        session["tool_choice"] = "auto"

    body: Dict[str, Any] = {
        "session": session
    }

    # 5. Headers
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 6. Create ephemeral client secret
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                os.getenv("OPENAI_REALTIME_API_URL"),
                headers=headers,
                json=body,
            )
    except httpx.RequestError as e:
        print(f"❌ [Realtime Connection Error] {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to connect to OpenAI Realtime API: {str(e)}",
        )

    # 7. Error handling & response
    if response.status_code >= 400:
        print(f"❌ [Realtime Client Secret Error] Status {response.status_code}: {response.text}")
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text,
        )

    result = response.json()
    session = result.get("session", {})
    print(f"✅ [Realtime Client Secret Created] Model={payload.model}, Session ID={session.get('id')}")

    return result

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
                video_url = best_match.start_url or best_match.url or ""
                print(f"✅ [Video] 매칭된 Step {best_step}: 유사도 {best_similarity:.3f}, URL: {video_url or 'No URL'}")
                return {
                    "success": True,
                    "step": best_step,
                    "url": video_url,
                    "recipe_id": recipe_id,
                    "similarity": round(best_similarity, 3),
                    "matched_text": best_match.text,
                    "video_id": best_match.video_id,
                    "start_seconds": best_match.start_seconds,
                    "step_len": best_match.step_len,
                }
            else:
                print(f"⚠️ [Video] 유사도가 낮아 매칭 실패 (최고 유사도: {best_similarity:.3f})")
                # 유사도가 낮으면 step 파라미터로 폴백
                if request.step:
                    step_video = recipe_crud.get_step_video(db, recipe_id, request.step)
                    video_url = (step_video.start_url or step_video.url) if step_video else ""
                    return {
                        "success": True,
                        "step": request.step,
                        "url": video_url,
                        "recipe_id": recipe_id,
                        "similarity": 0.0,
                        "fallback": True,
                        "step_len": step_video.step_len if step_video else None,
                    }
        
        # text가 없거나 매칭 실패 시: step 번호로 직접 조회
        step = request.step
        if not step:
            # step도 없으면 첫 번째 단계 반환
            step = all_steps[0].step
        
        step_video = recipe_crud.get_step_video(db, recipe_id, step)
        video_url = (step_video.start_url or step_video.url) if step_video else ""
        
        print(f"🎥 [Video] Recipe {recipe_id}, Step {step}: {video_url or 'No video found'}")
        
        return {
            "success": True,
            "step": step,
            "url": video_url,
            "recipe_id": recipe_id,
            "video_id": step_video.video_id if step_video else None,
            "start_seconds": step_video.start_seconds if step_video else None,
            "step_len": step_video.step_len if step_video else None,
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


# --------- Voice AI 평가지표(Metrics) 기록 및 조회 API ---------
class RecordTurnMetricsRequest(BaseModel):
    """단일 턴의 성능 지표 기록 요청."""
    session_id: str
    turn_id: Optional[int] = None
    user_speech_start_ts: Optional[float] = None
    user_speech_end_ts: Optional[float] = None
    stt_completed_ts: Optional[float] = None
    first_token_ts: Optional[float] = None
    first_audio_ts: Optional[float] = None
    response_completed_ts: Optional[float] = None
    interruption_ts: Optional[float] = None
    interruption_stopped_ts: Optional[float] = None
    user_audio_duration_ms: Optional[float] = None
    agent_audio_duration_ms: Optional[float] = None
    input_tokens: Optional[int] = 0
    output_tokens: Optional[int] = 0
    user_transcript: Optional[str] = None
    agent_response: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


@router.post("/conversation-log/turn-metrics")
async def record_turn_metrics(request: RecordTurnMetricsRequest) -> Dict[str, Any]:
    """프론트엔드 또는 음성 파이프라인에서 측정된 단일 턴의 세부 지표를 기록합니다."""
    logger = get_conversation_logger()
    tracker = logger.get_metrics_tracker(request.session_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Active session not found")
    
    from services.voice_metrics import TurnMetrics
    turn = TurnMetrics(
        turn_id=request.turn_id or (len(tracker.turns) + 1),
        user_speech_start_ts=request.user_speech_start_ts,
        user_speech_end_ts=request.user_speech_end_ts,
        stt_completed_ts=request.stt_completed_ts,
        first_token_ts=request.first_token_ts,
        first_audio_ts=request.first_audio_ts,
        response_completed_ts=request.response_completed_ts,
        interruption_ts=request.interruption_ts,
        interruption_stopped_ts=request.interruption_stopped_ts,
        user_audio_duration_ms=request.user_audio_duration_ms,
        agent_audio_duration_ms=request.agent_audio_duration_ms,
        input_tokens=request.input_tokens or 0,
        output_tokens=request.output_tokens or 0,
        user_transcript=request.user_transcript,
        agent_response=request.agent_response,
        tool_calls=request.tool_calls or [],
    )
    tracker.turns.append(turn)
    
    return {
        "success": True,
        "turn": turn.to_dict(),
    }


@router.get("/conversation-log/metrics-summary/{session_id}")
async def get_session_metrics_summary(session_id: str) -> Dict[str, Any]:
    """활성 세션의 실시간 평가지표 요약을 계산하여 반환합니다."""
    logger = get_conversation_logger()
    tracker = logger.get_metrics_tracker(session_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "success": True,
        "summary": tracker.compute_summary(),
    }
