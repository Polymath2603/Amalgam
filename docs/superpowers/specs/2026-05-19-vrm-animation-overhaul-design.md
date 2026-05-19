# VRM Animation Overhaul & Bug Fixes

**Date:** 2026-05-19
**Scope:** 13 bugs across animation/VRM, UI/settings, and chat — fixed incrementally with auto-tests between each

---

## Architecture: AnimationManager

New module: `frontend/animation.js`

Extracts animation logic from `avatar.js` into a dedicated manager. `AvatarRenderer` delegates animation decisions to it.

```
AnimationManager
├── state: 'idle' | 'playing'
├── current: VRMAnimation | null
├── idleTimer: number | null
├── idlePool: string[]
│
├── play(animation)        // stop current, play new immediately
├── onEmotion(emotion)     // map emotion → animation → play()
├── startIdle()
├── stopIdle()
└── dispose()
```

**Behavior:**
- New animation always interrupts current (no queue, no priority)
- Greeting plays once on page init only, not on character switch
- LLM emotions trigger `onEmotion()` which maps to animations
- Idle timer (30s inactivity) picks random from idle pool
- Idle stops during speech/emotion, restarts when they end

**Emotion → Animation mapping:**
- `happy` → greeting (30% chance) or subtle smile
- `surprised` → peaceSign
- `love` → peaceSign
- `victory` → dance
- `neutral` / others → return to idle

---

## Bug Fix Plan

### Group A: Animation/VRM (7 items)

Fix order by dependency (foundational first):

| # | Bug | Root cause | Fix |
|---|-----|-----------|-----|
| 1 | Batman VRM not loading | Model path/validation | Check path resolution, fallback to default |
| 2 | Letter icons → VRM icons | Icon renderer uses fallback | Run VRM icon generation for all characters |
| 3 | Center character in container | Container centered, not content | Center Three.js camera target, not CSS container |
| 4 | Preview head-box auto-sizing | Camera bounds not computed from VRM | Apply same auto-fit logic as main avatar |
| 5 | Ryuk not looking at camera | Saccade/lookAt misconfigured | Check lookAt target setup, ensure saccade points to camera |
| 6 | Diana voice bug | Emotion + lip sync conflict | Ensure emotion changes don't reset mouth state during speech |
| 7 | Greeting on start only | Greeting fires on character switch | Move greeting trigger to init-only path in app.js |

### Group B: UI/Settings (5 items)

| # | Bug | Fix |
|---|-----|-----|
| 8 | Unified settings cards | Remove section headers and per-section save buttons, all settings in single grid |
| 9 | Persistent audio toggles | Save mic/speaker toggle state to settings.json via API |
| 10 | Thinking on/off toggle | Add thinking mode toggle card in settings, persist to settings.json |
| 11 | Font size in settings | Wire font-size input to `--font-size` CSS variable on `:root` |
| 12 | Message action buttons | Add copy/edit/regenerate/speak buttons on message hover with proper event handlers |

### Group C: Chat (1 item)

| # | Bug | Fix |
|---|-----|-----|
| 13 | Error deletes prompt too | On error response, remove both error message and preceding user prompt from chat DOM |

---

## Testing Approach

For each of the 13 fixes:

1. Write a quick automated check:
   - DOM assertions (element exists, has correct class/style)
   - API calls (settings persist correctly)
   - Console injection (animation state transitions)
2. Run via puppeteer or browser console
3. Mark fix as verified
4. Move to next

After all 13: full manual pass by user.

---

## Execution Order

1. Batman VRM → auto-test
2. Letter→VRM icons → auto-test
3. Center character → auto-test
4. Preview head-box → auto-test
5. Ryuk gaze → auto-test
6. Diana voice → auto-test
7. Greeting init-only → auto-test
8. Unified settings → auto-test
9. Persistent toggles → auto-test
10. Thinking toggle → auto-test
11. Font size → auto-test
12. Message buttons → auto-test
13. Error cleanup → auto-test
14. User manual pass
