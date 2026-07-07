---
name: deep-web-research
description: Multi-source research with contradiction detection and synthesis
version: 1.0.0
author: amalgam-core
triggers:
  - "research"
  - "find information about"
  - "look into"
  - "investigate"
tools_required: [web_search, url_fetch]
---
## When to use
Use when the question requires checking multiple sources, not just one search.
Signs: "what do experts say", "compare approaches", current events, technical topics.

## Process
1. Generate 3 search queries from different angles: broad, specific, skeptical ("problems with X")
2. Run all 3 searches
3. Fetch full content of top 2 results per query (6 sources total)
4. Identify any direct contradictions between sources — flag as [CONFLICT: A says X, B says Y]
5. Synthesize: direct answer → key evidence → conflicts → uncertainty flags [one source]

## Notes
- Never cite only one source for factual claims
- Cap synthesis at 400 words unless asked for more
- Flag claims supported by only one source with [one source]
