from sqlalchemy import Column, String, Enum
from sqlalchemy.dialects.mysql import BIGINT
from db.base import Base
import enum

class Unit(str, enum.Enum):
    GRAMS = "g(그램)"
    KILOGRAMS = "kg(킬로그램)"
    LITERS = "l(리터)"
    MILLILITERS = "ml(밀리리터)"
    CUPS = "cup(컵)"
    TABLESPOONS = "tbsp(큰술)"
    TEASPOONS = "tsp(작은술)"
    PIECE = "piece(개)"
    SLICE = "slice(조각)"
    PACK = "pack(팩)"
    CAN = "can(통조림)"
    BUNCH = "bunch(다발)"
    PINCH = "pinch(꼬집)"
    SHEET = "sheet(장)"
    STICK = "stick(막대형)"

class Storage(str, enum.Enum):
    ROOM_TEMP = "상온 보관"
    REFRIGERATED = "냉장 보관"
    FROZEN = "냉동 보관"
    SEALED = "밀봉/진공 보관"
    DARK_COOL = "서늘하고 어두운 곳"
    AIRTIGHT = "밀폐 보관"

class WasteType(str, enum.Enum):
    FOOD = "음식물 쓰레기"
    GENERAL = "일반 쓰레기"
    RECYCLABLE = "재활용 쓰레기(플라스틱, 캔, 종이 등)"
    PLASTIC = "플라스틱"
    CAN = "캔"
    PAPER = "종이류"
    METAL = "금속류"
    GLASS = "유리류"
    HAZARDOUS = "유해 폐기물(배터리, 전구 등)"
    OTHER = "기타"

class Ingredient(Base):
    __tablename__ = "ingredient"

    ingredient_id = Column(BIGINT, primary_key=True, autoincrement=True, index=True)

    name = Column(String(100), nullable=False)
    unit = Column(Enum(Unit), nullable=False)
    storage_method = Column(Enum(Storage))
    waste_type = Column(Enum(WasteType))
