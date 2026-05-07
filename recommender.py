"""
Recommendation engine.

Scoring factors (all normalized 0-1, then weighted):
  1. health_score     — AHA-aligned nutrition (weight varies by diet balance)
  2. yelp_rating      — Yelp stars / 5
  3. price_fit        — how well price fits today's budget
  4. novelty          — penalize dishes eaten recently (7-day cooldown)
  5. diet_balance     — if recent meals were indulgent, boost healthy options
"""
import random
from database import (
    get_dishes,
    get_restaurants,
    get_recently_eaten_dish_ids,
    get_recent_indulgence_score,
    is_open_today,
)


def _price_score(price, budget) -> float:
    if price is None:
        return 0.5  # unknown price: neutral
    if budget is None:
        return 0.8  # no budget set: slightly favor cheaper implicitly
    if price <= budget:
        return 1.0
    over = (price - budget) / budget
    return max(0.0, 1.0 - over * 2)


def recommend(
    cuisine_categories=None,
    exclude_restaurant_ids=None,
    exclude_keywords=None,
    max_price=None,
    prefer_healthy=None,
    cooldown_days: int = 7,
    top_n: int = 3,
    required_protein_types=None,
    exclude_shown_ids=None,
    min_rating: float = 0.0,
    boost_favorites: bool = False,
) -> list[dict]:
    """
    Return up to top_n recommended dishes as dicts, ranked by composite score.
    """
    exclude_restaurant_ids = set(exclude_restaurant_ids or [])
    exclude_keywords = set(kw.lower() for kw in (exclude_keywords or []))
    exclude_shown_ids = set(exclude_shown_ids or [])

    # Filter restaurants by cuisine category and open today
    all_rests = get_restaurants(cuisine_categories=cuisine_categories if cuisine_categories else None)
    open_rids = {r["id"] for r in all_rests if is_open_today(r.get("opening_hours"))}
    allowed_rids = open_rids if cuisine_categories else open_rids

    all_dishes = get_dishes(active_only=True)
    recently_eaten = get_recently_eaten_dish_ids(days=cooldown_days)
    indulgence_score = get_recent_indulgence_score(days=5)

    # Auto-decide health preference from recent diet
    if prefer_healthy is None:
        prefer_healthy = indulgence_score >= 0.4  # 40%+ indulgent meals → go healthy

    # Weight matrix
    w_health = 0.45 if prefer_healthy else 0.20
    w_yelp   = 0.25
    w_price  = 0.20
    w_novelty = 0.10

    scored = []
    for d in all_dishes:
        d = dict(d)

        # Hard exclusions
        if allowed_rids is not None and d["restaurant_id"] not in allowed_rids:
            continue
        if d["restaurant_id"] in exclude_restaurant_ids:
            continue
        if d["id"] in recently_eaten:
            continue
        if d["id"] in exclude_shown_ids:
            continue
        if max_price is not None and d["price"] is not None and d["price"] > max_price:
            continue

        # Keyword exclusion (from Yelp mentions or notes)
        mentions = (d.get("yelp_mentions") or "").lower()
        notes = (d.get("notes") or "").lower()
        if any(kw in mentions or kw in notes for kw in exclude_keywords):
            continue

        # Rating filter — skip only if rated AND below threshold
        if min_rating and d.get("yelp_rating") and d["yelp_rating"] < min_rating:
            continue

        # Compute component scores (all 0-1)
        s_health = (d["health_score"] - 1) / 4          # health_score 1-5 → 0-1
        s_yelp   = d["yelp_rating"] / 5.0 if d["yelp_rating"] else 0.5
        s_price  = _price_score(d.get("price"), max_price)
        s_novelty = 1.0  # not recently eaten (already filtered above)

        composite = (
            w_health  * s_health +
            w_yelp    * s_yelp   +
            w_price   * s_price  +
            w_novelty * s_novelty
        )
        # Favorite boost
        if boost_favorites and d.get("is_favorite"):
            composite += 0.20

        # Add small random jitter so it's not always the same top result
        composite += random.uniform(0, 0.05)

        d["_score"] = round(composite, 3)
        d["_prefer_healthy"] = prefer_healthy
        d["_indulgence_score"] = round(indulgence_score, 2)
        scored.append(d)

    scored.sort(key=lambda x: x["_score"], reverse=True)
    top = scored[:top_n]

    # Enforce required protein types (each must appear at least once)
    if required_protein_types:
        required_set = set(required_protein_types)
        for ptype in required_protein_types:
            if any(d.get("protein_type") == ptype for d in top):
                continue
            # Search all scored dishes (not just overflow) for best candidate
            candidate = next(
                (d for d in scored if d.get("protein_type") == ptype and d not in top),
                None
            )
            if candidate is None:
                continue
            # Replace lowest-scored dish that is not itself a required type
            currently_covered = required_set & {d.get("protein_type") for d in top}
            replaced = False
            for i in range(len(top) - 1, -1, -1):
                if top[i].get("protein_type") not in currently_covered:
                    top[i] = candidate
                    replaced = True
                    break
            # If all slots are required types, replace the last slot anyway
            if not replaced:
                top[-1] = candidate

    return top


