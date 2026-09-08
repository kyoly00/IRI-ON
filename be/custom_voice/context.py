"""사용자/레시피 DB 정보를 Custom cascade용 system prompt로 조립한다."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from crud import recipe_crud, user_crud
from models.recipe.recipe_step import RecipeStep


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
    steps_text = "\n".join(
        f"{row['step']}단계: {row['text']}"
        + (f" (약 {row['duration']}초)" if row["duration"] else "")
        for row in step_rows
    )
    if not steps_text:
        steps_text = getattr(recipe, "instructions", "") or "등록된 조리 단계가 없습니다."

    allergy = getattr(profile, "allergy", "") if profile else ""
    safety = {
        "knife": bool(getattr(profile, "can_use_knife", False)) if profile else False,
        "fire": bool(getattr(profile, "can_use_fire", False)) if profile else False,
        "scissors": bool(getattr(profile, "can_use_scissors", False)) if profile else False,
        "peeler": bool(getattr(profile, "can_use_peeler", False)) if profile else False,
    }
    prompt = f"""너는 어린이와 함께 요리하는 친절한 음성 친구 '셰프얌'이야.
항상 자연스러운 한국어 반말로 짧게 답하고, 한 번에 한 조리 단계만 안내해.
칼, 불, 뜨거운 기름을 다루는 단계에서는 반드시 보호자 도움을 요청해.
사용자가 다음/이전/특정 단계 이동을 원하면 navigate_cooking_step 도구를 호출해.
시간을 재 달라고 하면 start_timer 도구를 호출해. 도구 호출을 말로 했다고 꾸미지 마.
음성 문맥에 voice_context가 있으면 급한 목소리에는 더 짧고 차분하게 답해.
개인정보 마스킹 토큰은 복원하거나 추측하지 마.

요리: {getattr(recipe, 'name', '요리')}
재료: {getattr(recipe, 'materials', '') or '정보 없음'}
조리도구: {getattr(recipe, 'tools', '') or '정보 없음'}
알레르기: {allergy or '없음'}
도구 사용 가능 여부: {safety}
조리 단계:
{steps_text}
"""
    return {
        "system_prompt": prompt.strip(),
        "recipe_name": getattr(recipe, "name", "요리"),
        "steps": step_rows,
        "safety": safety,
    }
