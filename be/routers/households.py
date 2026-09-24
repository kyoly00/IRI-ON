import base64
import io
import json
import os
import re
import secrets
import uuid
from decimal import Decimal
from urllib.parse import quote_plus

import filetype
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from openai import OpenAI
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from db.session import get_db
from models.domain.household import (
    FridgeItem, Household, HouseholdMember, HouseholdRole, PurchaseRequest,
    PurchaseRequestItem, RequestStatus,
)
from models.domain.ingredient import Ingredient
from models.recipe.recipe import Recipe
from models.recipe.recipe_ingredient import RecipeIngredient
from models.user.user_ingredient import UserIngredient
from models.user.user import User
from schemas.household_schema import (
    AvailabilitySchema, FridgeItemInputSchema, FridgeItemUpdateSchema,
    HouseholdCreateSchema, HouseholdJoinSchema, PurchaseRequestCreateSchema,
    PurchaseRequestStatusSchema,
)
from services.fridge_units import converted
from security import get_current_user

router = APIRouter(prefix="/households", tags=["households"])

def member_for(db: Session, household_id: int, user_id: int) -> HouseholdMember:
    """인증된 사용자가 해당 가정의 구성원일 때만 멤버십을 반환합니다."""
    member = db.query(HouseholdMember).filter_by(household_id=household_id, user_id=user_id).first()
    if not member:
        raise HTTPException(status_code=403, detail="이 가정의 구성원이 아닙니다.")
    return member


def current_membership(db: Session, user_id: int) -> HouseholdMember | None:
    return db.query(HouseholdMember).filter_by(user_id=user_id).first()


def item_dict(item: FridgeItem) -> dict:
    return {"fridge_item_id": item.fridge_item_id, "ingredient_id": item.ingredient_id,
            "name": item.ingredient.name, "quantity": float(item.quantity), "unit": item.unit,
            "source": item.source}


def get_or_create_ingredient(db: Session, data: FridgeItemInputSchema) -> Ingredient:
    if data.ingredient_id:
        ingredient = db.get(Ingredient, data.ingredient_id)
        if not ingredient:
            raise HTTPException(status_code=404, detail="재료를 찾을 수 없습니다.")
        return ingredient
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="ingredient_id 또는 name이 필요합니다.")
    ingredient = db.query(Ingredient).filter(Ingredient.name == name).first()
    if not ingredient:
        ingredient = Ingredient(name=name)
        db.add(ingredient)
        db.flush()
    return ingredient


def upsert_item(db: Session, household_id: int, data: FridgeItemInputSchema, source="manual") -> FridgeItem:
    """기존 단위와 새 단위가 호환될 때만 재고를 합산하거나 추가합니다."""
    ingredient = get_or_create_ingredient(db, data)
    item = db.query(FridgeItem).filter_by(household_id=household_id, ingredient_id=ingredient.ingredient_id).first()
    if item:
        added = converted(data.quantity, data.unit, item.unit)
        if added is None:
            raise HTTPException(status_code=422, detail=f"{ingredient.name}의 기존 단위({item.unit})와 합칠 수 없습니다.")
        item.quantity += added
    else:
        item = FridgeItem(household_id=household_id, ingredient_id=ingredient.ingredient_id,
                          quantity=data.quantity, unit=data.unit, source=source)
        db.add(item)
    db.flush()
    return item


