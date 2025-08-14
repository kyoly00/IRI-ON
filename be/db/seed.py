# seed.py
import csv
from db.session import SessionLocal
from models.recipe.recipe import Recipe, Difficulty, Category
from models.domain.ingredient import Ingredient
from models.recipe.recipe_ingredient import RecipeIngredient
from crud.recipe_crud import get_recipe_id_by_name
from crud.ingredient_crud import get_ingredient_id_by_name

difficulty_map = {
    "초급": Difficulty.EASY,
    "아무나": Difficulty.ANY,
    "중급": Difficulty.MEDIUM,
    "고급": Difficulty.HARD,
}

category_map = {
    "한식": Category.KOREAN,
    "중식": Category.CHINESE,
    "일식": Category.JAPANESE,
    "양식": Category.WESTERN,
    "간식": Category.SNACK,
    "기타": Category.OTHER,
}

def seed_recipes():
    db = SessionLocal()
    try:
        with open("data/recipes.csv", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if db.query(Recipe).count() == 0:    
                existing_names = []

                for row in reader:
                    if row["title"] in existing_names:
                        continue

                    diff_value = difficulty_map.get(row["difficulty"])
                    if not diff_value:
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
                        difficulty=diff_value,
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

def seed_ingredients():
    db = SessionLocal()
    try:
        with open("data/recipes_ingredients.csv", newline="", encoding="utf-8") as f:
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
        with open("data/recipes_ingredients.csv", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if db.query(RecipeIngredient).count() == 0:
                existing_keys = []

                for row in reader:
                    if (row["title"], row["ingredients"]) in existing_keys:
                        continue

                    recipe_id = get_recipe_id_by_name(db, row["title"])[0]
                    ingredient_id = get_ingredient_id_by_name(db, row["ingredients"])[0]
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


def seed():
    seed_recipes()
    seed_ingredients()
    seed_recipes_ingredients()
