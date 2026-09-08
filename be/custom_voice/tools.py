"""Custom cascade에서 LLM function call을 실제 UI 이벤트로 바꾸는 계층."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Any, Awaitable, Callable
from urllib.parse import quote_plus


# OpenAI 호환 Chat Completions에서 사용하는 독립 function schema이다.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "navigate_cooking_step",
            "description": "요리 화면을 다음, 이전 또는 지정 단계로 이동한다.",
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
    {
        "type": "function",
        "function": {
            "name": "changeBrowserTheme",
            "description": "화면 테마를 바꾼다.",
            "parameters": {
                "type": "object",
                "properties": {"theme": {"type": "string", "enum": ["light", "dark"]}},
                "required": ["theme"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "재료 대체품, 구매처, 조리 팁처럼 최신 정보가 필요한 요리 질문을 검색한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
        },
    },
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
    {
        "type": "function",
        "function": {
            "name": "searchFoodNutrition",
            "description": "식품의약품안전처 영양성분 DB에서 음식 정보를 검색한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "foodNameKr": {"type": "string"},
                    "makerName": {"type": "string"},
                    "foodCategory1Name": {"type": "string"},
                    "pageNo": {"type": "integer", "minimum": 1},
                    "numOfRows": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["foodNameKr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "endConversation",
            "description": "사용자가 명확히 종료를 요청했을 때 음성 대화를 끝낸다.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


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
            if name == "navigate_cooking_step":
                action = str(arguments.get("action", "next"))
                if action not in {"next", "prev", "set"}:
                    raise ValueError("action must be next, prev, or set")
                event = {"type": "navigate_step", "action": action}
                if action == "set":
                    event["targetStep"] = max(1, int(arguments.get("target_step", 1)))
                await self._send_event({"type": "assistant_event", "event": event})
                result = {"success": True, "action": action, "target_step": event.get("targetStep")}
            elif name == "start_timer":
                step = max(1, int(arguments.get("step", 1)))
                duration = min(7200, max(1, int(arguments.get("duration", 1))))
                message = str(arguments.get("message") or f"{step}단계 타이머가 끝났어.")
                await self._send_event(
                    {
                        "type": "assistant_event",
                        "event": {"type": "timer_start", "step": step, "time": duration, "message": message},
                    }
                )
                result = {"success": True, "step": step, "duration": duration}
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
                    {"type": "assistant_event", "event": {"type": "open_url", "url": url}}
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
