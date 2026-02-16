#!/usr/bin/env python
"""Use web search page instead of API search endpoint."""

import json
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import quote

def normalize_title(title):
    """Normalize title for comparison."""
    title = title.lower()
    title = re.sub(r'^(the|a|an)\s+', '', title)
    title = re.sub(r'[^\w\s]', '', title)
    title = re.sub(r'\s+', ' ', title).strip()
    return title

def calculate_title_match(search_title, result_title):
    """Calculate title match score."""
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

def search_apple_tv_web(title, year, min_title_score=0.95):
    """
    Search Apple TV using web search page (not API endpoint).

    Uses: https://tv.apple.com/us/search?term=...
    Instead of: https://tv.apple.com/api/search
    """

    # URL encode the search term
    search_term = quote(title)
    search_url = f"https://tv.apple.com/us/search?term={search_term}"

    print(f"🔍 Searching: '{title}' (year: {year})")
    print(f"   URL: {search_url}")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    resp = requests.get(search_url, headers=headers, timeout=10)

    if resp.status_code != 200:
        print(f"   ❌ Search failed: HTTP {resp.status_code}")
        return None

    # LAYER 1: Check for "isn't available" message
    soup = BeautifulSoup(resp.text, 'html.parser')

    for p_tag in soup.find_all("p"):
        text = p_tag.get_text()
        if "isn't available" in text.lower():
            print(f"   ⚠️  Apple says: '{text.strip()}'")
            print("   ❌ No results - skipping")
            return None

    print("   ✅ No 'isn't available' message")

    # LAYER 2: Check for "Top Results" section
    top_results_section = None

    for span in soup.find_all("span"):
        if "top result" in span.get_text().lower():
            parent = span.find_parent("div", class_="section-content")
            if parent:
                top_results_section = parent
                print("   ✅ Found 'Top Results' section")
                break

    if not top_results_section:
        print("   ⚠️  No 'Top Results' section")
        print("   ❌ Only recommendations - skipping")
        return None

    # LAYER 3: Extract IDs from Top Results only
    shelf = top_results_section.find("div", class_=re.compile(r"shelf-grid__body"))

    if not shelf:
        print("   ⚠️  No shelf grid in Top Results")
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
        print("   ⚠️  No IDs in Top Results")
        return None

    print(f"   ✅ Found {len(unique_ids)} items in Top Results")

    # LAYER 4: Extract metadata from JSON
    script = soup.find("script", id="serialized-server-data")

    if not script:
        print("   ⚠️  No metadata JSON")
        return None

    try:
        data = json.loads(script.string)
    except json.JSONDecodeError:
        print("   ⚠️  Could not parse JSON")
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
                    except:
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
        print("   ⚠️  Could not extract metadata")
        return None

    # LAYER 5: Filter by exact year
    year_matches = [m for m in movies if m["year"] == year]

    if not year_matches:
        print(f"   ⚠️  No results match year {year}")
        available_years = sorted(set(m["year"] for m in movies))
        print(f"   → Available years: {available_years}")
        return None

    print(f"   ✅ {len(year_matches)} results match year {year}")

    # LAYER 6: Score by title
    for movie in year_matches:
        movie["title_score"] = calculate_title_match(title, movie["title"])

    year_matches.sort(key=lambda x: x["title_score"], reverse=True)

    print(f"\n   Top matches:")
    for i, movie in enumerate(year_matches[:3], 1):
        score_pct = int(movie["title_score"] * 100)
        print(f"      {i}. {movie['title']} ({movie['year']}) - {score_pct}% match")

    best = year_matches[0]

    print(f"\n   Best match: {best['title']} ({best['year']})")
    print(f"   Title score: {best['title_score']:.3f} (threshold: {min_title_score})")

    if best["title_score"] >= min_title_score:
        print(f"   ✅ HIGH CONFIDENCE - Safe to download!")
        print(f"   ID: {best['id']}")
        return best
    else:
        print(f"   ❌ Title score too low - skipping")
        return None


# Test cases
print("=" * 80)
print("Web Search Page Test (Not API Endpoint)")
print("=" * 80)

test_cases = [
    ("Napoleon", 2023),
    ("CODA", 2021),
    ("Greyhound", 2020),
    ("Tetris", 2023),
    ("Killers of the Flower Moon", 2023),  # Should work now!
    ("The Matrix", 1999),
    ("Blade Runner", 1982),
]

results = []

for title, year in test_cases:
    print(f"\n{'=' * 80}")
    result = search_apple_tv_web(title, year, min_title_score=0.95)
    results.append((title, year, result is not None))
    print()

# Summary
print("=" * 80)
print("Summary")
print("=" * 80)

matches = sum(1 for _, _, matched in results if matched)
print(f"\nMatches: {matches}/{len(results)}")

print("\nResults:")
for title, year, matched in results:
    status = "✅ MATCH" if matched else "❌ SKIP"
    print(f"  {status}: {title} ({year})")

if any(t == "Killers of the Flower Moon" and m for t, y, m in results):
    print("\n🎉 SUCCESS! Killers of the Flower Moon now works!")
