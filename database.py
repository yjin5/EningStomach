import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from config import DATABASE_URL

# ── Connection ────────────────────────────────────────────────────────────────

USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras

    @contextmanager
    def get_conn():
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor, connect_timeout=10)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    PH = "%s"   # PostgreSQL placeholder

else:
    DB_PATH = Path(__file__).parent / "food_picker.db"

    @contextmanager
    def get_conn():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    PH = "?"    # SQLite placeholder


def _row(r):
    """Normalize a DB row to a plain dict."""
    return dict(r) if r else None


def _rows(rs):
    return [dict(r) for r in rs]


# ── Schema ────────────────────────────────────────────────────────────────────

CUISINE_CATEGORIES = [
    "中国菜", "日本菜", "韩国菜", "东南亚菜", "印度菜",
    "中东/地中海菜", "意大利菜", "西班牙/墨西哥菜", "美式", "其他",
]

_CUISINE_MAP = {
    "chinese": "中国菜", "cantonese": "中国菜", "sichuan": "中国菜", "dim sum": "中国菜",
    "japanese": "日本菜", "sushi": "日本菜", "ramen": "日本菜", "izakaya": "日本菜",
    "korean": "韩国菜", "korean bbq": "韩国菜",
    "vietnamese": "东南亚菜", "thai": "东南亚菜", "pho": "东南亚菜",
    "indian": "印度菜", "curry": "印度菜",
    "middle eastern": "中东/地中海菜", "mediterranean": "中东/地中海菜",
    "lebanese": "中东/地中海菜", "persian": "中东/地中海菜",
    "italian": "意大利菜", "pizza": "意大利菜", "pasta": "意大利菜",
    "spanish": "西班牙/墨西哥菜", "mexican": "西班牙/墨西哥菜", "tex-mex": "西班牙/墨西哥菜",
    "american": "美式", "burger": "美式", "bbq": "美式", "southern": "美式",
}


def guess_category(cuisine_text: str) -> str:
    if not cuisine_text:
        return "其他"
    lower = cuisine_text.lower()
    for kw, cat in _CUISINE_MAP.items():
        if kw in lower:
            return cat
    return "其他"


def _col_exists(conn, table, column):
    if USE_PG:
        cur = conn.cursor()
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
            (table, column)
        )
        return cur.fetchone() is not None
    else:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        return column in cols


