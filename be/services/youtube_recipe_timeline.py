"""YouTube 자막을 LLM으로 요리 단계화하고 RecipeStep으로 저장한다."""

from __future__ import annotations

import ast
import json
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session

from models.recipe.recipe import Category, Difficulty, Recipe
from models.recipe.recipe_step import RecipeStep


VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
NOISE_TOKEN_PATTERN = re.compile(
    r"(?:\[(?:music|applause|laughter|음악|박수|웃음)\]|♪|♫)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TranscriptSegment:
    text: str
    start: float
    duration: float

    @property
    def end(self) -> float:
        return self.start + self.duration


class YouTubeRecipeDuplicateError(RuntimeError):
    """이미 등록된 YouTube 영상으로 새 레시피를 만들려 할 때의 도메인 오류다."""

    def __init__(self, recipe: Recipe) -> None:
        self.recipe_id = int(recipe.recipe_id)
        self.recipe_name = recipe.name
        super().__init__(f"이미 등록된 YouTube 영상입니다: {recipe.name}")


@dataclass(frozen=True)
class TimelineGenerationPolicy:
    """영상 길이와 생성 단계 수를 제어하는 검증 정책이다.

    기본값은 짧은 Shorts와 한 단계 요리도 허용한다. 운영 환경에서 최소값을 높이고
    싶으면 환경 변수로 조정하며, 신규 등록 API에서는 요청별 값이 우선한다.
    """

    min_duration_seconds: int = 0
    min_transcript_segments: int = 1
    min_steps: int = 1
    max_steps: int = 24


@dataclass(frozen=True)
class GeneratedYouTubeRecipe:
    """외부 영상 검증과 LLM 생성이 끝났지만 아직 DB에 저장되지 않은 레시피 초안이다."""

    video_id: str
    video_url: str
    name: str
    description: str
    materials: str
    tools: str
    tips: str
    time_minutes: int
    timeline: list[dict[str, Any]]


def _read_policy_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """잘못된 환경 변수가 서버 기동을 막지 않도록 범위 안의 정수만 읽는다."""

    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


def resolve_timeline_policy(
    *,
    min_duration_seconds: int | None = None,
    min_steps: int | None = None,
    max_steps: int | None = None,
) -> TimelineGenerationPolicy:
    """환경 기본값에 요청별 제어값을 적용해 유효한 타임라인 생성 정책을 만든다."""

    duration = (
        min_duration_seconds
        if min_duration_seconds is not None
        else _read_policy_int("YOUTUBE_RECIPE_MIN_DURATION_SECONDS", 0, 0, 86_400)
    )
    minimum = (
        min_steps
        if min_steps is not None
        else _read_policy_int("YOUTUBE_RECIPE_MIN_STEPS", 1, 1, 60)
    )
    maximum = (
        max_steps
        if max_steps is not None
        else _read_policy_int("YOUTUBE_RECIPE_MAX_STEPS", 24, 1, 60)
    )
    segment_minimum = _read_policy_int("YOUTUBE_RECIPE_MIN_TRANSCRIPT_SEGMENTS", 1, 1, 10_000)
    if duration < 0 or minimum < 1 or maximum < 1 or minimum > maximum:
        raise ValueError("최소 단계 수는 최대 단계 수보다 클 수 없으며 모든 값은 유효한 범위여야 합니다.")
    return TimelineGenerationPolicy(
        min_duration_seconds=duration,
        min_transcript_segments=segment_minimum,
        min_steps=minimum,
        max_steps=maximum,
    )


def canonical_youtube_url(video_id: str) -> str:
    """검증된 video ID를 중복 비교와 저장에 쓸 단일 YouTube URL로 정규화한다."""

    return f"https://www.youtube.com/watch?v={video_id}"


def extract_video_id(url: str | None) -> str | None:
    """watch/embed/shorts/youtu.be 형태에서 11자리 YouTube ID를 추출한다."""
    if not url:
        return None
    candidate = url.strip()
    if VIDEO_ID_PATTERN.fullmatch(candidate):
        return candidate
    try:
        parsed = urlparse(candidate)
        host = parsed.netloc.lower().split(":")[0]
        if host in {"youtu.be", "www.youtu.be"}:
            video_id = parsed.path.strip("/").split("/")[0]
        elif host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
            parts = [part for part in parsed.path.split("/") if part]
            if parts and parts[0] in {"embed", "shorts", "live"} and len(parts) > 1:
                video_id = parts[1]
            else:
                video_id = parse_qs(parsed.query).get("v", [""])[0]
        else:
            return None
        return video_id if VIDEO_ID_PATTERN.fullmatch(video_id) else None
    except (TypeError, ValueError):
        return None


def parse_recipe_steps(raw: str | None) -> list[str]:
    """CSV에 Python literal 형태로 저장된 원 레시피 단계를 안전하게 읽는다."""
    if not raw:
        return []
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return [raw.strip()] if raw.strip() else []
    if not isinstance(parsed, list):
        return []
    result = []
    for item in parsed:
        text = item.get("text") if isinstance(item, dict) else str(item)
        if text and text.strip():
            result.append(text.strip())
    return result


def fetch_transcript(video_id: str) -> list[TranscriptSegment]:
    """한국어를 우선하고, 없으면 번역 가능한 자막/첫 자막을 사용한다."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise RuntimeError(
            "youtube-transcript-api가 설치되지 않았습니다. pip install -r requirements.txt를 실행하세요."
        ) from exc

    api = YouTubeTranscriptApi()
    try:
        fetched = api.fetch(video_id, languages=["ko", "ko-KR", "en"])
    except Exception as primary_error:
        try:
            transcript_list = api.list(video_id)
            transcript = None
            for candidate in transcript_list:
                if candidate.language_code.startswith("ko"):
                    transcript = candidate
                    break
            if transcript is None:
                transcript = next(iter(transcript_list))
                if getattr(transcript, "is_translatable", False):
                    transcript = transcript.translate("ko")
            fetched = transcript.fetch()
        except Exception as fallback_error:
            raise RuntimeError(
                f"YouTube 자막을 가져올 수 없습니다 ({video_id}): {fallback_error}"
            ) from primary_error

    segments = []
    for snippet in fetched:
        if isinstance(snippet, dict):
            text = snippet.get("text", "")
            start = snippet.get("start", 0)
            duration = snippet.get("duration", 0)
        else:
            text = getattr(snippet, "text", "")
            start = getattr(snippet, "start", 0)
            duration = getattr(snippet, "duration", 0)
        clean_text = re.sub(r"\s+", " ", str(text)).strip()
        meaningful_text = NOISE_TOKEN_PATTERN.sub("", clean_text).strip(" -")
        if len(re.sub(r"[^0-9A-Za-z가-힣]", "", meaningful_text)) >= 2:
            segments.append(
                TranscriptSegment(meaningful_text, float(start), float(duration))
            )
    if not segments:
        raise RuntimeError(f"사용할 수 있는 자막이 없습니다 ({video_id})")
    return segments


def _compact_segments(segments: list[TranscriptSegment], max_segments: int = 650) -> list[TranscriptSegment]:
    """긴 자동자막은 인접 항목을 묶어 LLM 입력 크기를 제한한다."""
    if len(segments) <= max_segments:
        return segments
    group_size = math.ceil(len(segments) / max_segments)
    compacted = []
    for index in range(0, len(segments), group_size):
        group = segments[index:index + group_size]
        compacted.append(
            TranscriptSegment(
                text=" ".join(item.text for item in group),
                start=group[0].start,
                duration=max(0.1, group[-1].end - group[0].start),
            )
        )
    return compacted


def _validate_transcript(segments: list[TranscriptSegment], policy: TimelineGenerationPolicy) -> None:
    """LLM 호출 전 자막이 요청 정책에 맞는 최소한의 조리 근거를 갖췄는지 확인한다."""

    if len(segments) < policy.min_transcript_segments:
        raise RuntimeError(
            f"레시피 생성에 필요한 자막이 부족합니다. "
            f"최소 {policy.min_transcript_segments}개 구간이 필요합니다."
        )
    duration = max((segment.end for segment in segments), default=0.0)
    if duration < policy.min_duration_seconds:
        raise RuntimeError(
            f"영상 자막 길이가 너무 짧습니다 ({duration:.1f}초). "
            f"현재 최소 길이 설정은 {policy.min_duration_seconds}초입니다."
        )


def _validate_timeline(timeline: list[dict[str, Any]], policy: TimelineGenerationPolicy) -> None:
    """LLM 결과가 요청한 단계 수와 시간 순서 조건을 충족하는지 DB 저장 전에 검증한다."""

    if not policy.min_steps <= len(timeline) <= policy.max_steps:
        raise RuntimeError(
            f"생성된 조리 단계가 {len(timeline)}개입니다. "
            f"현재 허용 범위는 {policy.min_steps}~{policy.max_steps}개입니다."
        )
    previous_start = -1
    for step in timeline:
        text = str(step.get("text") or "").strip()
        start = int(step.get("start_seconds") or 0)
        if not text or start < previous_start:
            raise RuntimeError("생성된 레시피 단계의 내용 또는 시간 순서가 올바르지 않습니다.")
        previous_start = start


def split_transcript_with_llm(
    *,
    title: str,
    difficulty: str | None,
    original_steps: list[str],
    segments: list[TranscriptSegment],
    model: str | None = None,
    min_steps: int = 1,
    max_steps: int = 24,
    metadata_out: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """LLM이 단계 설명과 각 단계의 첫 자막 인덱스를 고르게 한다."""
    from openai import OpenAI

    compacted = _compact_segments(segments)
    transcript_text = "\n".join(
        f"[{index}] {segment.start:.2f}s {segment.text}"
        for index, segment in enumerate(compacted)
    )
    reference = "\n".join(
        f"- {step}" for step in original_steps
    ) or "(원문 단계 없음)"

    schema = {
        "name": "recipe_timeline",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "recipe_name": {"type": "string"},
                "description": {"type": "string"},
                "materials": {"type": "array", "items": {"type": "string"}},
                "tools": {"type": "array", "items": {"type": "string"}},
                "tips": {"type": "string"},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "start_segment": {"type": "integer"},
                        },
                        "required": ["text", "start_segment"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["recipe_name", "description", "materials", "tools", "tips", "steps"],
            "additionalProperties": False,
        },
    }
    prompt = f"""너는 아동(어린이)을 위한 요리 교육 타임라인 편집 전문가야.
어린이가 음성 AI의 안내를 들으며 혼자서도 안전하고 쉽게 따라 할 수 있도록 요리 영상 자막을 세분화된 단계별 레시피로 만들어줘.

요리명: {title}
난이도: {difficulty or '초급'}
생성 단계 수: 반드시 {min_steps}개 이상 {max_steps}개 이하

레시피 기본 정보도 함께 만들어줘.
- recipe_name: 영상의 실제 요리 이름을 짧고 구체적인 한국어로 작성해.
- description: 어린이와 보호자가 이해할 한두 문장 요약을 작성해.
- materials: 영상에서 확인 가능한 주요 재료를 배열로 작성해. 확인할 수 없으면 빈 배열.
- tools: 영상에서 확인 가능한 주요 조리도구를 배열로 작성해. 확인할 수 없으면 빈 배열.
- tips: 안전 또는 조리 팁을 짧게 작성해. 없으면 빈 문자열.

### 단계 분할 핵심 원칙 (필수 준수):
1. **단일 물리적 행위 단위(Single Action Unit) 분할**:
   - 한 단계에는 어린이가 한 번에 집중해서 수행할 수 있는 '하나의 독립된 동작/작업'만 담아야 해.
   - 여러 개의 연속된 서로 다른 작업을 하나의 단계로 묶지 말고, 동작이 전환될 때마다 반드시 별도의 단계로 분할해.

2. **단계 분할 기준 (동작 전환 시점)**:
   - 다루는 조리 도구가 변경될 때
   - 작업을 진행하는 용기나 조리 위치(공간)가 변경될 때
   - 새로운 재료가 투입되거나, 대상 재료에 가하는 물리적 동작의 목적이 바뀔 때
   - 이전 작업이 완료되고 다음 새로운 작업 단위로 넘어갈 때

3. **전 과정의 완전성 (시작부터 최종 완성까지)**:
   - 최초 준비 과정부터 재료 손질, 조리, 마지막 마무리 및 그릇/접시에 담아 완성하는 전 과정이 빠짐없이 포함되어야 해.
   - 영상 후반부나 마지막 완성 단계를 임의로 생략하거나 축약하지 말고 끝까지 모든 조리 행위를 순서대로 분할해.
   - (단순 채널 홍보, 구독 요청, 인사 등 조리와 무관한 내용만 제외)

4. **어린이 눈높이에 맞춘 쉽고 명확한 설명**:
   - 전문 용어, 외국어 조리 용어 대신 어린이가 직관적으로 이해할 수 있는 쉬운 한국어로 설명해.
   - 각 단계 설명은 어린이가 무엇을 어떻게 해야 하는지 명확하고 친절한 문장으로 작성해.

5. **타임스탬프 순서**:
   - start_segment는 해당 조리 동작이 실제로 시작되는 자막 번호이며, 반드시 오름차순이어야 해.

원 레시피 단계(정확도 참고용):
{reference}

타임스탬프 자막:
{transcript_text}"""

    # 외부 LLM이 지연되거나 일시적으로 실패해도 요청이 무한정 대기하지 않도록 제한한다.
    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        timeout=float(os.getenv("RECIPE_TIMELINE_TIMEOUT_SECONDS", "30")),
        max_retries=int(os.getenv("RECIPE_TIMELINE_MAX_RETRIES", "1")),
    )
    response = client.chat.completions.create(
        model=model or os.getenv("RECIPE_TIMELINE_MODEL", "gpt-5-nano"),
        messages=[
            {"role": "system", "content": "너는 아동 요리 교육 전문 타임라인 에디터다."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_schema", "json_schema": schema},
    )
    content = response.choices[0].message.content
    data = json.loads(content or "{}")
    if metadata_out is not None:
        metadata_out.update(
            {
                "recipe_name": str(data.get("recipe_name") or "").strip(),
                "description": str(data.get("description") or "").strip(),
                "materials": _clean_text_list(data.get("materials")),
                "tools": _clean_text_list(data.get("tools")),
                "tips": str(data.get("tips") or "").strip(),
            }
        )
    raw_steps = data.get("steps", [])
    if not raw_steps:
        raise RuntimeError("LLM이 유효한 레시피 단계를 반환하지 않았습니다.")

    normalized = []
    previous_index = -1
    for item in raw_steps:
        index = max(0, min(int(item["start_segment"]), len(compacted) - 1))
        if index <= previous_index:
            continue
        text = str(item["text"]).strip()
        if not text:
            continue
        normalized.append({"text": text, "start_segment": index})
        previous_index = index
    if not normalized:
        raise RuntimeError("LLM 단계의 시작 시간이 올바르지 않습니다.")

    result = []
    for index, item in enumerate(normalized):
        start_segment = compacted[item["start_segment"]]
        start = int(start_segment.start)
        if index + 1 < len(normalized):
            next_segment = compacted[normalized[index + 1]["start_segment"]]
            end = max(start + 1, int(math.ceil(next_segment.start)))
        else:
            end = max(start + 1, int(math.ceil(compacted[-1].end)))
        result.append({"text": item["text"], "start_seconds": start, "step_len": end - start})
    return result


def save_timeline(
    db: Session,
    recipe: Recipe,
    video_id: str,
    timeline: Iterable[dict[str, Any]],
    *,
    commit: bool = True,
) -> list[RecipeStep]:
    """검증된 timeline을 저장한다. 신규 등록은 recipe와 같은 transaction으로 commit한다."""

    db.query(RecipeStep).filter(RecipeStep.recipe_id == recipe.recipe_id).delete(
        synchronize_session=False
    )
    saved = []
    for step_number, item in enumerate(timeline, start=1):
        start = max(0, int(item["start_seconds"]))
        start_url = f"https://youtu.be/{video_id}?t={start}"
        entity = RecipeStep(
            recipe_id=recipe.recipe_id,
            step=step_number,
            text=str(item["text"]).strip(),
            url=start_url,
            video_id=video_id,
            start_url=start_url,
            start_seconds=start,
            step_len=max(1, int(item["step_len"])),
        )
        db.add(entity)
        saved.append(entity)
    if commit:
        db.commit()
    else:
        db.flush()
    for entity in saved:
        db.refresh(entity)
    return saved


def process_recipe_timeline(
    db: Session,
    recipe: Recipe,
    model: str | None = None,
    *,
    policy: TimelineGenerationPolicy | None = None,
) -> list[RecipeStep]:
    """기존 DB 레시피의 영상을 정책 검증 뒤 단계별 타임라인으로 다시 생성한다."""

    video_id = extract_video_id(recipe.video_url)
    if not video_id:
        raise ValueError("이 레시피에는 유효한 YouTube video_url이 없습니다.")
    transcript = fetch_transcript(video_id)
    resolved_policy = policy or resolve_timeline_policy()
    _validate_transcript(transcript, resolved_policy)
    timeline = split_transcript_with_llm(
        title=recipe.name,
        difficulty=getattr(recipe.difficulty, "value", recipe.difficulty),
        original_steps=parse_recipe_steps(recipe.instructions),
        segments=transcript,
        model=model,
        min_steps=resolved_policy.min_steps,
        max_steps=resolved_policy.max_steps,
    )
    _validate_timeline(timeline, resolved_policy)
    return save_timeline(db, recipe, video_id, timeline)


def find_recipe_by_video_id(db: Session, video_id: str) -> Recipe | None:
    """DB에 저장된 URL을 실제 video ID로 재검증해 같은 YouTube 영상의 중복을 찾는다."""

    candidates = (
        db.query(Recipe)
        .filter(Recipe.video_url.isnot(None), Recipe.video_url.like(f"%{video_id}%"))
        .all()
    )
    return next((recipe for recipe in candidates if extract_video_id(recipe.video_url) == video_id), None)


def _clean_text_list(value: Any) -> list[str]:
    """LLM의 문자열 배열에서 빈 값과 중복을 제거해 DB TEXT 컬럼용 목록으로 만든다."""

    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _unique_recipe_name(db: Session, name: str, video_id: str) -> str:
    """Recipe.name의 unique 제약과 충돌하면 video ID suffix를 붙여 새 이름을 만든다."""

    candidate = re.sub(r"\s+", " ", name).strip()[:100] or f"YouTube 요리 {video_id}"
    if db.query(Recipe).filter(Recipe.name == candidate).first() is None:
        return candidate
    suffix = f" ({video_id[:6]})"
    return f"{candidate[: 100 - len(suffix)]}{suffix}"


def generate_youtube_recipe_draft(
    *,
    video_id: str,
    requested_name: str | None = None,
    difficulty: str | None = None,
    model: str | None = None,
    policy: TimelineGenerationPolicy | None = None,
) -> GeneratedYouTubeRecipe:
    """자막과 LLM 결과를 모두 검증해 DB 저장 전의 완성된 레시피 초안을 만든다."""

    resolved_policy = policy or resolve_timeline_policy()
    transcript = fetch_transcript(video_id)
    _validate_transcript(transcript, resolved_policy)
    metadata: dict[str, Any] = {}
    timeline = split_transcript_with_llm(
        title=(requested_name or "영상 속 요리").strip(),
        difficulty=difficulty,
        original_steps=[],
        segments=transcript,
        model=model,
        min_steps=resolved_policy.min_steps,
        max_steps=resolved_policy.max_steps,
        metadata_out=metadata,
    )
    _validate_timeline(timeline, resolved_policy)
    generated_name = (requested_name or metadata.get("recipe_name") or f"YouTube 요리 {video_id}").strip()
    total_seconds = max((int(step["start_seconds"]) + int(step["step_len"]) for step in timeline), default=0)
    return GeneratedYouTubeRecipe(
        video_id=video_id,
        video_url=canonical_youtube_url(video_id),
        name=generated_name,
        description=str(metadata.get("description") or ""),
        materials=", ".join(_clean_text_list(metadata.get("materials"))),
        tools=", ".join(_clean_text_list(metadata.get("tools"))),
        tips=str(metadata.get("tips") or ""),
        time_minutes=max(1, math.ceil(total_seconds / 60)),
        timeline=timeline,
    )


def import_youtube_recipe(
    db: Session,
    *,
    video_url: str,
    requested_name: str | None = None,
    difficulty: str | None = None,
    model: str | None = None,
    policy: TimelineGenerationPolicy | None = None,
) -> Recipe:
    """중복·자막·LLM 단계 검증을 모두 마친 뒤에만 새 Recipe와 RecipeStep을 저장한다."""

    video_id = extract_video_id(video_url)
    if not video_id:
        raise ValueError("유효한 YouTube 링크를 입력해 주세요.")
    duplicate = find_recipe_by_video_id(db, video_id)
    if duplicate is not None:
        raise YouTubeRecipeDuplicateError(duplicate)

    # 이 시점까지 DB에 Recipe를 추가하지 않는다. 자막/LLM 검증 실패에는 DB 변경이 없다.
    draft = generate_youtube_recipe_draft(
        video_id=video_id,
        requested_name=requested_name,
        difficulty=difficulty,
        model=model,
        policy=policy,
    )
    duplicate = find_recipe_by_video_id(db, video_id)
    if duplicate is not None:
        raise YouTubeRecipeDuplicateError(duplicate)

    difficulty_value = next(
        (item for item in Difficulty if item.value == difficulty),
        Difficulty.EASY,
    )
    recipe = Recipe(
        name=_unique_recipe_name(db, draft.name, draft.video_id),
        description=draft.description,
        image_url=f"https://i.ytimg.com/vi/{draft.video_id}/hqdefault.jpg",
        time=draft.time_minutes,
        servings=1,
        difficulty=difficulty_value,
        instructions=json.dumps([item["text"] for item in draft.timeline], ensure_ascii=False),
        category=Category.OTHER,
        tools=draft.tools,
        materials=draft.materials,
        tips=draft.tips,
        video_url=draft.video_url,
    )
    try:
        db.add(recipe)
        db.flush()
        save_timeline(db, recipe, draft.video_id, draft.timeline, commit=False)
        db.commit()
        db.refresh(recipe)
        return recipe
    except Exception:
        db.rollback()
        raise


def main() -> int:
    """`python -m services.youtube_recipe_timeline` 일괄 처리 진입점."""
    import argparse

    parser = argparse.ArgumentParser(
        description="YouTube 레시피의 자막 타임라인을 생성해 DB에 저장합니다."
    )
    parser.add_argument("--recipe-id", type=int, help="한 레시피만 처리")
    parser.add_argument("--limit", type=int, help="이번 실행에서 처리할 최대 개수")
    parser.add_argument("--model", help="RECIPE_TIMELINE_MODEL 대신 사용할 모델")
    parser.add_argument("--force", action="store_true", help="기존 타임라인도 다시 생성")
    args = parser.parse_args()

    from db.init_db import init_db
    from db.seed import seed
    from db.session import SessionLocal

    init_db()
    seed()
    db = SessionLocal()
    succeeded = 0
    failed = 0
    try:
        query = db.query(Recipe).filter(Recipe.video_url.isnot(None))
        if args.recipe_id:
            query = query.filter(Recipe.recipe_id == args.recipe_id)
        recipes = query.order_by(Recipe.recipe_id).all()
        if args.limit:
            recipes = recipes[:args.limit]

        for recipe in recipes:
            ready = (
                db.query(RecipeStep)
                .filter(
                    RecipeStep.recipe_id == recipe.recipe_id,
                    RecipeStep.step_len.isnot(None),
                )
                .first()
            )
            if ready and not args.force:
                print(f"SKIP {recipe.recipe_id}: {recipe.name}")
                continue
            try:
                steps = process_recipe_timeline(db, recipe, model=args.model)
                succeeded += 1
                print(f"OK   {recipe.recipe_id}: {recipe.name} ({len(steps)} steps)")
            except Exception as error:
                db.rollback()
                failed += 1
                print(f"FAIL {recipe.recipe_id}: {recipe.name} - {error}")
    finally:
        db.close()
    print(f"완료: 성공 {succeeded}, 실패 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
