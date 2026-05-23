---
name: summarize_url
description: Fetch a webpage and extract its readable text content
---

## summarize_url

Fetch a webpage and extract clean, readable text. Removes navigation, scripts, styling, ads, and other chrome.

### Parameters
- `url` (string, required): The URL to fetch

### Usage
Call the `summarize_url` tool when:
- The user shares a link and you need to read its content
- You need to extract information from documentation or articles
- You want to verify the content of a referenced URL

### Limitations
- Some sites block automated requests (returns error)
- JavaScript-rendered content is not captured
- Content is truncated at ~3000 characters
- Requires `httpx` and `beautifulsoup4` Python packages
