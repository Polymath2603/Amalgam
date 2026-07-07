---
name: read_vault
description: Search and retrieve notes from the personal knowledge vault
---

## read_vault

Search for, read, or list notes from the user's persistent knowledge vault.

### Parameters
- `query` (string, optional): Keywords to search for — matches against file content
- `filename` (string, optional): Exact filename to read (overrides query)

### Usage
Call `read_vault` when:
- The user asks "do you remember..." or similar
- You need to retrieve saved information
- The user wants to review their notes
- You want to check if you've saved something before creating a duplicate

### Behavior
- With `filename`: reads and returns the full file content
- With `query` only: searches all vault files, returns ranked snippets
- With neither: lists all vault files
