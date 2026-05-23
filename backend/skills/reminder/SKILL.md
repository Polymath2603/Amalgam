---
name: reminder
description: Set a timer or delayed reminder
---

## reminder

Set an in-process timer that logs a message after a delay. Useful for time-based notifications.

### Parameters
- `text` (string, required): The reminder message to display
- `delay_seconds` (integer, optional, default 60): How long to wait

### Usage
Call the `reminder` tool when:
- The user asks you to remind them about something
- You need to notify the user after a time delay

### Limitations
- Timers are in-memory and lost on server restart
- The reminder is logged server-side — it does not send a push notification to the user
- Only visible in server logs, not in the chat UI
