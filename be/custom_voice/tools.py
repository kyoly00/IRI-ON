"""Custom cascade에서 LLM function call을 실제 UI 이벤트로 바꾸는 계층."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
import time
from typing import Any, Awaitable, Callable
from urllib.parse import quote_plus
from uuid import uuid4


# OpenAI 호환 Chat Completions에서 사용하는 독립 function schema이다.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "control_video",
            "description": "사용자가 현재 발화에서 영상을 재생·정지·탐색해 달라고 직접 요청한 경우에만 영상을 조작한다. 단계 이동 요청만으로 호출하지 않는다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["pause", "play", "seek"],
                        "description": "pause: 영상 일시정지(발화 시점 기준), play: 영상 재생, seek: 시간 이동",
                    },
                    "target_seconds": {
                        "type": "number",
                        "description": "이동할 영상 절대 시간(초). 예: 1분 20초면 80",
                    },
                    "offset_seconds": {
                        "type": "number",
                        "description": "현재 위치 기준 상대 이동 시간(초). 예: 10초 전이면 -10, 30초 뒤면 +30",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_cooking_step",
            "description": "사용자가 다음·이전·특정 번호 단계로 이동해 달라고 직접 요청했거나, 현재 화면의 실제 조리 작업을 끝냈다고 분명히 말해 자연스럽게 다음 단계로 이어야 할 때 화면을 이동한다. 다음은 next, 이전은 prev, 번호를 직접 지정한 경우만 set을 사용한다. 손 씻기 같은 시작 전 준비, 단순 단계 설명, 모호한 완료 언급에는 호출하지 않는다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["next", "prev", "set"]},
                    "target_step": {"type": "integer", "minimum": 1},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_timer",
            "description": "현재 조리 단계를 위한 타이머를 시작한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "step": {"type": "integer", "minimum": 1},
                    "duration": {"type": "integer", "minimum": 1, "maximum": 7200},
                    "label": {
                        "type": "string",
                        "description": "사용자가 알아볼 수 있는 짧은 작업명. 예: 닭고기 재우기, 시험용",
                    },
                    "message": {"type": "string"},
                },
                "required": ["step", "duration"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_video_url",
            "description": "지정한 단계의 요리 영상을 화면에 표시한다.",
            "parameters": {
                "type": "object",
                "properties": {"step": {"type": "integer", "minimum": 1}},
                "required": ["step"],
            },
        },
    },
    # {
    #     "type": "function",
    #     "function": {
    #         "name": "changeBrowserTheme",
    #         "description": "화면 테마를 바꾼다.",
    #         "parameters": {
    #             "type": "object",
    #             "properties": {"theme": {"type": "string", "enum": ["light", "dark"]}},
    #             "required": ["theme"],
    #         },
    #     },
    # },
    # {
    #     "type": "function",
    #     "function": {
    #         "name": "web_search",
    #         "description": "재료 대체품, 구매처, 조리 팁처럼 최신 정보가 필요한 요리 질문을 검색한다.",
    #         "parameters": {
    #             "type": "object",
    #             "properties": {
    #                 "query": {"type": "string"},
    #                 "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
    #             },
    #             "required": ["query"],
    #         },
    #     },
    # },
    {
        "type": "function",
        "function": {
            "name": "open_coupang",
            "description": "사용자가 재료 구매를 원할 때 쇼핑 검색 페이지를 연다.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    # {
    #     "type": "function",
    #     "function": {
    #         "name": "searchFoodNutrition",
    #         "description": "식품의약품안전처 영양성분 DB에서 음식 정보를 검색한다.",
    #         "parameters": {
    #             "type": "object",
    #             "properties": {
    #                 "foodNameKr": {"type": "string"},
    #                 "makerName": {"type": "string"},
    #                 "foodCategory1Name": {"type": "string"},
    #                 "pageNo": {"type": "integer", "minimum": 1},
    #                 "numOfRows": {"type": "integer", "minimum": 1, "maximum": 20},
    #             },
    #             "required": ["foodNameKr"],
    #         },
    #     },
    # },
    # {
    #     "type": "function",
    #     "function": {
    #         "name": "endConversation",
    #         "description": "사용자가 명확히 종료를 요청했을 때 음성 대화를 끝낸다.",
    #         "parameters": {"type": "object", "properties": {}, "required": []},
    #     },
    # },
]


def is_explicit_media_control_request(transcript: str) -> bool:
    """영상 조작을 응답 보류 명령과 구분한다.

    이 함수는 답변을 고정하거나 도구를 직접 실행하지 않는다. 정상 대화 모드에서
    ``영상 멈춰`` 같은 UI 명령이 Response Gate의 ``멈춰`` 단어에 가로막히지 않도록
    명령 처리 우선순위만 정한다.
    """

    text = re.sub(r"\s+", "", transcript.lower())
    media_cue = any(cue in text for cue in ("영상", "비디오", "재생화면"))
    control_cue = any(
        cue in text
        for cue in (
            "멈춰",
            "정지",
            "일시정지",
            "재생",
            "돌려",
            "앞으로",
            "뒤로",
            "이동",
        )
    )
    return media_cue and control_cue


def is_navigation_review_candidate(transcript: str) -> bool:
    """맥락형 단계 이동 검토가 필요할 수 있는 발화만 가볍게 선별한다.

    실제 이동 판단은 reviewer와 main LLM이 하며 이 함수는 side-effect를 만들지 않는다.
    """

    text = re.sub(r"\s+", "", transcript.lower())
    return any(
        cue in text
        for cue in (
            "단계",
            "다음",
            "이전",
            "앞단계",
            "전단계",
            "넘어가",
            "이동",
            "다했",
            "다해",
            "끝냈",
            "끝났",
            "완료",
            "해놨어",
            "해놓았",
            "만들었",
            "준비됐",
        )
    )


def select_tool_schemas(transcript: str) -> list[dict[str, Any]]:
    """현재 발화와 무관한 function schema를 API 요청에서 제외한다.

    이 선택은 도구를 실행하지 않는다. 조리 대화의 핵심인 단계 이동 schema는
    자연스러운 표현과 STT 변형을 놓치지 않도록 항상 제공하고, 부가 UI schema만
    명확한 단서가 있을 때 추가한다.
    """
    # A direct media command cannot require a timer or recipe-navigation tool.
    # Narrowing the schema set reduces prompt size and wrong-tool choices while
    # the LLM still decides the concrete action and contextual spoken response.
    if is_explicit_media_control_request(transcript):
        return [
            schema
            for schema in TOOL_SCHEMAS
            if schema["function"]["name"] == "control_video"
        ]

    text = transcript.replace(" ", "").lower()
    # 단계 이동과 타이머는 조리 대화의 핵심 기능이다. 키워드 기반으로 schema를 숨기면
    # STT 변형("타이밍", "10분 있다 올게")에서 존재하는 기능을 모델이 사용할 수 없게 된다.
    wanted: set[str] = {"navigate_cooking_step", "start_timer"}
    if any(token in text for token in ("영상", "비디오", "재생", "일시정지", "멈춰", "되감", "넘겨")):
        wanted.add("control_video")
    if any(token in text for token in ("다음단계", "이전단계", "몇단계", "단계로", "단계로가", "단계보여")):
        wanted.add("navigate_cooking_step")
    if any(token in text for token in ("영상보여", "영상틀어", "영상켜")):
        wanted.add("send_video_url")
    # "영상 3단계 부분 보여줘"처럼 단계 번호가 끼어 있는 요청도
    # 해당 단계의 start_seconds로 플레이어를 이동시켜야 한다.
    if "영상" in text and ("보여" in text or "단계" in text):
        wanted.add("send_video_url")
    if any(token in text for token in ("구매", "주문", "쿠팡", "사줘")):
        wanted.add("open_coupang")
    return [schema for schema in TOOL_SCHEMAS if schema["function"]["name"] in wanted]


@dataclass(frozen=True)
class ToolExecution:
    """추적 저장에 필요한 도구 결과와 실행 시간을 함께 반환한다."""

    result: dict[str, Any]
    duration_ms: float
    success: bool


class ToolExecutor:
    """브라우저가 수행해야 하는 side effect를 구조화 이벤트로 전달한다."""

    def __init__(self, send_event: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._send_event = send_event

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolExecution:
        """허용 목록에 있는 도구만 검증해 실행하고 결과를 LLM으로 되돌린다."""

        started = time.perf_counter()
        try:
            if name == "control_video":
                action = str(arguments.get("action") or "").lower()
                if action not in {"pause", "play", "seek"}:
                    raise ValueError("action must be pause, play, or seek")
                event: dict[str, Any] = {"type": "video_control", "action": action}
                target_seconds = arguments.get("target_seconds")
                if target_seconds is not None:
                    try:
                        event["targetSeconds"] = float(target_seconds)
                    except (TypeError, ValueError):
                        pass
                offset_seconds = arguments.get("offset_seconds")
                if offset_seconds is not None:
                    try:
                        event["offsetSeconds"] = float(offset_seconds)
                    except (TypeError, ValueError):
                        pass
                # 사용자 발화 시점 기준 지연 보정값(초)
                event["rollbackSeconds"] = 1.5
                await self._send_event({"type": "assistant_event", "event": event})
                result = {"success": True, "action": action, **{k: v for k, v in event.items() if k != "type"}}
            elif name == "navigate_cooking_step":
                action = str(arguments.get("action") or "")
                if action not in {"next", "prev", "set"}:
                    raise ValueError("action must be next, prev, or set")
                # Runtime이 UI event 전송 전에 pending 상태를 만들 수 있도록 주입된
                # correlation id를 우선 사용한다. 독립 호출은 기존처럼 여기서 생성한다.
                navigation_id = str(arguments.get("navigation_id") or uuid4().hex)
                event = {"type": "navigate_step", "action": action, "navigation_id": navigation_id}
                if action == "set":
                    if arguments.get("target_step") is None:
                        raise ValueError("target_step is required when action is set")
                    event["targetStep"] = max(1, int(arguments["target_step"]))
                await self._send_event({"type": "assistant_event", "event": event})
                result = {
                    "success": True,
                    "action": action,
                    "target_step": event.get("targetStep"),
                    "navigation_id": navigation_id,
                }
            elif name == "start_timer":
                if arguments.get("step") is None or arguments.get("duration") is None:
                    raise ValueError("step and duration are required")
                step = max(1, int(arguments["step"]))
                duration = min(7200, max(1, int(arguments["duration"])))
                timer_id = uuid4().hex
                label = str(arguments.get("label") or f"{step}단계 타이머").strip()[:80]
                message = str(arguments.get("message") or f"{label}가 끝났어.")[:160]
                started_at = time.time()
                await self._send_event(
                    {
                        "type": "assistant_event",
                        "event": {
                            "type": "timer_start",
                            "timer_id": timer_id,
                            "step": step,
                            "time": duration,
                            "label": label,
                            "message": message,
                            "started_at": started_at,
                            "ends_at": started_at + duration,
                        },
                    }
                )
                result = {
                    "success": True,
                    "timer_id": timer_id,
                    "step": step,
                    "duration": duration,
                    "label": label,
                    "message": message,
                    "started_at": started_at,
                    "ends_at": started_at + duration,
                }
            elif name == "send_video_url":
                step = max(1, int(arguments.get("step", 1)))
                await self._send_event(
                    {"type": "assistant_event", "event": {"type": "video", "step": step, "data": ""}}
                )
                result = {"success": True, "step": step}
            elif name == "changeBrowserTheme":
                theme = str(arguments.get("theme", "light"))
                if theme not in {"light", "dark"}:
                    raise ValueError("theme must be light or dark")
                await self._send_event(
                    {"type": "assistant_event", "event": {"type": "theme", "theme": theme}}
                )
                result = {"success": True, "theme": theme}
            elif name == "web_search":
                query = str(arguments.get("query", "")).strip()
                if not query:
                    raise ValueError("query is required")
                max_results = min(10, max(1, int(arguments.get("max_results", 5))))
                # 기존 Realtime 라우터가 아닌 공용 MCP manager를 직접 호출해 구현을 분리한다.
                from services.mcp_clients_manager import get_mcp_manager

                manager = await get_mcp_manager()
                search_result = await manager.tool_call(
                    server_id="tavily-remote-mcp",
                    tool_name="search",
                    arguments={"query": query, "max_results": max_results},
                )
                result = {"success": True, "query": query, **search_result}
            elif name == "open_coupang":
                query = str(arguments.get("query", "")).strip()
                if not query:
                    raise ValueError("query is required")
                url = f"https://www.coupang.com/np/search?q={quote_plus(query)}"
                await self._send_event(
                    {
                        "type": "assistant_event",
                        "event": {"type": "open_url", "url": url, "query": query},
                    }
                )
                result = {"success": True, "query": query, "url": url}
            elif name == "searchFoodNutrition":
                food_name = str(arguments.get("foodNameKr", "")).strip()
                if not food_name:
                    raise ValueError("foodNameKr is required")
                from services.mcp_clients_manager import get_mcp_manager

                manager = await get_mcp_manager()
                nutrition = await manager.tool_call(
                    server_id="k-mfds-fooddb",
                    tool_name="searchFoodNutrition",
                    arguments={
                        "foodNameKr": food_name,
                        "makerName": str(arguments.get("makerName", "")),
                        "foodCategory1Name": str(arguments.get("foodCategory1Name", "")),
                        "pageNo": max(1, int(arguments.get("pageNo", 1))),
                        "numOfRows": min(20, max(1, int(arguments.get("numOfRows", 5)))),
                    },
                )
                result = {"success": True, **nutrition}
            elif name == "endConversation":
                await self._send_event(
                    {"type": "assistant_event", "event": {"type": "end_conversation"}}
                )
                result = {"success": True}
            else:
                raise ValueError(f"Unknown tool: {name}")
            return ToolExecution(result, (time.perf_counter() - started) * 1000.0, True)
        except Exception as exc:
            # 인자 검증/MCP 오류를 tool result로 반환해 LLM이 설명하거나 스스로 고칠 수 있게 한다.
            await asyncio.sleep(0)
            return ToolExecution(
                {"success": False, "error": str(exc)},
                (time.perf_counter() - started) * 1000.0,
                False,
            )
