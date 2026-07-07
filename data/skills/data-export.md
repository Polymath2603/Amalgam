---
name: data-export
description: Export conversation data, memories, or vault files
version: 1.0.0
author: amalgam-core
triggers:
  - "export this"
  - "save this as"
  - "download my data"
  - "export memories"
tools_required:
  - "read_vault"
  - "write_file"
---

## When to use
When the user wants to export their conversation, memories, vault notes, or other data.

## How to use
1. Ask what format they want (markdown, json, txt)
2. Use the appropriate tool to gather the data
3. Format it cleanly for download

### Parameters
- `format` (string, required): Export format (markdown, json, txt)
- `scope` (string, required): What to export (conversation, memories, vault, all)

### Notes
- Respect privacy—only export what the user explicitly asks for
- For large exports, summarize or chunk the output
