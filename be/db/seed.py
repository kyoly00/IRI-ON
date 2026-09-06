# seed.py
import csv
import re
from pathlib import Path
from db.session import SessionLocal
from models.recipe.recipe import Recipe, Category as RecipeCategory
from models.domain.ingredient import Ingredient
from models.domain.tool import Tool, Category as ToolCategory
from models.recipe.recipe_ingredient import RecipeIngredient
from models.recipe.recipe_tool import RecipeTool
from models.recipe.recipe_step import RecipeStep
from crud.recipe_crud import get_recipe_by_name
from crud.domain_crud import get_ingredient_id_by_name, get_tool_id_by_name

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

category_map = {
    "한식": RecipeCategory.KOREAN,
    "중식": RecipeCategory.CHINESE,
    "일식": RecipeCategory.JAPANESE,
    "양식": RecipeCategory.WESTERN,
    "간식": RecipeCategory.SNACK,
    "기타": RecipeCategory.OTHER,
}

tools = {
    "칼": ToolCategory.knife,
    "가위": ToolCategory.scissors,
    "냄비": ToolCategory.fire,
    "프라이팬": ToolCategory.fire,
    "필러": ToolCategory.peeler,
    "에어프라이어": ToolCategory.other,
    "그릇": ToolCategory.other,
    "주걱": ToolCategory.other,
    "뒤집개": ToolCategory.other,
    "계량도구": ToolCategory.other,
    "도마": ToolCategory.other,
    "전자레인지": ToolCategory.other,
    "국자": ToolCategory.other,
    "체/거름망": ToolCategory.other,
    "집게": ToolCategory.other,
    "오븐": ToolCategory.other
}

def seed_recipes():
    db = SessionLocal()
    try:
        with (DATA_DIR / "recipes.csv").open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if db.query(Recipe).count() == 0:    
                existing_names = []

                for row in reader:
                    if row["title"] in existing_names:
                        continue

                    category_value = category_map.get(row["category"])
                    if not category_value:
                        continue

                    recipe = Recipe(
                        name=row["title"],
                        description=row["description"],
                        image_url=row["main_image"],
                        time=int(row["time"]) if row["time"].isdigit() else None,
                        servings=int(row["servings"]) if row["servings"].isdigit() else None,
                        instructions=row["steps"],
                        category=category_value,
                        tools=row["tools"],
                        materials=row["materials"],
                        tips=row["tips"],
                    )
                    db.add(recipe)
                    existing_names.append(row["title"])
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _number(value):
    match = re.search(r"\d+", value or "")
    return int(match.group()) if match else None


def seed_youtube_recipes():
    """대용량 CSV 중 YouTube 영상이 있는 레시피만 목록에 추가한다."""
    db = SessionLocal()
    try:
        existing = {recipe.name: recipe for recipe in db.query(Recipe).all()}
        difficulty_map = {
            "초급": "EASY",
            "중급": "MEDIUM",
            "고급": "HARD",
            "아무나": "EASY",
        }
        with (DATA_DIR / "recipes_2000to2054.csv").open(
            newline="", encoding="utf-8-sig"
        ) as file:
            for row in csv.DictReader(file):
                video_url = (row.get("video_url") or "").strip()
                if "youtube.com/" not in video_url and "youtu.be/" not in video_url:
                    continue

                recipe = existing.get(row["title"])
                if recipe:
                    recipe.video_url = video_url
                    continue

                recipe = Recipe(
                    name=row["title"],
                    description=row.get("description") or "",
                    image_url=row.get("main_image") or None,
                    time=_number(row.get("time")),
                    servings=_number(row.get("servings")),
                    difficulty=difficulty_map.get(row.get("difficulty") or "아무나", "EASY"),
                    instructions=row.get("steps") or "[]",
                    category=RecipeCategory.OTHER,
                    tools=row.get("tools") or "",
                    materials=row.get("materials") or "",
                    tips=row.get("tips") or "",
                    video_url=video_url,
                )
                db.add(recipe)
                existing[recipe.name] = recipe
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def seed_ingredients():
    db = SessionLocal()
    try:
        with (DATA_DIR / "recipes_ingredients.csv").open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if db.query(Ingredient).count() == 0:
                existing_names = []

                for row in reader:
                    if row["ingredients"] in existing_names:
                        continue

                    ingredient = Ingredient(
                        name=row["ingredients"],
                    )
                    db.add(ingredient)
                    existing_names.append(row["ingredients"])
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def seed_recipes_ingredients():
    db = SessionLocal()
    try:
        with (DATA_DIR / "recipes_ingredients.csv").open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if db.query(RecipeIngredient).count() == 0:
                existing_keys = []

                for row in reader:
                    if (row["title"], row["ingredients"]) in existing_keys:
                        continue

                    recipe_id = get_recipe_by_name(db, row["title"]).recipe_id
                    ingredient_id = get_ingredient_id_by_name(db, row["ingredients"]).ingredient_id
                    recipe_ingredient = RecipeIngredient(
                        recipe_id=recipe_id,
                        ingredient_id=ingredient_id,
                    )
                    db.add(recipe_ingredient)
                    existing_keys.append((row["title"], row["ingredients"]))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def seed_tools():
    db = SessionLocal()
    try:
        if db.query(Tool).count() == 0:
            existing_names = []

            for name, category in tools.items():
                if name in existing_names:
                    continue

                tool = Tool(
                    name=name,
                    category=category
                )
                db.add(tool)
                existing_names.append(name)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def seed_recipes_tools():
    db = SessionLocal()
    try:
        with (DATA_DIR / "recipes_tools.csv").open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if db.query(RecipeTool).count() == 0:
                existing_keys = []

                for row in reader:
                    if (row["title"], row["tools"]) in existing_keys:
                        continue

                    recipe_id = get_recipe_by_name(db, row["title"]).recipe_id
                    tool_id = get_tool_id_by_name(db, row["tools"]).tool_id
                    recipe_tool = RecipeTool(
                        recipe_id=recipe_id,
                        tool_id=tool_id,
                    )
                    db.add(recipe_tool)
                    existing_keys.append((row["title"], row["tools"]))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def seed_videos():
    db = SessionLocal()
    try:
        with (DATA_DIR / "shrimp_fried_rice_recipe_steps.csv").open(newline="", encoding="cp949") as f:
            reader = csv.DictReader(f)
            if db.query(RecipeStep).count() == 0:
                existing_keys = []

                for row in reader:
                    if (row["recipe_id"], row["step"]) in existing_keys:
                        continue

                    recipe_step = RecipeStep(
                        recipe_id=row["recipe_id"],
                        text=row["text"],
                        step=row["step"],
                        url=row["url"],
                        video_id=row["url"].split("youtu.be/")[-1].split("?")[0],
                        start_url=row["url"],
                        start_seconds=0,
                    )
                    db.add(recipe_step)
                    existing_keys.append((row["recipe_id"], row["step"]))
        # 이미 구축한 DB에도 새 영상 메타데이터를 채운다.
        for recipe_step in db.query(RecipeStep).all():
            if recipe_step.url and not recipe_step.start_url:
                recipe_step.start_url = recipe_step.url
            if recipe_step.url and not recipe_step.video_id and "youtu.be/" in recipe_step.url:
                recipe_step.video_id = recipe_step.url.split("youtu.be/")[-1].split("?")[0]
            if recipe_step.start_seconds is None and recipe_step.url:
                recipe_step.start_seconds = 0
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def seed():
    seed_recipes()
    seed_youtube_recipes()
    seed_ingredients()
    seed_recipes_ingredients()
    seed_tools()
    seed_recipes_tools()
    seed_videos()
