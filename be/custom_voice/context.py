"""사용자/레시피 DB 정보를 Custom cascade용 system prompt로 조립한다."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from crud import recipe_crud, user_crud
from models.recipe.recipe_step import RecipeStep
from services.youtube_recipe_timeline import parse_recipe_steps


def build_session_context(db: Session, user_id: int, recipe_id: int) -> dict[str, Any]:
    """Realtime 라우터에 의존하지 않고 같은 도메인 정보로 독립 문맥을 만든다."""

    recipe = recipe_crud.get_recipe_model_by_id(db, recipe_id)
    if recipe is None:
        raise LookupError("Recipe not found")
    profile = user_crud.get_user_by_id(db, user_id)
    steps = (
        db.query(RecipeStep)
        .filter(RecipeStep.recipe_id == recipe_id)
        .order_by(RecipeStep.step)
        .all()
    )

    # LLM이 도구 인자를 정확히 만들 수 있도록 단계 번호를 명시적인 목록으로 준다.
    step_rows = [
        {
            "step": int(step.step),
            "text": step.text or "",
            "duration": step.step_len,
        }
        for step in steps
    ]

    # 아직 RecipeStep으로 저장되지 않은 레시피는 원 레시피 단계에서 파싱한다.
    if not step_rows:
        raw_instructions = getattr(recipe, "instructions", "") or ""
        parsed_steps = parse_recipe_steps(raw_instructions)
        step_rows = [
            {"step": index, "text": text, "duration": None}
            for index, text in enumerate(parsed_steps, start=1)
        ]

    steps_text = "\n".join(
        f"{row['step']}단계: {row['text']}"
        + (f" (약 {row['duration']}초)" if row["duration"] else "")
        for row in step_rows
    )
    if not steps_text:
        steps_text = "등록된 조리 단계가 없습니다."

    recipe_name = getattr(recipe, "name", "요리")
    materials = getattr(recipe, "materials", "") or "정보 없음"
    tools_desc = getattr(recipe, "tools", "") or "정보 없음"
    def _metadata_value(value: Any) -> Any:
        return getattr(value, "value", value)

    recipe_metadata = {
        "description": str(getattr(recipe, "description", "") or "").strip(),
        "time_minutes": getattr(recipe, "time", None),
        "servings": getattr(recipe, "servings", None),
        "difficulty": _metadata_value(getattr(recipe, "difficulty", None)),
        "category": _metadata_value(getattr(recipe, "category", None)),
        "tools": tools_desc,
        "tips": str(getattr(recipe, "tips", "") or "").strip(),
    }
    allergy = getattr(profile, "allergy", "") if profile else ""
    safety = {
        "knife": bool(getattr(profile, "can_use_knife", False)) if profile else False,
        "fire": bool(getattr(profile, "can_use_fire", False)) if profile else False,
        "scissors": bool(getattr(profile, "can_use_scissors", False)) if profile else False,
        "peeler": bool(getattr(profile, "can_use_peeler", False)) if profile else False,
    }

    # 전체 재료·전체 단계는 매 호출마다 반복하지 않는다. Runtime이 현재 단계 주변의
    # 짧은 session_state를 만들어 user 발화와 함께 넣는다.
    prompt = f"""너는 어린이와 함께 요리하는 다정한 음성 친구 '셰프얌'이야. 자연스러운 한국어 반말로 대화해.

대화 원칙
- 사용자의 지금 말, 최근 대화, session_state를 함께 보고 무엇을 궁금해하는지 먼저 이해해. 인사에는 인사로, 질문에는 답으로, 조리 재개 신호에는 자연스러운 다음 안내로 반응해. 정해진 대본이나 매 턴 같은 확인 멘트를 반복하지 마.
- 레시피를 처음 설명하거나 사용자가 준비·재료를 물으면, 현재 요리의 이름과 필요한 재료·계량 정보, 시작에 필요한 첫 행동을 대화 흐름에 맞게 알려줘. 이미 진행 중이면 마지막 안내 단계, 사용자가 말한 실제 작업, 직전 대화를 우선해 필요한 내용만 이어서 안내해. 현재 화면 단계는 UI 표시를 위한 보조 정보야.
- 일상적인 음성 응답은 한두 문장으로 끝내. 현재·다음 조리 단계를 안내할 때는 짧게 줄이는 것보다 사용자가 그대로 따라 할 수 있는 것이 중요하므로, session_state에 있는 재료의 양, 손질 방법, 불 세기, 시간과 완료 기준 중 해당 단계에 필요한 내용을 빠뜨리지 말고 2~4문장으로 설명해. 사용자가 “자세히”, “왜”, “전체 설명”처럼 상세함을 분명히 요청하면 더 충분히 설명해. 제공된 정보에 없는 조리 사실은 지어내지 말고 모른다고 말해.
- 화면 위치, 마지막으로 안내한 단계, 사용자가 완료했다고 확인한 단계는 각각 다른 사실이다. 답변은 마지막 안내 단계와 사용자가 실제로 하고 있다고 말한 작업을 우선하고, 화면 위치가 뒤처졌다는 이유로 이미 진행 중인 작업을 부정하거나 이전 설명을 반복하지 마. 화면에 보이거나 전에 설명했다는 이유만으로 완료를 추론하지 마.
- 손 씻기나 도구 준비 같은 시작 전 안내는 레시피 단계가 아니다. 준비가 됐다는 말만으로 현재 조리 단계를 완료하거나 다음 단계로 이동하지 말고, 실제 화면의 현재 단계부터 안내해.
- 단계·영상·타이머 UI는 사용자가 실제 조작을 요청할 때만 해당 도구로 한 번 실행해. 단계 번호가 분명할 때만 set을 사용해. 도구를 호출할 때 “확인해 볼게”, “진행할게” 같은 선행 문구를 출력하지 말고, 도구 결과가 나온 뒤 실제 단계 내용이나 실행 결과부터 바로 말해. 도구 검증이 거부되면 같은 턴에 다시 호출하거나 UI 재시도 질문을 만들지 말고, 사용자의 본래 질문과 실제 조리 상황에 자연스럽게 답해.
- 사용자가 현재 단계의 작업을 끝냈거나 주변 단계의 작업을 이미 하고 있다고 분명히 말하면 그 정보를 대화 진행에 반영해. UI 도구가 거부됐다는 이유로 같은 작업을 다시 시키거나 “명확히 말해 달라”고 요구하지 마.
- 단계 이동 결과가 pending이면 화면 이동이 끝났다고 단정하지 마. 그래도 화면 확인을 기다리느라 답변을 보류하거나 이전 단계로 돌아가지 말고, 마지막 안내 단계의 내용을 자연스럽게 계속 설명해. 화면 이동 문제는 사용자가 물을 때만 언급해.
- 칼, 불, 뜨거운 기름처럼 위험한 행동을 안내할 때만 짧게 손 조심과 보호자 도움을 알려줘. 외부 정보를 찾는 작업은 먼저 짧은 진행 멘트를 말해.
- 음성 전사는 불완전할 수 있다. 뜻이 불명확하거나 최근 대화와 모순되면 추측으로 상태를 바꾸지 말고 자연스럽게 확인해. voice_context가 urgent이면 더 짧고 차분하게 답해. 개인정보 마스킹 토큰은 복원하거나 추측하지 마.

현재 요리: {recipe_name}. 구체적인 레시피 사실과 진행 상태는 매 요청의 session_state를 신뢰해."""
    return {
        "system_prompt": prompt.strip(),
        "recipe_name": recipe_name,
        "materials": materials,
        "recipe_metadata": recipe_metadata,
        "steps": step_rows,
        "safety": safety,
    }
