"""
Parse restaurant menu from image or PDF using Groq Vision (free tier).
Model: llama-3.2-11b-vision-preview
"""
import base64
import io
import json
import re
import fitz  # PyMuPDF
import PIL.Image
from groq import Groq
from config import GROQ_API_KEY

SYSTEM_PROMPT = """You are a nutrition-aware menu parser.

CRITICAL LANGUAGE RULE: If the menu contains Chinese characters, you MUST include them in the "name" field. Format: "中文名 English Name". Never drop Chinese characters. If a dish only has Chinese, keep Chinese. This is mandatory.

Given a restaurant menu image or text, extract every dish and estimate its nutritional profile
based on the dish name, ingredients listed, and cuisine type.

Use these guidelines (AHA / USDA standards):
- calorie_level: 1=low(<400kcal), 2=medium(400-700kcal), 3=high(>700kcal)
- sodium_level: 1=low(<300mg), 2=medium(300-600mg), 3=high(>600mg per serving)
- veggie_content: 1=none/minimal, 2=some vegetables, 3=vegetable-dominant
- protein_type: "poultry"(chicken/duck/turkey dishes where poultry IS the main ingredient),
                "seafood"(fish/shrimp/crab/lobster/clam),
                "beef"(steak/ground beef/brisket), "pork"(pork belly/ribs/ham/sausage/egg rolls),
                "lamb"(lamb chop/mutton), "plant"(tofu/beans/tempeh/veggie),
                "other"(pasta/rice/noodles/dessert/soup/mixed/unclear — use this when protein is secondary or mixed)
                NOTE: egg rolls, spring rolls, dumplings → "pork" or "other" (NOT poultry). Only use "poultry" when chicken/duck/turkey is clearly the star ingredient.
- is_indulgent: true for deep-fried, very heavy, desserts, or high-fat dishes

If the menu has both Chinese and English names for a dish, include both in the "name" field, e.g. "宫保鸡丁 Kung Pao Chicken". If only Chinese, keep Chinese. If only English, keep English.

Return ONLY a JSON array, no other text. Example:
[
  {
    "name": "宫保鸡丁 Kung Pao Chicken",
    "price": 14.99,
    "calorie_level": 2,
    "sodium_level": 3,
    "veggie_content": 2,
    "protein_type": "lean",
    "is_indulgent": false,
    "notes": "spicy"
  }
]
If price is not visible, use null. Include all dishes visible on the menu."""

MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


def _get_client():
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not set. Get a free key at console.groq.com")
    return Groq(api_key=GROQ_API_KEY)


def _parse_json(raw: str) -> list:
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Output was truncated — salvage complete objects before the cut-off
        last_brace = raw.rfind("},")
        if last_brace == -1:
            last_brace = raw.rfind("}")
        if last_brace != -1:
            salvaged = raw[: last_brace + 1].rstrip(",") + "\n]"
            try:
                return json.loads("[" + salvaged.lstrip("["))
            except json.JSONDecodeError:
                pass
        raise


def _pil_to_b64(img: PIL.Image.Image) -> str:
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _pdf_to_pil_images(pdf_bytes: bytes) -> list:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return [
        PIL.Image.open(io.BytesIO(page.get_pixmap(dpi=150).tobytes("png")))
        for page in doc
    ]


def _call_vision(images: list, text_prompt: str) -> str:
    """Send up to one image + prompt to Groq vision model."""
    client = _get_client()
    content = []
    # Groq vision supports one image per call
    if images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{_pil_to_b64(images[0])}"},
        })
    content.append({"type": "text", "text": text_prompt})
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        max_tokens=8192,
    )
    return response.choices[0].message.content


def _call_vision_multi(images: list, text_prompt: str) -> str:
    """
    Groq supports only 1 image per call.
    For multiple images, call once per image and merge results.
    """
    if not images:
        return _call_vision([], text_prompt)

    all_dishes = []
    seen = set()
    errors = []
    for i, img in enumerate(images):
        try:
            raw = _call_vision([img], text_prompt)
            dishes = _parse_json(raw)
            for d in dishes:
                key = d.get("name", "").lower().strip()
                if key and key not in seen:
                    seen.add(key)
                    all_dishes.append(d)
        except Exception as e:
            errors.append(f"图{i+1}: {e}")
            continue
    if not all_dishes:
        detail = "; ".join(errors) if errors else "图片中未找到菜单"
        raise ValueError(
            f"未能识别到菜品。可能原因：Google Places 的照片里没有菜单图。"
            f"建议直接拍菜单照片从'上传文件'导入。\n详情: {detail}"
        )
    return json.dumps(all_dishes)


def parse_menu(file_bytes: bytes, filename: str) -> list:
    """Parse menu from uploaded image or PDF bytes."""
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        images = _pdf_to_pil_images(file_bytes)
    else:
        images = [PIL.Image.open(io.BytesIO(file_bytes))]
    prompt = "Extract all dishes from this menu. Return only the JSON array."
    return _parse_json(_call_vision_multi(images, prompt))


def parse_menu_text(menu_text: str) -> list:
    """Parse menu from plain text (extracted from HTML)."""
    prompt = f"Extract all dishes from this menu text. Return only the JSON array.\n\n{menu_text}"
    return _parse_json(_call_vision([], prompt))


def parse_menu_from_google_photos(images_bytes: list) -> list:
    """Given image bytes from Google Places, find menu photos and extract dishes."""
    images = []
    for b in images_bytes:
        try:
            images.append(PIL.Image.open(io.BytesIO(b)))
        except Exception:
            continue
    if not images:
        raise ValueError("No valid photos found.")
    prompt = (
        "These are photos from a restaurant. "
        "Find any that show a menu and extract ALL visible dishes. "
        "Return only the JSON array."
    )
    return _parse_json(_call_vision_multi(images, prompt))
