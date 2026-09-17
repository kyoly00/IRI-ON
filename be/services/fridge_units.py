from decimal import Decimal


UNIT_ALIASES = {
    "g": ("mass", Decimal("1")), "그램": ("mass", Decimal("1")), "kg": ("mass", Decimal("1000")), "킬로그램": ("mass", Decimal("1000")),
    "ml": ("volume", Decimal("1")), "밀리리터": ("volume", Decimal("1")), "l": ("volume", Decimal("1000")), "리터": ("volume", Decimal("1000")),
    "cup": ("volume", Decimal("240")), "컵": ("volume", Decimal("240")), "tbsp": ("volume", Decimal("15")), "t": ("volume", Decimal("15")), "큰술": ("volume", Decimal("15")),
    "tsp": ("volume", Decimal("5")), "작은술": ("volume", Decimal("5")),
    "piece": ("count", Decimal("1")), "개": ("count", Decimal("1")), "ea": ("count", Decimal("1")), "slice": ("count", Decimal("1")), "장": ("count", Decimal("1")),
}


def normalize(unit: str):
    return UNIT_ALIASES.get((unit or "").strip().lower())


def converted(quantity: Decimal, unit: str, target_unit: str):
    source, target = normalize(unit), normalize(target_unit)
    if not source or not target or source[0] != target[0]:
        return None
    return quantity * source[1] / target[1]
