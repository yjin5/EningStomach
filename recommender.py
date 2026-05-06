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
) -> list[dict]:
    """
    Return up to top_n recommended dishes as dicts, ranked by composite score.
    """
    exclude_restaurant_ids = set(exclude_restaurant_ids or [])
    exclude_keywords = set(kw.lower() for kw in (exclude_keywords or []))

    # Filter restaurants by cuisine category first
    if cuisine_categories:
        allowed_rids = {r["id"] for r in get_restaurants(cuisine_categories=cuisine_categories)}
    else:
        allowed_rids = None

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
        if max_price is not None and d["price"] is not None and d["price"] > max_price:
            continue

        # Keyword exclusion (from Yelp mentions or notes)
        mentions = (d.get("yelp_mentions") or "").lower()
        notes = (d.get("notes") or "").lower()
        if any(kw in mentions or kw in notes for kw in exclude_keywords):
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
        # Add small random jitter so it's not always the same top result
        composite += random.uniform(0, 0.05)

        d["_score"] = round(composite, 3)
        d["_prefer_healthy"] = prefer_healthy
        d["_indulgence_score"] = round(indulgence_score, 2)
        scored.append(d)

    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored[:top_n]


def diet_status_message(indulgence_score: float) -> str:
    if indulgence_score >= 0.6:
        return "最近吃得比较油腻，今天建议清淡一些。"
    elif indulgence_score >= 0.3:
        return "最近饮食均衡，今天随意。"
    else:
        return "最近吃得很健康，今天可以放松一下。"
