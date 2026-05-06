"""
Search for a restaurant's menu online and return parsed dishes.
Flow: DuckDuckGo search → download PDF or fetch HTML → Claude extraction.
"""
import io
import re
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 15


def search_menu_urls(restaurant_name: str, location: str = "Houston TX", max_results: int = 6) -> list[dict]:
    """
    Search DuckDuckGo for menu pages or PDFs.
    Returns list of {title, url, is_pdf}.
    """
    query = f"{restaurant_name} {location} menu"
    results = []
    with DDGS() as ddg:
        for r in ddg.text(query, max_results=max_results):
            url = r.get("href", "")
            is_pdf = url.lower().endswith(".pdf") or "menu.pdf" in url.lower()
            results.append({
                "title": r.get("title", url),
                "url": url,
                "is_pdf": is_pdf,
            })
    # Sort: PDFs first
    results.sort(key=lambda x: not x["is_pdf"])
    return results


def fetch_menu_content(url: str) -> tuple:
    """
    Download URL. Returns (bytes, filename, content_type).
    Raises on failure.
    """
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "")
    filename = url.split("/")[-1].split("?")[0] or "menu"
    if not filename.endswith((".pdf", ".jpg", ".jpeg", ".png")):
        filename += ".html"
    return resp.content, filename, content_type


def html_to_menu_text(html_bytes: bytes) -> str:
    """Strip HTML to plain text, keep structure useful for menu parsing."""
    soup = BeautifulSoup(html_bytes, "html.parser")
    # Remove nav, footer, scripts, ads
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Collapse blank lines
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:12000]  # Claude context limit safety


def parse_menu_from_url(url: str) -> list[dict]:
    """
    Download URL and parse menu using Claude.
    Handles PDF and HTML pages.
    """
    from menu_parser import parse_menu, parse_menu_text

    content, filename, content_type = fetch_menu_content(url)

    is_pdf = "pdf" in content_type.lower() or filename.endswith(".pdf")
    is_image = any(t in content_type.lower() for t in ("jpeg", "jpg", "png", "image"))

    if is_pdf or is_image:
        return parse_menu(content, filename)
    else:
        # HTML → extract text → Claude
        menu_text = html_to_menu_text(content)
        return parse_menu_text(menu_text)
