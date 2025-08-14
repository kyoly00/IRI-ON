# seed.py
import csv
from db.session import SessionLocal
from models.recipe.recipe import Recipe, Difficulty

difficulty_map = {
    "초급": Difficulty.EASY,
    "아무나": Difficulty.ANY,
    "중급": Difficulty.MEDIUM,
    "고급": Difficulty.HARD,
}

def seed():
    db = SessionLocal()
    try:
        with open("data/recipes.csv", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if db.query(Recipe).count() == 0:    
                existing_names = {r.name for r in db.query(Recipe.name).all()}

                for row in reader:
                    if row["title"] in existing_names:
                        continue

                    diff_value = difficulty_map.get(row["difficulty"])
                    if not diff_value:
                        continue

                    recipe = Recipe(
                        name=row["title"],
                        description=row["description"],
                        image_url=row["main_image"],
                        time=int(row["time"]) if row["time"].isdigit() else None,
                        servings=int(row["servings"]) if row["servings"].isdigit() else None,
                        difficulty=diff_value,
                        instructions=row["steps"],
                        tools=row["tools"],
                        materials=row["materials"],
                        tips=row["tips"],
                    )
                    db.add(recipe)
                    existing_names.add(row["title"])
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
