"""
Google Places API integration.
Fetches restaurant info, ratings, review snippets, and website for Houston area.
"""
import requests
from config import GOOGLE_PLACES_API_KEY

PLACES_BASE = "https://maps.googleapis.com/maps/api/place"
HOUSTON_LATLNG = "29.7604,-95.3698"  # Houston city center


def search_restaurant(name: str, address: str = ""):
    """Search Google Places for a restaurant. Returns best match or None."""
    if not GOOGLE_PLACES_API_KEY:
        return None
    query = f"{name} {address} Houston TX".strip()
    resp = requests.get(
        f"{PLACES_BASE}/textsearch/json",
        params={
            "query": query,
            "type": "restaurant",
            "location": HOUSTON_LATLNG,
            "radius": 50000,
            "key": GOOGLE_PLACES_API_KEY,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        return None
    results = resp.json().get("results", [])
    if not results:
        return None
    place = results[0]
    return {
        "place_id": place.get("place_id", ""),
        "google_rating": place.get("rating", 0),
        "google_review_count": place.get("user_ratings_total", 0),
        "address": place.get("formatted_address", ""),
    }


def get_place_details(place_id: str) -> dict:
    """Fetch details including website and reviews for a place."""
    if not GOOGLE_PLACES_API_KEY or not place_id:
        return {}
    resp = requests.get(
        f"{PLACES_BASE}/details/json",
        params={
            "place_id": place_id,
            "fields": "website,reviews,url",
            "key": GOOGLE_PLACES_API_KEY,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        return {}
    return resp.json().get("result", {})


def extract_keywords(reviews: list[dict]) -> list[str]:
    flags = ["salty", "greasy", "fresh", "spicy", "sweet", "bland",
             "heavy", "light", "oily", "healthy", "rich", "crispy",
             "tender", "dry", "soggy", "flavorful"]
    found = set()
    for r in reviews:
        text = r.get("text", "").lower()
        for kw in flags:
            if kw in text:
                found.add(kw)
    return sorted(found)


def get_place_photos(place_id: str, max_photos: int = 10) -> list[bytes]:
    """Download up to max_photos images for a place. Returns list of image bytes."""
    if not GOOGLE_PLACES_API_KEY or not place_id:
        return []
    # First get photo references
    resp = requests.get(
        f"{PLACES_BASE}/details/json",
        params={
            "place_id": place_id,
            "fields": "photos",
            "key": GOOGLE_PLACES_API_KEY,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        return []
    refs = [p["photo_reference"] for p in resp.json().get("result", {}).get("photos", [])[:max_photos]]
    images = []
    for ref in refs:
        img_resp = requests.get(
            f"{PLACES_BASE}/photo",
            params={"maxwidth": 1200, "photo_reference": ref, "key": GOOGLE_PLACES_API_KEY},
            timeout=15,
        )
        if img_resp.status_code == 200:
            images.append(img_resp.content)
    return images


def enrich_restaurant(name: str, address: str = ""):
    """
    One-shot: search + fetch details + reviews.
    Returns enriched data dict or None.
    """
    info = search_restaurant(name, address)
    if not info:
        return None
    details = get_place_details(info["place_id"])
    reviews = details.get("reviews", [])
    info["website"] = details.get("website") or details.get("url", "")
    info["keywords"] = extract_keywords(reviews)
    info["review_snippets"] = [r.get("text", "")[:200] for r in reviews[:3]]
    return info