def availability(db: Session, household_id: int, recipe_id: int, servings: int):
    """인분에 맞춰 레시피 필요량을 계산하고 해당 가정 재고만 비교합니다."""
    recipe = db.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="레시피를 찾을 수 없습니다.")
    scale = Decimal(servings) / Decimal(recipe.servings or 1)
    requirements = db.query(RecipeIngredient).options(joinedload(RecipeIngredient.ingredient)).filter_by(recipe_id=recipe_id).all()
    results = []
    for requirement in requirements:
        needed = (requirement.quantity or Decimal("1")) * scale
        unit = requirement.unit or "piece"
        stock = db.query(FridgeItem).options(joinedload(FridgeItem.ingredient)).filter_by(
            household_id=household_id, ingredient_id=requirement.ingredient_id).first()
        # 단위가 호환되지 않으면 부족으로 처리해 잘못된 '충분함' 판단을 막습니다.
        available = converted(stock.quantity, stock.unit, unit) if stock else Decimal("0")
        comparable = available is not None
        shortage = max(needed - available, Decimal("0")) if comparable else needed
        results.append({"ingredient_id": requirement.ingredient_id, "name": requirement.ingredient.name,
                        "needed_quantity": float(needed), "unit": unit,
                        "available_quantity": float(available) if comparable else 0,
                        "shortage_quantity": float(shortage), "is_shortage": shortage > 0,
                        "unit_compatible": comparable})
    return {"recipe_id": recipe_id, "recipe_name": recipe.name, "servings": servings,
            "base_servings": recipe.servings or 1, "items": results,
            "shortages": [item for item in results if item["is_shortage"]]}


