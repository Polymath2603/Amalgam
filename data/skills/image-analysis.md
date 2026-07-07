---
name: image-analysis
description: Analyze images and extract information
version: 1.0.0
author: amalgam-core
triggers:
  - "what's in this image"
  - "analyze this picture"
  - "describe the image"
  - "read this screenshot"
tools_required: []
---

## When to use
When the user shares an image and asks about its contents, or when visual information is needed.

## How to use
Analyze the provided image carefully. Describe what you see, identify objects, text, people, or context.

### Parameters
- `image` (image, required): The image to analyze

### Notes
- Be thorough—describe both foreground and background
- Read any visible text
- Note colors, composition, and style
- If the image contains code or UI, describe the functionality
