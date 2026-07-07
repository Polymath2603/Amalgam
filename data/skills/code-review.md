---
name: code-review
description: Thorough code review including logic, security, and quality
version: 1.0.0
author: amalgam-core
triggers:
  - "review this code"
  - "check my code"
  - "look at this function"
  - "is this correct"
tools_required: []
---
## When to use
When shown code and asked to review, critique, or check it.

## Process
1. Read the full code before commenting
2. Check correctness: does the logic actually do what it claims?
3. Check edge cases: what happens with empty input, None, zero, very large values?
4. Check security: any injection risks, hardcoded secrets, unsafe eval/exec?
5. Check style: naming clarity, unnecessary complexity, missing error handling
6. Rate each issue: CRITICAL (breaks things) / WARN (could break things) / NITPICK (style)

## Notes
- Lead with the most important issue, not the easiest one
- If the code is correct and clean, say so clearly — don't invent issues
- Always explain WHY an issue matters, not just what it is
