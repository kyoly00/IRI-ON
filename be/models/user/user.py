from sqlalchemy import BigInteger, Boolean, Column, DateTime, SmallInteger, String, Text, func
from db.base import Base

class User(Base):
    __tablename__ = "user"

    # SQLAlchemy 공통 타입을 사용해 MySQL/PostgreSQL 어느 dialect에서도 같은 모델을 사용한다.
    user_id = Column(BigInteger, primary_key=True, autoincrement=True, index=True)

    # 계정 기본 정보
    id = Column(String(100), nullable=False, unique=True)
    password = Column(String(100), nullable=False)
    name = Column(String(20), default="셰프")

    # 기존 추천 로직과의 호환 필드. 아래 skill 값이 independent일 때만 True로 동기화한다.
    can_use_fire = Column(Boolean, nullable=False, default=False)
    can_use_knife = Column(Boolean, nullable=False, default=False)
    can_use_peeler = Column(Boolean, nullable=False, default=False)
    can_use_scissors = Column(Boolean, nullable=False, default=False)

    # 도구별 안전 수준: not_used / with_help / independent
    fire_skill = Column(String(20), nullable=False, default="with_help")
    knife_skill = Column(String(20), nullable=False, default="with_help")
    peeler_skill = Column(String(20), nullable=False, default="with_help")
    scissors_skill = Column(String(20), nullable=False, default="with_help")

    # 사용자가 직접 설정하는 요리 숙련도와 조리 보조 수준
    cooking_level = Column(SmallInteger, nullable=False, default=1)
    age_group = Column(String(20), nullable=True)
    supervision_level = Column(String(30), nullable=False, default="sometimes_help")

    # preset이면 baby1~baby4, upload이면 Supabase Storage의 object key를 저장한다.
    # 만료되는 signed URL 자체는 DB에 저장하지 않는다.
    avatar_type = Column(String(20), nullable=False, default="preset")
    avatar_value = Column(String(512), nullable=False, default="baby1")
    photo_consent_confirmed = Column(Boolean, nullable=False, default=False)

    # 배열형 값은 기존 TEXT 컬럼 호환을 위해 JSON 문자열로 직렬화한다.
    allergy_status = Column(String(20), nullable=False, default="unknown")
    allergy = Column(Text, nullable=True, default=None)
    dietary_restrictions = Column(Text, nullable=True, default=None)
    disliked_ingredients = Column(Text, nullable=True, default=None)

    # 생성 및 최종 수정 시각
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
