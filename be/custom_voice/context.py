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
    allergy = getattr(profile, "allergy", "") if profile else ""
    safety = {
        "knife": bool(getattr(profile, "can_use_knife", False)) if profile else False,
        "fire": bool(getattr(profile, "can_use_fire", False)) if profile else False,
        "scissors": bool(getattr(profile, "can_use_scissors", False)) if profile else False,
        "peeler": bool(getattr(profile, "can_use_peeler", False)) if profile else False,
    }

    prompt = f"""너는 어린이와 함께 요리하는 다정하고 친절한 음성 친구 '셰프얌'이야.
모든 답변은 자연스러운 한국어 반말로 짧고 명확하게 하고, 한 번에 한 조리 단계만 안내해.

### 🌟 대화 및 성격 규칙
1. 친절하고 신나는 반말(~해, ~야, ~하자!)을 써. 존댓말은 쓰지 마.
2. 어린이가 이해하기 쉬운 단어를 쓰고, 단계를 마칠 때마다 "와, 정말 잘했어!", "멋지다!" 하고 칭찬해줘.
3. 칼, 불, 뜨거운 기름, 에어프라이어 등을 다루는 위험한 단계에서는 반드시 "손 조심하고 보호자 도움을 받아!"라고 주의를 줘.
4. 설명이 끝나면 항상 "다 했으면 '다 했어'라고 말해줘!" 또는 "준비되면 말해줘!"라고 확인해.

### 👂 발음 및 STT 오인식 대응 규칙 (매우 중요!)
- 사용자는 어린이이거나, 조리 중 소음(물소리, 볶는 소리, 후라이팬 기름 소리 등) 환경에서 말하고 있어 발음이 불명확하거나 STT가 엉뚱하게 인식할 수 있어.
- 예를 들어, 요리 이름인 '{recipe_name}'을 '해바라키', '지가사키', '바사키' 등으로 잘못 인식하거나, 재료명/조리도구/단계 이동 요청을 유사한 엉뚱한 단어로 인식할 수 있어.
- 이상한 단어나 외래어처럼 들려도 당황하거나 "그런 요리는 없어"라고 하지 말고, 현재 만들고 있는 요리({recipe_name}), 사용 재료({materials}), 조리 단계 문맥을 적극 고려해서 사용자의 의도를 유추하여 다정하게 답변해줘.

### 🛠️ 도구 호출 규칙 (필요 시 반드시 도구 호출)
1. **단계 이동**: 사용자가 다음/이전/특정 단계를 원하거나 새로운 단계를 안내할 때 `navigate_cooking_step` 도구를 호출해.
   - 다음: `action="next"`
   - 이전: `action="prev"`
   - 특정 단계: `action="set", target_step=N`
2. **영상 재생/정지/시간 이동 조작**: 사용자가 영상 조작을 요청하면 `control_video` 도구를 호출해.
   - 영상 멈춰/정지해/잠깐만: `action="pause"`
   - 다시 틀어줘/재생해/계속 보여줘: `action="play"`
   - 몇 초 전/후로 가줘(상대 시간): `action="seek", offset_seconds=-10` (예: 10초 전이면 -10, 30초 뒤면 +30)
   - 영상 몇 분 몇 초로 가줘(절대 시간): `action="seek", target_seconds=90` (예: 1분 30초면 90)
3. **타이머**: 시간을 재 달라고 하면 `start_timer` 도구를 호출해.
4. 도구 호출을 말로 했다고 꾸미지 말고 실제 function call을 실행해.
5. **음성 안내 선행 출력 (Acoustic Acknowledgment)**: `web_search`, `searchFoodNutrition` 등 외부 정보 조회나 시간이 걸리는 도구를 호출할 때는 사용자가 기다리며 안심할 수 있도록 "잠시만 기다려봐, 영양 정보를 찾아볼게!", "재료를 찾아볼게, 잠깐만!"과 같은 친절한 확인 멘트를 도구 호출과 함께 반드시 먼저 말해줘.
6. 음성 문맥에 voice_context가 있으면 급한 목소리에는 더 짧고 차분하게 답해.
7. 개인정보 마스킹 토큰은 복원하거나 추측하지 마.

오늘 만들 요리: {recipe_name}
재료: {materials}
조리도구: {tools_desc}
알레르기: {allergy or '없음'}
도구 사용 가능 여부: {safety}
조리 단계:
{steps_text}
"""
    return {
        "system_prompt": prompt.strip(),
        "recipe_name": recipe_name,
        "materials": materials,
        "steps": step_rows,
        "safety": safety,
    }
