---
name: create_skill
description: Guide for creating effective SKILL.md skills that the AI can load at runtime
---

# How to Create a Skill

Skills are markdown files with YAML frontmatter that the AI loads on-demand via the `skill` tool. They inject knowledge, patterns, and instructions into the AI's context at runtime.

## Anatomy of a SKILL.md

```markdown
---
name: my-skill
description: "What this skill does in one line"
---

# Skill Title

## Section
Detailed instructions, patterns, or knowledge...
```

### Frontmatter Fields
- **name** (required): Unique identifier. Lowercase, hyphenated. Used to load the skill (`skill("my-skill")`).
- **description** (optional but recommended): Shown in the skill list when the AI decides which skill to load. If absent, the skill is hidden from the listing.

## When to Create a Skill

Create a skill when you find yourself repeating the same instructions, patterns, or knowledge. Good candidates:

- **Frameworks & Libraries**: Coding patterns, gotchas, conventions for a specific tech stack
- **Project Knowledge**: Architecture decisions, naming conventions, deployment procedures
- **User Preferences**: The user's preferred style, recurring tasks they ask for
- **Domain Expertise**: Specialized knowledge you frequently reference (legal, medical, technical)

## Best Practices

1. **Focused scope** — each skill should cover one topic. Don't create a single "everything" skill.
2. **Actionable content** — write instructions the AI can follow, not general reference.
3. **Name-description clarity** — the name and description are all the AI sees before deciding whether to load the skill. Make them descriptive.
4. **Use sections** — organize with `##` headings. The AI reads the full content on load.
5. **Include examples** — concrete examples are more useful than abstract rules.

## How to Create

Use the `create_skill` tool with:
- `name`: Unique, lowercase, hyphenated
- `description`: One-line summary shown in the skills list
- `content`: Full markdown body (without frontmatter — it's auto-generated)

## How to Load a Skill

Use the `skill` tool with the skill's `name` to load its content into context. The AI should do this when:
- It recognizes the task matches a skill's description
- The user mentions a framework, tool, or topic covered by a skill
- It needs specialized knowledge for the current task
