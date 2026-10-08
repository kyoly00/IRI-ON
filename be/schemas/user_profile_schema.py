from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SkillLevel = Literal["not_used", "with_help", "independent"]
AgeGroup = Literal["under_8", "8_13", "14_18", "19_34", "35_49", "50_64", "65_plus", "unspecified"]
SupervisionLevel = Literal["always_together", "sometimes_help", "independent"]
AllergyStatus = Literal["none", "has", "unknown"]
AvatarType = Literal["preset", "upload"]

class UserProfileSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    name: str = Field(min_length=1, max_length=20)
    cooking_level: int = Field(default=1, ge=1, le=10)
    age_group: AgeGroup = "unspecified"
    supervision_level: SupervisionLevel = "sometimes_help"
    fire_skill: SkillLevel = "with_help"
    knife_skill: SkillLevel = "with_help"
    peeler_skill: SkillLevel = "with_help"
    scissors_skill: SkillLevel = "with_help"
    avatar_type: AvatarType = "preset"
    avatar_value: str = Field(default="baby1", max_length=512)
    photo_consent_confirmed: bool = False
    allergy_status: AllergyStatus = "unknown"
    allergies: list[str] = Field(default_factory=list, max_length=30)
    dietary_restrictions: list[str] = Field(default_factory=list, max_length=30)
    disliked_ingredients: list[str] = Field(default_factory=list, max_length=50)
