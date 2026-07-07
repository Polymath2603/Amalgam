---
name: coding-generate
description: Generate code from natural language descriptions
version: 1.0.0
author: amalgam-core
triggers:
  - "write a function"
  - "create a script"
  - "implement a class"
  - "generate code"
tools_required: []
---

## When to use
When the user asks you to write code, generate a function, class, script, or complete application.

## How to use
1. Understand the requirements thoroughly
2. Plan the architecture or algorithm before coding
3. Write clean, idiomatic, well-documented code
4. Include type hints, docstrings, and error handling

### Parameters
- `language` (string, required): The programming language
- `task` (string, required): What the code should do
- `requirements` (string, optional): Specific requirements, constraints, or libraries

### Notes
- Prefer readability over cleverness
- Include usage examples
- Note any assumptions or limitations
- Suggest tests where appropriate