@router.get("/me")
def get_my_household(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    member = current_membership(db, current_user.user_id)
    if not member:
        return {"household": None}
    household = db.get(Household, member.household_id)
    return {"household": {"household_id": household.household_id, "name": household.name,
            "invite_code": household.invite_code, "role": member.role.value}}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_household(payload: HouseholdCreateSchema, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user_id = current_user.user_id
    if current_membership(db, user_id):
        raise HTTPException(status_code=409, detail="이미 가정에 참여하고 있습니다.")
    household = Household(name=payload.name.strip(), invite_code=secrets.token_urlsafe(6).upper()[:8])
    db.add(household)
    db.flush()
    db.add(HouseholdMember(household_id=household.household_id, user_id=user_id, role=HouseholdRole.PARENT))
    # Legacy selections become a shared starter inventory.
    for old in db.query(UserIngredient).filter_by(user_id=user_id).all():
        db.add(FridgeItem(household_id=household.household_id, ingredient_id=old.ingredient_id,
                          quantity=old.quantity or 1, unit="piece", source="legacy"))
    db.commit()
    return {"household_id": household.household_id, "name": household.name, "invite_code": household.invite_code, "role": "parent"}


@router.post("/join")
def join_household(payload: HouseholdJoinSchema, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user_id = current_user.user_id
    if current_membership(db, user_id):
        raise HTTPException(status_code=409, detail="이미 가정에 참여하고 있습니다.")
    household = db.query(Household).filter(Household.invite_code == payload.invite_code.strip().upper()).first()
    if not household:
        raise HTTPException(status_code=404, detail="초대 코드를 찾을 수 없습니다.")
    db.add(HouseholdMember(household_id=household.household_id, user_id=user_id, role=HouseholdRole.CHILD))
    db.commit()
    return {"household_id": household.household_id, "name": household.name, "role": "child"}


@router.get("/{household_id}/fridge-items")
def get_fridge_items(household_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    member_for(db, household_id, current_user.user_id)
    items = db.query(FridgeItem).options(joinedload(FridgeItem.ingredient)).filter_by(household_id=household_id).order_by(FridgeItem.updated_at.desc()).all()
    return [item_dict(item) for item in items]


@router.post("/{household_id}/fridge-items", status_code=status.HTTP_201_CREATED)
def add_fridge_item(household_id: int, payload: FridgeItemInputSchema, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    member_for(db, household_id, current_user.user_id)
    item = upsert_item(db, household_id, payload)
    db.commit()
    db.refresh(item)
    return item_dict(item)


@router.put("/{household_id}/fridge-items/{fridge_item_id}")
def update_fridge_item(household_id: int, fridge_item_id: int, payload: FridgeItemUpdateSchema, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    member_for(db, household_id, current_user.user_id)
    item = db.query(FridgeItem).filter_by(household_id=household_id, fridge_item_id=fridge_item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="냉장고 재료를 찾을 수 없습니다.")
    item.quantity, item.unit = payload.quantity, payload.unit
    db.commit()
    db.refresh(item)
    return item_dict(item)


MAX_IMAGE_DIMENSION = 4096


def validate_and_reencode_image(content: bytes) -> tuple[bytes, str]:
    """매직 바이트를 검증하고 메타데이터(EXIF)를 제거하며 안전하게 재인코딩합니다."""
    # 1. Magic byte 기반 검증 (확장자 위조 방지)
    kind = filetype.guess(content)
    if not kind or kind.mime not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=422, detail="유효한 이미지 파일(JPEG, PNG, WEBP)이 아닙니다.")

    # 2. PIL을 통한 디컴프레션 폭탄 방지 및 EXIF 메타데이터 제거 재인코딩
    try:
        with Image.open(io.BytesIO(content)) as img:
            width, height = img.size
            if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
                img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION))

            if img.mode in ("RGBA", "P", "LA"):
                clean_img = img.convert("RGB")
            elif img.mode != "RGB":
                clean_img = img.convert("RGB")
            else:
                clean_img = img.copy()

            out_buffer = io.BytesIO()
            clean_img.save(out_buffer, format="JPEG", quality=85, optimize=True)
            return out_buffer.getvalue(), "image/jpeg"
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail="손상되었거나 처리할 수 없는 이미지 파일입니다.") from exc


def sanitize_extracted_string(val: str, max_len: int = 50) -> str:
    """추출된 텍스트에서 제어 문자, 특수 문자 및 순회 패턴을 제거합니다."""
    if not val:
        return ""
    # 제어문자 및 널 바이트 제거
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", str(val))
    # 파일 경로 순회 및 태그 기호 제거
    cleaned = cleaned.replace("..", "").replace("/", "").replace("\\", "")
    cleaned = re.sub(r"[<>]", "", cleaned)
    return cleaned.strip()[:max_len]


@router.post("/{household_id}/vision/parse")
async def parse_shopping_image(household_id: int, image: UploadFile = File(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Vision 제공자에게 전달하기 전에 임시 이미지 업로드를 검증합니다."""
    member_for(db, household_id, current_user.user_id)
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="이미지 인식 API 키가 설정되지 않았습니다. 직접 입력해 주세요.")

    content = await image.read()
    max_upload_bytes = int(os.getenv("MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))
    if not content or len(content) > max_upload_bytes:
        raise HTTPException(status_code=422, detail="8MB 이하의 유효한 이미지 파일을 올려 주세요.")

    # 원본 파일명 무시 및 난수화 식별자 부여 (경로 순회/공격 방지)
    _safe_filename = f"{uuid.uuid4().hex}.jpg"

    # 매직 바이트 검증 및 EXIF 메타데이터 제거된 깨끗한 바이트 스트림 생성
    sanitized_bytes, media_type = validate_and_reencode_image(content)

    try:
        # 외부 AI 호출은 짧은 timeout과 제한된 재시도로 요청 적체를 막습니다.
        result = OpenAI(timeout=30.0, max_retries=1).chat.completions.create(
            model=os.getenv("FRIDGE_VISION_MODEL", "gpt-4o-mini"),
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "Extract grocery items from Korean receipts or shopping screenshots. Return JSON only: {\"items\": [{\"name\": string, \"quantity\": number, \"unit\": string}]}. Include only food ingredients; use piece when quantity/unit is absent.",
                },
                {"role": "user", "content": [{"type": "text", "text": "영수증 또는 장보기 목록에서 식재료를 추출하세요."}, {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{base64.b64encode(sanitized_bytes).decode()}"}}]},
            ],
        )
        parsed = json.loads(result.choices[0].message.content or "{}")
        raw_items = parsed.get("items", [])
        sanitized_items = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            name = sanitize_extracted_string(raw_item.get("name", ""), max_len=50)
            if not name:
                continue
            unit = sanitize_extracted_string(raw_item.get("unit", "piece"), max_len=20) or "piece"
            try:
                quantity = float(raw_item.get("quantity", 1.0))
                if quantity < 0:
                    quantity = 1.0
            except (ValueError, TypeError):
                quantity = 1.0
            sanitized_items.append({"name": name, "quantity": quantity, "unit": unit})

        return {"items": sanitized_items}
    except Exception as error:
        # 제공자 상세 오류에는 내부 정보가 포함될 수 있어 응답에서 숨깁니다.
        raise HTTPException(status_code=422, detail="이미지에서 재료를 읽지 못했습니다.") from error


@router.post("/{household_id}/fridge-items/confirm")
def confirm_vision_items(household_id: int, payload: list[FridgeItemInputSchema], current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    member_for(db, household_id, current_user.user_id)
    items = [upsert_item(db, household_id, item, source="vision") for item in payload]
    db.commit()
    for item in items:
        db.refresh(item)
    return [item_dict(item) for item in items]


@router.post("/{household_id}/recipes/{recipe_id}/availability")
def recipe_availability(household_id: int, recipe_id: int, payload: AvailabilitySchema, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    member_for(db, household_id, current_user.user_id)
    return availability(db, household_id, recipe_id, payload.servings)


@router.post("/{household_id}/purchase-requests", status_code=status.HTTP_201_CREATED)
def create_purchase_request(household_id: int, payload: PurchaseRequestCreateSchema, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user_id = current_user.user_id
    member = member_for(db, household_id, user_id)
    request = PurchaseRequest(household_id=household_id, requester_id=user_id, recipe_id=payload.recipe_id, servings=payload.servings)
    db.add(request)
    db.flush()
    for request_item in payload.items:
        ingredient = get_or_create_ingredient(db, request_item)
        db.add(PurchaseRequestItem(purchase_request_id=request.purchase_request_id, ingredient_id=ingredient.ingredient_id,
                                   quantity=request_item.quantity, unit=request_item.unit))
    db.commit()
    return {"purchase_request_id": request.purchase_request_id, "status": request.status.value, "requester_role": member.role.value}


@router.get("/{household_id}/purchase-requests")
def get_purchase_requests(household_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    member_for(db, household_id, current_user.user_id)
    requests = db.query(PurchaseRequest).options(joinedload(PurchaseRequest.requester), joinedload(PurchaseRequest.recipe)).filter_by(household_id=household_id).order_by(PurchaseRequest.created_at.desc()).all()
    response = []
    for request in requests:
        items = db.query(PurchaseRequestItem).options(joinedload(PurchaseRequestItem.ingredient)).filter_by(purchase_request_id=request.purchase_request_id).all()
        response.append({"purchase_request_id": request.purchase_request_id, "status": request.status.value,
                         "requester_name": request.requester.name, "recipe_name": request.recipe.name if request.recipe else None,
                         "servings": request.servings, "items": [{"ingredient_id": item.ingredient_id, "name": item.ingredient.name, "quantity": float(item.quantity), "unit": item.unit, "shopping_url": f"https://www.coupang.com/np/search?q={quote_plus(item.ingredient.name)}"} for item in items]})
    return response


@router.patch("/{household_id}/purchase-requests/{request_id}")
def review_purchase_request(household_id: int, request_id: int, payload: PurchaseRequestStatusSchema, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user_id = current_user.user_id
    member = member_for(db, household_id, user_id)
    if member.role != HouseholdRole.PARENT:
        raise HTTPException(status_code=403, detail="부모 계정만 구매 요청을 처리할 수 있습니다.")
    request = db.query(PurchaseRequest).filter_by(household_id=household_id, purchase_request_id=request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="구매 요청을 찾을 수 없습니다.")
    if request.status != RequestStatus.PENDING:
        raise HTTPException(status_code=409, detail="이미 처리된 구매 요청입니다.")
    request.status = RequestStatus(payload.status)
    request.reviewed_by = user_id
    db.commit()
    return {"purchase_request_id": request_id, "status": request.status.value}