def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_PG:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS restaurants (
                    id               SERIAL PRIMARY KEY,
                    name             TEXT NOT NULL,
                    cuisine          TEXT,
                    cuisine_category TEXT DEFAULT '其他',
                    address          TEXT,
                    website          TEXT,
                    yelp_id          TEXT,
                    yelp_rating      REAL DEFAULT 0,
                    yelp_review_count INTEGER DEFAULT 0,
                    opening_hours    TEXT,
                    created_at       DATE DEFAULT CURRENT_DATE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dishes (
                    id              SERIAL PRIMARY KEY,
                    restaurant_id   INTEGER NOT NULL REFERENCES restaurants(id),
                    name            TEXT NOT NULL,
                    price           REAL,
                    calorie_level   INTEGER DEFAULT 2,
                    sodium_level    INTEGER DEFAULT 2,
                    veggie_content  INTEGER DEFAULT 1,
                    protein_type    TEXT DEFAULT 'other',
                    is_indulgent    INTEGER DEFAULT 0,
                    health_score    REAL DEFAULT 3.0,
                    yelp_mentions   TEXT,
                    notes           TEXT,
                    active          INTEGER DEFAULT 1
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS eat_history (
                    id          SERIAL PRIMARY KEY,
                    dish_id     INTEGER NOT NULL REFERENCES dishes(id),
                    eaten_date  DATE NOT NULL DEFAULT CURRENT_DATE,
                    indulgent   INTEGER DEFAULT 0,
                    notes       TEXT
                )
            """)
        else:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS restaurants (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    name             TEXT NOT NULL,
                    cuisine          TEXT,
                    cuisine_category TEXT DEFAULT '其他',
                    address          TEXT,
                    website          TEXT,
                    yelp_id          TEXT,
                    yelp_rating      REAL DEFAULT 0,
                    yelp_review_count INTEGER DEFAULT 0,
                    opening_hours    TEXT,
                    created_at       TEXT DEFAULT (date('now'))
                );
                CREATE TABLE IF NOT EXISTS dishes (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    restaurant_id   INTEGER NOT NULL REFERENCES restaurants(id),
                    name            TEXT NOT NULL,
                    price           REAL,
                    calorie_level   INTEGER DEFAULT 2,
                    sodium_level    INTEGER DEFAULT 2,
                    veggie_content  INTEGER DEFAULT 1,
                    protein_type    TEXT DEFAULT 'other',
                    is_indulgent    INTEGER DEFAULT 0,
                    health_score    REAL DEFAULT 3.0,
                    yelp_mentions   TEXT,
                    notes           TEXT,
                    active          INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS eat_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    dish_id     INTEGER NOT NULL REFERENCES dishes(id),
                    eaten_date  TEXT NOT NULL DEFAULT (date('now')),
                    indulgent   INTEGER DEFAULT 0,
                    notes       TEXT
                );
            """)
            # SQLite migrations
            if not _col_exists(conn, "restaurants", "cuisine_category"):
                conn.execute("ALTER TABLE restaurants ADD COLUMN cuisine_category TEXT DEFAULT '其他'")
                for row in _rows(conn.execute("SELECT id, cuisine FROM restaurants").fetchall()):
                    conn.execute("UPDATE restaurants SET cuisine_category=? WHERE id=?",
                                 (guess_category(row["cuisine"] or ""), row["id"]))
            if not _col_exists(conn, "restaurants", "opening_hours"):
                conn.execute("ALTER TABLE restaurants ADD COLUMN opening_hours TEXT")


# ── Hours helpers ─────────────────────────────────────────────────────────────

def is_open_today(opening_hours_json) -> bool:
    """Return True if the restaurant is open today (or hours unknown)."""
    if not opening_hours_json:
        return True
    try:
        weekday_text = json.loads(opening_hours_json)
        today = date.today().strftime("%A")  # e.g. "Tuesday"
        for entry in weekday_text:
            if entry.startswith(today):
                return "Closed" not in entry
    except Exception:
        pass
    return True


def today_hours(opening_hours_json) -> str:
    """Return today's hours string, e.g. '11:00 AM – 9:00 PM', or '' if unknown."""
    if not opening_hours_json:
        return ""
    try:
        weekday_text = json.loads(opening_hours_json)
        today = date.today().strftime("%A")
        for entry in weekday_text:
            if entry.startswith(today):
                return entry.split(": ", 1)[-1]
    except Exception:
        pass
    return ""


# ── Restaurants ───────────────────────────────────────────────────────────────

def add_restaurant(name, cuisine="", cuisine_category=None, address="", website="",
                   yelp_id="", yelp_rating=0, yelp_review_count=0, opening_hours=None):
    if cuisine_category is None:
        cuisine_category = guess_category(cuisine)
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_PG:
            cur.execute(
                """INSERT INTO restaurants (name, cuisine, cuisine_category, address, website,
                   yelp_id, yelp_rating, yelp_review_count, opening_hours)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (name, cuisine, cuisine_category, address, website, yelp_id, yelp_rating, yelp_review_count, opening_hours)
            )
            return cur.fetchone()["id"]
        else:
            cur = conn.execute(
                """INSERT INTO restaurants (name, cuisine, cuisine_category, address, website,
                   yelp_id, yelp_rating, yelp_review_count, opening_hours)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (name, cuisine, cuisine_category, address, website, yelp_id, yelp_rating, yelp_review_count, opening_hours)
            )
            return cur.lastrowid


def update_restaurant_hours(restaurant_id, opening_hours_json):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE restaurants SET opening_hours={PH} WHERE id={PH}",
            (opening_hours_json, restaurant_id)
        )


