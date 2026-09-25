---
name: schedule-onetake-check
description: Create a recurring One Take status check that notifies the current channel.
argument-hint: <cron or interval> <project id or all>
---

Create a scheduled task using Miniclaw's Scheduler capability.

The task must only:

1. Call read-only One Take tools.
2. Check project, pipeline, video, and error state.
3. Notify the current channel when status changes or requires user action.
4. Never create, confirm, retry, delete, or pay for a One Take operation.

Keep notifications quiet while the state is unchanged.