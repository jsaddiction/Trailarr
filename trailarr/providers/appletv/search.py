"""Apple TV+ web search with 5-layer safety system."""

import json
import logging
import re
from datetime import datetime
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup


def normalize_title(title: str) -> str:
    """
    Normalize title for comparison.

    Removes articles (the/a/an), punctuation, and extra whitespace.
    Converts to lowercase.
    """
    title = title.lower()
    title = re.sub(r'^(the|a|an)\s+', '', title)
    title = re.sub(r'[^\w\s]', '', title)
    title = re.sub(r'\s+', ' ', title).strip()
    return title


def calculate_title_match(search_title: str, result_title: str) -> float:
    """
    Calculate Jaccard similarity between titles.

    Returns:
        1.0 for exact match after normalization
        0.0-1.0 for partial matches (intersection / union)
    """
    norm_search = normalize_title(search_title)
    norm_result = normalize_title(result_title)

    if norm_search == norm_result:
        return 1.0

    search_words = set(norm_search.split())
    result_words = set(norm_result.split())

    if not search_words or not result_words:
        return 0.0

    intersection = search_words & result_words
    union = search_words | result_words

    return len(intersection) / len(union)


def search_apple_tv(
    title: str,
    year: int,
    min_title_score: float = 0.95,
    log: logging.Logger | None = None
) -> dict | None:
    """
    Search Apple TV using web search page with 5-layer safety system.

    Args:
        title: Movie title to search
        year: Release year (must match exactly)
        min_title_score: Minimum title similarity threshold (default 95%)
        log: Logger instance (optional)

    Returns:
        Dict with keys: id, title, year, title_score
        None if no confident match found

    Safety Layers:
    1. Check for "isn't available" message → return None
    2. Verify "Top Results" section exists → return None if missing
    3. Extract IDs from shelf-grid__body only (not recommendations)
    4. Filter by exact year match
    5. Require title similarity ≥min_title_score
    """
    if log is None:
        log = logging.getLogger("TrailArr.Providers.AppleTV")

    # URL encode the search term
    search_term = quote(title)
    search_url = f"https://tv.apple.com/us/search?term={search_term}"

    log.debug("Searching Apple TV for '%s' (%s)", title, year)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    try:
        resp = requests.get(search_url, headers=headers, timeout=10)
    except requests.exceptions.RequestException as e:
        log.warning("Apple TV search request failed: %s", e)
        return None

    if resp.status_code != 200:
        log.warning("Apple TV search returned HTTP %s", resp.status_code)
        return None

    # LAYER 1: Check for "isn't available" message
    soup = BeautifulSoup(resp.text, 'html.parser')

    for p_tag in soup.find_all("p"):
        text = p_tag.get_text()
        if "isn't available" in text.lower():
            log.debug("Apple TV says: '%s' - no results", text.strip())
            return None

    log.debug("No 'isn't available' message found")

    # LAYER 2: Check for "Top Results" section
    top_results_section = None

    for span in soup.find_all("span"):
        if "top result" in span.get_text().lower():
            parent = span.find_parent("div", class_="section-content")
            if parent:
                top_results_section = parent
                log.debug("Found 'Top Results' section")
                break

    if not top_results_section:
        log.debug("No 'Top Results' section - only recommendations returned")
        return None

    # LAYER 3: Extract IDs from Top Results only
    shelf = top_results_section.find("div", class_=re.compile(r"shelf-grid__body"))

    if not shelf:
        log.debug("No shelf grid in Top Results")
        return None

    shelf_html = str(shelf)
    ids = re.findall(r'(umc\.cmc\.[a-z0-9]+)', shelf_html)

    # Deduplicate
    seen = set()
    unique_ids = []
    for id in ids:
        if id not in seen:
            seen.add(id)
            unique_ids.append(id)

    if not unique_ids:
        log.debug("No IDs found in Top Results")
        return None

    log.debug("Found %s items in Top Results", len(unique_ids))

    # LAYER 4: Extract metadata from JSON
    script = soup.find("script", id="serialized-server-data")

    if not script:
        log.debug("No metadata JSON found")
        return None

    try:
        data = json.loads(script.string)
    except json.JSONDecodeError as e:
        log.warning("Could not parse Apple TV JSON: %s", e)
        return None

    # Extract movies matching Top Results IDs
    movies = []

    def extract_movies(obj):
        if isinstance(obj, dict):
            movie_id = obj.get("id")

            if movie_id and movie_id in unique_ids:
                movie_title = obj.get("title", obj.get("name", ""))
                release_date = obj.get("releaseDate")

                movie_year = None
                if release_date and isinstance(release_date, (int, float)):
                    try:
                        dt = datetime.fromtimestamp(release_date / 1000)
                        movie_year = dt.year
                    except Exception:
                        pass

                if movie_title and movie_year:
                    movies.append({
                        "id": movie_id,
                        "title": movie_title,
                        "year": movie_year,
                        "type": obj.get("type", "Unknown"),
                    })

            for value in obj.values():
                if isinstance(value, (dict, list)):
                    extract_movies(value)

        elif isinstance(obj, list):
            for item in obj:
                extract_movies(item)

    extract_movies(data)

    if not movies:
        log.debug("Could not extract metadata for Top Results IDs")
        return None

    # LAYER 5: Filter by exact year
    year_matches = [m for m in movies if m["year"] == year]

    if not year_matches:
        available_years = sorted(set(m["year"] for m in movies))
        log.debug("No results match year %s (available: %s)", year, available_years)
        return None

    log.debug("%s results match year %s", len(year_matches), year)

    # Score by title similarity
    for movie in year_matches:
        movie["title_score"] = calculate_title_match(title, movie["title"])

    year_matches.sort(key=lambda x: x["title_score"], reverse=True)

    # Log top matches
    log.debug("Top matches:")
    for i, movie in enumerate(year_matches[:3], 1):
        score_pct = int(movie["title_score"] * 100)
        log.debug("  %s. %s (%s) - %s%% match", i, movie['title'], movie['year'], score_pct)

    best = year_matches[0]

    log.debug("Best match: %s (%s) - score: %.3f (threshold: %.3f)",
              best['title'], best['year'], best['title_score'], min_title_score)

    if best["title_score"] >= min_title_score:
        log.info("High confidence Apple TV match: %s (%s) - %s",
                 best['title'], best['year'], best['id'])
        return best
    else:
        log.debug("Title score too low - skipping to avoid wrong trailer")
        return None