def update_restaurant_yelp(restaurant_id, yelp_id, yelp_rating, yelp_review_count, website=""):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE restaurants SET yelp_id={PH}, yelp_rating={PH}, yelp_review_count={PH},"
            f" website=COALESCE(NULLIF(website,''), {PH}) WHERE id={PH}",
            (yelp_id, yelp_rating, yelp_review_count, website, restaurant_id)
        )


def get_restaurants(cuisine_categories=None):
    with get_conn() as conn:
        cur = conn.cursor()
        if cuisine_categories:
            placeholders = ",".join([PH] * len(cuisine_categories))
            cur.execute(
                f"SELECT * FROM restaurants WHERE cuisine_category IN ({placeholders}) ORDER BY name",
                list(cuisine_categories)
            )
        else:
            cur.execute("SELECT * FROM restaurants ORDER BY name")
        return _rows(cur.fetchall())


def get_restaurant(restaurant_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM restaurants WHERE id={PH}", (restaurant_id,))
        return _row(cur.fetchone())


# ── Dishes ────────────────────────────────────────────────────────────────────

def compute_health_score(calorie_level, sodium_level, veggie_content, protein_type, is_indulgent):
    score = 5.0
    score -= (calorie_level - 1) * 0.8
    score -= (sodium_level - 1) * 0.8
    score += (veggie_content - 1) * 0.4
    protein_bonus = {
        "poultry": 0.2, "seafood": 0.4, "beef": 0.0, "pork": -0.1, "lamb": 0.0,
        "plant": 0.5, "other": 0.0,
        "lean": 0.3, "fatty": -0.3,  # legacy
    }
    score += protein_bonus.get(protein_type, 0)
    if is_indulgent:
        score -= 1.0
    return round(max(1.0, min(5.0, score)), 1)


def add_dish(restaurant_id, name, price, calorie_level, sodium_level,
             veggie_content, protein_type, is_indulgent, notes=""):
    health_score = compute_health_score(calorie_level, sodium_level, veggie_content, protein_type, is_indulgent)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""INSERT INTO dishes (restaurant_id, name, price, calorie_level,
               sodium_level, veggie_content, protein_type, is_indulgent, health_score, notes)
               VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})""",
            (restaurant_id, name, price, calorie_level, sodium_level,
             veggie_content, protein_type, int(is_indulgent), health_score, notes)
        )


def add_dishes_bulk(restaurant_id, dishes: list):
    with get_conn() as conn:
        cur = conn.cursor()
        for d in dishes:
            price = d.get("price")
            calorie_level = int(d.get("calorie_level", 2))
            sodium_level = int(d.get("sodium_level", 2))
            veggie_content = int(d.get("veggie_content", 1))
            protein_type = d.get("protein_type", "other")
            is_indulgent = bool(d.get("is_indulgent", False))
            health_score = compute_health_score(calorie_level, sodium_level, veggie_content, protein_type, is_indulgent)
            cur.execute(
                f"""INSERT INTO dishes (restaurant_id, name, price, calorie_level,
                   sodium_level, veggie_content, protein_type, is_indulgent, health_score, notes)
                   VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})""",
                (restaurant_id, d["name"], price, calorie_level, sodium_level,
                 veggie_content, protein_type, int(is_indulgent), health_score, d.get("notes", ""))
            )


def update_dish_yelp_mentions(dish_id, mentions_csv):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE dishes SET yelp_mentions={PH} WHERE id={PH}", (mentions_csv, dish_id))


def get_dishes(restaurant_id=None, active_only=True):
    with get_conn() as conn:
        cur = conn.cursor()
        q = ("SELECT d.*, r.name as restaurant_name, r.website, r.yelp_rating "
             "FROM dishes d JOIN restaurants r ON d.restaurant_id=r.id")
        where, params = [], []
        if active_only:
            where.append("d.active=1")
        if restaurant_id:
            where.append(f"d.restaurant_id={PH}")
            params.append(restaurant_id)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY r.name, d.name"
        cur.execute(q, params)
        return _rows(cur.fetchall())


def update_dish_protein_type(dish_id, protein_type):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE dishes SET protein_type={PH} WHERE id={PH}", (protein_type, dish_id))


def deactivate_dish(dish_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE dishes SET active=0 WHERE id={PH}", (dish_id,))


# ── Eat history ───────────────────────────────────────────────────────────────

def log_meal(dish_id, indulgent=False, notes=""):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO eat_history (dish_id, indulgent, notes) VALUES ({PH},{PH},{PH})",
            (dish_id, int(indulgent), notes)
        )


def get_history(days=30):
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_PG:
            cur.execute(
                """SELECT h.*, d.name as dish_name, d.is_indulgent, r.name as restaurant_name
                   FROM eat_history h
                   JOIN dishes d ON h.dish_id=d.id
                   JOIN restaurants r ON d.restaurant_id=r.id
                   WHERE h.eaten_date >= CURRENT_DATE - INTERVAL %s
                   ORDER BY h.eaten_date DESC""",
                (f"{days} days",)
            )
        else:
            cur.execute(
                """SELECT h.*, d.name as dish_name, d.is_indulgent, r.name as restaurant_name
                   FROM eat_history h
                   JOIN dishes d ON h.dish_id=d.id
                   JOIN restaurants r ON d.restaurant_id=r.id
                   WHERE h.eaten_date >= date('now', ?)
                   ORDER BY h.eaten_date DESC""",
                (f"-{days} days",)
            )
        return _rows(cur.fetchall())


def get_recently_eaten_dish_ids(days=7):
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_PG:
            cur.execute(
                "SELECT DISTINCT dish_id FROM eat_history WHERE eaten_date >= CURRENT_DATE - INTERVAL %s",
                (f"{days} days",)
            )
        else:
            cur.execute(
                "SELECT DISTINCT dish_id FROM eat_history WHERE eaten_date >= date('now', ?)",
                (f"-{days} days",)
            )
        return {r["dish_id"] for r in _rows(cur.fetchall())}


def get_history_by_date(date_str: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT h.*, d.name as dish_name, d.is_indulgent, r.name as restaurant_name
               FROM eat_history h
               JOIN dishes d ON h.dish_id=d.id
               JOIN restaurants r ON d.restaurant_id=r.id
               WHERE h.eaten_date = %s
               ORDER BY h.id DESC""" if USE_PG else
            """SELECT h.*, d.name as dish_name, d.is_indulgent, r.name as restaurant_name
               FROM eat_history h
               JOIN dishes d ON h.dish_id=d.id
               JOIN restaurants r ON d.restaurant_id=r.id
               WHERE h.eaten_date = ?
               ORDER BY h.id DESC""",
            (date_str,)
        )
        return _rows(cur.fetchall())


def delete_meal(meal_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM eat_history WHERE id={PH}", (meal_id,))


def delete_meals_by_date(date_str: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM eat_history WHERE eaten_date={PH}", (date_str,))


def get_recent_indulgence_score(days=5):
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_PG:
            cur.execute(
                """SELECT indulgent FROM eat_history
                   WHERE eaten_date >= CURRENT_DATE - INTERVAL %s
                   ORDER BY eaten_date DESC LIMIT 10""",
                (f"{days} days",)
            )
        else:
            cur.execute(
                """SELECT indulgent FROM eat_history
                   WHERE eaten_date >= date('now', ?)
                   ORDER BY eaten_date DESC LIMIT 10""",
                (f"-{days} days",)
            )
        rows = _rows(cur.fetchall())
    if not rows:
        return 0.0
    return sum(r["indulgent"] for r in rows) / len(rows)
