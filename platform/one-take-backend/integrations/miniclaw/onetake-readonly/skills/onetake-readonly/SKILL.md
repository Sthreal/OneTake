---
name: onetake-readonly
description: Inspect One Take projects, provider status, pipeline state, video state, and cost estimates through read-only MCP tools. Use when the user asks about an existing One Take project or video generation status.
---

# One Take Read-only

Use only these tools:

- onetake_get_provider_status
- onetake_list_projects
- onetake_get_project
- onetake_get_pipeline
- onetake_get_video
- onetake_estimate_video_cost

Rules:

1. Never claim a video is complete unless the tool response says the plan is complete and includes a video URL.
2. Never infer project state from chat history.
3. Never attempt to generate, confirm, retry, delete, or modify anything.
4. Return the project ID and the authoritative state from One Take.
5. If the MCP server is unavailable, report the failure and do not fabricate data.
## Controlled Write Tools

When enabled by One Take MCP capabilities, you may create projects, import allowlisted HTTPS images, start recognition/main image, generate scripts, and create video plans.

Never call `onetake_request_voice` or `onetake_request_video` directly from chat. Paid actions require a one-time `approval_id` created by the MiniClaw administrator action. If an approval is missing or expired, stop and ask the user to approve in the MiniClaw page.