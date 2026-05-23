---
name: note
description: Save a note to the personal knowledge vault
---

## note

Save information to the user's persistent knowledge vault as a markdown file. Notes persist across sessions and are searchable via `read_vault`.

### Parameters
- `title` (string, required): Note title — used as the filename
- `content` (string, required): Markdown content of the note
- `tags` (string, optional): Comma-separated tags for organization

### Usage
Call the `note` tool when:
- The user asks you to remember something
- You learn something important about the user (preferences, facts about their life)
- The user gives instructions they want persisted
- You want to save a useful reference, code snippet, or resource

### Best Practices
- Use descriptive titles that make notes easy to find later
- Add tags for better discoverability
- Frontmatter (tags, date) is automatically added
