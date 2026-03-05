"""대화 로깅 서비스.

API 프롬프트와 응답, 사용자 음성 대화를 로그 파일로 저장합니다.
토큰 사용량, 인식 결과, 응답 품질 테스트용으로 활용합니다.
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


# 로그 저장 폴더 경로 (be 폴더 기준)
LOG_DIR = Path(__file__).resolve().parents[1] / "conversation_logs"


class ConversationEntry(BaseModel):
    """개별 대화 항목."""
    timestamp: str
    role: str  # "user", "assistant", "system", "tool_call", "tool_result"
    content: str
    metadata: Optional[Dict[str, Any]] = None  # 토큰, 지연시간 등


class ConversationSession(BaseModel):
    """대화 세션."""
    session_id: str
    user_id: Optional[int] = None
    recipe_id: Optional[int] = None
    started_at: str
    ended_at: Optional[str] = None
    system_prompt: Optional[str] = None
    entries: List[ConversationEntry] = []
    token_usage: Optional[Dict[str, Any]] = None


class ConversationLogger:
    """대화 로깅 관리자."""
    
    def __init__(self) -> None:
        # 로그 폴더 생성
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._active_sessions: Dict[str, ConversationSession] = {}
    
    def start_session(
        self,
        session_id: str,
        user_id: Optional[int] = None,
        recipe_id: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> ConversationSession:
        """새 대화 세션을 시작합니다."""
        session = ConversationSession(
            session_id=session_id,
            user_id=user_id,
            recipe_id=recipe_id,
            started_at=datetime.now().isoformat(),
            system_prompt=system_prompt,
            entries=[],
        )
        self._active_sessions[session_id] = session
        
        # 시스템 프롬프트를 첫 번째 엔트리로 추가
        if system_prompt:
            self.log_entry(
                session_id=session_id,
                role="system",
                content=system_prompt,
            )
        
        print(f"📝 [ConversationLogger] 세션 시작: {session_id}")
        return session
    
    def log_entry(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """대화 항목을 로그에 추가합니다."""
        session = self._active_sessions.get(session_id)
        if not session:
            print(f"⚠️ [ConversationLogger] 세션 없음: {session_id}")
            return False
        
        entry = ConversationEntry(
            timestamp=datetime.now().isoformat(),
            role=role,
            content=content,
            metadata=metadata,
        )
        session.entries.append(entry)
        
        # 실시간으로 파일에 추가 저장 (incremental)
        self._save_session(session_id)
        
        print(f"📝 [{role}] {content[:50]}..." if len(content) > 50 else f"📝 [{role}] {content}")
        return True
    
    def log_user_speech(
        self,
        session_id: str,
        transcript: str,
        audio_duration_ms: Optional[int] = None,
    ) -> bool:
        """사용자 음성 인식 결과를 로그에 추가합니다."""
        metadata = {}
        if audio_duration_ms is not None:
            metadata["audio_duration_ms"] = audio_duration_ms
        
        return self.log_entry(
            session_id=session_id,
            role="user",
            content=transcript,
            metadata=metadata if metadata else None,
        )
    
    def log_assistant_response(
        self,
        session_id: str,
        text: str,
        is_final: bool = True,
        token_count: Optional[int] = None,
    ) -> bool:
        """어시스턴트 응답을 로그에 추가합니다."""
        metadata = {"is_final": is_final}
        if token_count is not None:
            metadata["token_count"] = token_count
        
        return self.log_entry(
            session_id=session_id,
            role="assistant",
            content=text,
            metadata=metadata,
        )
    
    def log_tool_call(
        self,
        session_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        call_id: str,
    ) -> bool:
        """도구 호출을 로그에 추가합니다."""
        return self.log_entry(
            session_id=session_id,
            role="tool_call",
            content=json.dumps({"tool": tool_name, "arguments": arguments}, ensure_ascii=False),
            metadata={"call_id": call_id},
        )
    
    def log_tool_result(
        self,
        session_id: str,
        tool_name: str,
        result: Any,
        call_id: str,
    ) -> bool:
        """도구 호출 결과를 로그에 추가합니다."""
        result_str = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
        return self.log_entry(
            session_id=session_id,
            role="tool_result",
            content=result_str,
            metadata={"call_id": call_id, "tool": tool_name},
        )
    
    def set_token_usage(
        self,
        session_id: str,
        token_usage: Dict[str, Any],
    ) -> bool:
        """토큰 사용량을 설정합니다."""
        session = self._active_sessions.get(session_id)
        if not session:
            return False
        
        session.token_usage = token_usage
        self._save_session(session_id)
        
        print(f"💰 [ConversationLogger] 토큰 사용량: {token_usage}")
        return True
    
    def end_session(self, session_id: str) -> Optional[str]:
        """세션을 종료하고 파일 경로를 반환합니다."""
        session = self._active_sessions.get(session_id)
        if not session:
            return None
        
        session.ended_at = datetime.now().isoformat()
        filepath = self._save_session(session_id, final=True)
        
        # 메모리에서 제거
        del self._active_sessions[session_id]
        
        print(f"📝 [ConversationLogger] 세션 종료: {session_id} -> {filepath}")
        return filepath
    
    def get_session(self, session_id: str) -> Optional[ConversationSession]:
        """활성 세션을 가져옵니다."""
        return self._active_sessions.get(session_id)
    
    def _save_session(self, session_id: str, final: bool = False) -> str:
        """세션을 파일로 저장합니다."""
        session = self._active_sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        
        # 파일명 생성: YYYYMMDD_HHMMSS_sessionid.json
        date_str = datetime.fromisoformat(session.started_at).strftime("%Y%m%d_%H%M%S")
        filename = f"{date_str}_{session_id}.json"
        filepath = LOG_DIR / filename
        
        # JSON으로 저장
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(session.model_dump(), f, ensure_ascii=False, indent=2)
        
        return str(filepath)
    
    def list_sessions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """저장된 세션 목록을 반환합니다."""
        files = sorted(LOG_DIR.glob("*.json"), reverse=True)[:limit]
        sessions = []
        for file in files:
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    sessions.append({
                        "filename": file.name,
                        "session_id": data.get("session_id"),
                        "started_at": data.get("started_at"),
                        "ended_at": data.get("ended_at"),
                        "user_id": data.get("user_id"),
                        "recipe_id": data.get("recipe_id"),
                        "entry_count": len(data.get("entries", [])),
                        "token_usage": data.get("token_usage"),
                    })
            except Exception as e:
                print(f"⚠️ [ConversationLogger] 파일 읽기 실패: {file} - {e}")
        return sessions
    
    def get_session_log(self, filename: str) -> Optional[Dict[str, Any]]:
        """저장된 세션 로그를 읽어 반환합니다."""
        filepath = LOG_DIR / filename
        if not filepath.exists():
            return None
        
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)


# 싱글톤 인스턴스
_logger_instance: Optional[ConversationLogger] = None


def get_conversation_logger() -> ConversationLogger:
    """ConversationLogger 싱글톤 인스턴스를 반환합니다."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = ConversationLogger()
    return _logger_instance
