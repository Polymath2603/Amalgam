---
name: translate
description: Translate text between languages
version: 1.0.0
author: amalgam-core
triggers:
  - "translate this"
  - "can you translate"
  - "in french"
  - "in spanish"
tools_required: []
---

## When to use
When the user asks to translate text from one language to another.

## How to use
Identify the source and target languages from context. Just translate naturally—no special tool needed.

### Parameters
- `text` (string, required): The text to translate
- `target_language` (string, required): The target language
- `source_language` (string, optional): The source language (auto-detect if omitted)

### Notes
- Preserve formatting (markdown, code blocks, etc.)
- For technical terms, keep the original in parentheses
