---
name: web_search
description: Search the web for current information using DuckDuckGo
---

## web_search

Search the web for current information. Uses DuckDuckGo (no API key needed).

### Parameters
- `query` (string, required): The search terms
- `num_results` (integer, optional, default 5): Number of results to return

### Usage
Call the `web_search` tool directly with your query. Use this when:
- You need up-to-date information not in your training data
- You need to verify facts or find sources
- The user asks about current events, news, or recent developments

### Limitations
- Results are HTML-scraped from DuckDuckGo — format may break if DDG changes its markup
- No image search or specialized search filters
- Not suitable for private/authenticated content