_EXERCISES = [
    ("慢跑",   "Jogging",        9),
    ("快走",   "Brisk walk",     5),
    ("游泳",   "Swimming",      11),
    ("骑自行车","Cycling",        8),
    ("跳绳",   "Jump rope",     12),
    ("跳舞",   "Dancing",        6),
    ("爬楼梯", "Stair climbing",10),
    ("瑜伽",   "Yoga",           3),
    ("有氧操", "Aerobics",       7),
    ("篮球",   "Basketball",     8),
    ("足球",   "Soccer",         9),
    ("乒乓球", "Ping pong",      5),
    ("羽毛球", "Badminton",      7),
    ("网球",   "Tennis",         8),
    ("拳击",   "Boxing",        11),
    ("划船机", "Rowing machine",10),
    ("跑步机", "Treadmill",     10),
    ("卧推",   "Bench press",    4),
    ("深蹲",   "Squats",         5),
    ("椭圆机", "Elliptical",     8),
    ("壶铃训练","Kettlebell",    12),
    ("普拉提", "Pilates",        4),
]

_CALORIE_ESTIMATE = {0: 100, 1: 300, 2: 550, 3: 800}

_CUTE_TEMPLATES = [
    "吃完记得动一动哦～ 相当于{ex1}约 {t1} 分钟，或者{ex2}约 {t2} 分钟呢！",
    "这顿吃下去，要{ex1} {t1} 分钟才能消耗掉，也可以换成{ex2} {t2} 分钟～加油！",
    "热量小提示：需要{ex1}约 {t1} 分钟，或{ex2} {t2} 分钟来抵消，运动起来吧！",
    "想消耗这顿饭？{ex1} {t1} 分钟或{ex2} {t2} 分钟都行，你选哪个？",
]

_CUTE_TEMPLATES_EN = [
    "Remember to move! That's ~{ex1} for {t1} min, or {ex2} for {t2} min.",
    "Burn it off: {ex1} {t1} min, or swap for {ex2} {t2} min — your call!",
    "Calorie tip: {ex1} ~{t1} min or {ex2} ~{t2} min to offset this meal.",
    "Work it off with {ex1} {t1} min or {ex2} {t2} min. You got this!",
]


def exercise_hint(calorie_level: int, lang: str = "zh") -> str:
    kcal = _CALORIE_ESTIMATE.get(calorie_level, 550)
    picks = random.sample(_EXERCISES, 2)
    zh1, en1, rate1 = picks[0]
    zh2, en2, rate2 = picks[1]
    ex1 = en1 if lang == "en" else zh1
    ex2 = en2 if lang == "en" else zh2
    t1 = round(kcal / rate1)
    t2 = round(kcal / rate2)
    templates = _CUTE_TEMPLATES_EN if lang == "en" else _CUTE_TEMPLATES
    return random.choice(templates).format(ex1=ex1, t1=t1, ex2=ex2, t2=t2)


def calorie_estimate(calorie_level: int) -> int:
    return _CALORIE_ESTIMATE.get(calorie_level, 550)


def single_exercise_hint(calorie_level: int, lang: str = "zh"):
    """Returns (exercise_name, minutes) for one random exercise."""
    kcal = _CALORIE_ESTIMATE.get(calorie_level, 550)
    zh_name, en_name, rate = random.choice(_EXERCISES)
    name = en_name if lang == "en" else zh_name
    return name, round(kcal / rate)


def total_exercise_summary(total_kcal: int, lang: str = "zh") -> str:
    n = random.randint(2, len(_EXERCISES))
    picks = random.sample(_EXERCISES, n)
    display = picks[:3] if n >= 3 else picks
    splits = sorted([random.random() for _ in range(len(display) - 1)] + [0.0, 1.0])
    fracs = [splits[i+1] - splits[i] for i in range(len(display))]
    parts = []
    for (zh_name, en_name, rate), frac in zip(display, fracs):
        name = en_name if lang == "en" else zh_name
        unit = "min" if lang == "en" else "分钟"
        mins = round(total_kcal * frac / rate)
        if mins > 0:
            parts.append(f"{name} {mins} {unit}")
    combo = " + ".join(parts)
    if lang == "en":
        return f"This meal is ~**{total_kcal} kcal**. Burn it with: {combo} — just enough to offset it!"
    return f"这顿合计约 **{total_kcal} 千卡**，运动组合消耗方案：{combo}，合起来刚好抵消这顿饭～加油！"


def diet_status_message(indulgence_score: float, lang: str = "zh") -> str:
    if lang == "en":
        if indulgence_score >= 0.6:
            return "You've been eating heavy lately. Consider something lighter today."
        elif indulgence_score >= 0.3:
            return "Your diet has been balanced lately. No restrictions today."
        return "You've been eating healthy lately. Feel free to indulge a little."
    if indulgence_score >= 0.6:
        return "最近吃得比较油腻，今天建议清淡一些。"
    elif indulgence_score >= 0.3:
        return "最近饮食均衡，今天随意。"
    return "最近吃得很健康，今天可以放松一下。"
