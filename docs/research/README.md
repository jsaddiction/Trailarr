# Apple TV+ Provider Research

This directory contains research artifacts from the development of the Apple TV+ trailer provider.

## Research Process

The Apple TV+ provider was developed through extensive research and testing to ensure:
1. Accurate movie identification (avoiding wrong trailers)
2. High-quality trailer sources (4K, Dolby Vision, h265)
3. Reliable web scraping approach (after API alternatives failed)

## Proof of Concept

**`apple_tv_web_search_poc.py`** - Final working proof-of-concept demonstrating:
- Web search at `https://tv.apple.com/us/search?term=...`
- 5-layer safety system preventing wrong trailer downloads
- Title normalization and Jaccard similarity scoring
- Year matching from releaseDate timestamps
- Extraction of Apple content IDs (umc.cmc.xxxxx) from "Top Results" only

This code was ported into production as `/trailarr/providers/appletv/search.py`.

## Key Findings

### Search Approach

After testing multiple approaches, we settled on web search:
- ❌ **iTunes Search API**: Apple TV+ exclusives not in iTunes Store
- ❌ **Direct API**: Required homepage token extraction (brittle)
- ✅ **Web Search Page**: Reliable, includes "Top Results" vs recommendations distinction

### Safety Layers

1. **"isn't available" message check**: Detects when Apple has no results
2. **"Top Results" section verification**: Distinguishes actual matches from recommendations
3. **shelf-grid__body extraction**: Only considers real search results
4. **Exact year matching**: Uses releaseDate timestamp (milliseconds since epoch)
5. **95% title similarity**: Normalized Jaccard similarity prevents mismatches

### Test Results

Tested on 7 movies with 100% accuracy:
- ✅ Napoleon (2023)
- ✅ CODA (2021)
- ✅ Greyhound (2020)
- ✅ Tetris (2023)
- ✅ Killers of the Flower Moon (2023)
- ❌ The Matrix (1999) - correctly skipped (not on Apple TV+)
- ❌ Blade Runner (1982) - correctly skipped (not on Apple TV+)

## Implementation

The production implementation follows the existing Trailarr provider pattern:
- `AppleTVProvider` class implements `TrailerProvider` protocol
- Uses `ProviderRunState` for in-memory tracking
- Uses `ProviderStateManager` for persistent rate limit storage
- Integrates with yt-dlp for HLS m3u8 download (no special handling needed)

## Dependencies

Added to `requirements.txt`:
- `beautifulsoup4>=4.12.3` (HTML parsing)

## See Also

- [APPLE_TV_RESEARCH.md](../APPLE_TV_RESEARCH.md) - Comprehensive research notes
- Production code: `/trailarr/providers/appletv/`
