---
name: prompt-engineering
description: Improve a prompt to be clearer, more effective, and less ambiguous
version: 1.0.0
author: amalgam-core
triggers:
  - "improve this prompt"
  - "make this prompt better"
  - "write a prompt for"
tools_required: []
---
## When to use
When asked to write or improve a prompt for an LLM.

## Process
1. Identify the task the prompt is trying to accomplish
2. Identify what's vague or missing: role? format? constraints? examples?
3. Rewrite with: specific role, explicit output format, constraints (length, tone), 1-2 examples
4. Add a "negative example" if hallucination is a risk: "Do NOT make up..."
5. Add chain-of-thought if reasoning is important: "Think step by step before answering"

## Notes
- Shorter is not always better — specificity beats brevity for LLM prompts
- Examples (few-shot) are the single highest-ROI addition to any prompt
