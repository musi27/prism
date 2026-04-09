import csv
import json
import os

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from langchain_core.tools import tool
import prism

# Session-level search cache to avoid duplicate queries
_search_cache: dict[str, list[dict]] = {}

OUTPUT_CSV = os.path.join(os.path.dirname(__file__), "output.csv")


@tool
@prism.watch
def search_web(query: str) -> str:
    """Search the web for information about a company or topic. Returns the top 3 results with title, URL, and snippet."""
    if query in _search_cache:
        return json.dumps(_search_cache[query])

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=3):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            })

    _search_cache[query] = results
    return json.dumps(results)


@tool
@prism.watch
def read_page(url: str) -> str:
    """Fetch a webpage and return its text content. Use this to read a company's website or a news article."""
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except requests.RequestException as e:
        return f"Error fetching page: {e}"

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove script and style elements
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    # Truncate to keep context small for Haiku
    if len(text) > 3000:
        text = text[:3000] + "\n\n[truncated]"

    return text


@tool
@prism.watch(skill="prospect_research")
def write_to_sheet(company: str, data: str) -> str:
    """Write research findings for a company to the spreadsheet. The data parameter must be a JSON string with keys: summary, size, recent_news, contact."""
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return "Error: data must be a valid JSON string."

    file_exists = os.path.exists(OUTPUT_CSV)

    with open(OUTPUT_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Company", "Summary", "Size", "Recent News", "Contact"])
        writer.writerow([
            company,
            parsed.get("summary", ""),
            parsed.get("size", ""),
            parsed.get("recent_news", ""),
            parsed.get("contact", ""),
        ])

    return f"Successfully wrote findings for {company} to spreadsheet."
