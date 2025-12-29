# qzWhatNext

Continuously tells you what you should be doing **right now** and **immediately next**—across work, children, health, and home responsibilities—while prioritizing **user trust** through deterministic, explainable behavior.

## What this is (MVP)

qzWhatNext (MVP) does three things, end-to-end:

1. **Ingest tasks from Todoist**
2. **Infer structured attributes** (category, duration, energy, risk, impact, dependencies) when allowed
3. **Deterministically stack-rank + auto-schedule** tasks into real calendar time, including **Transition Time**, while enforcing user constraints and energy budgeting

## Product principles (non-negotiable)

- **Trust over optimization**
- **Deterministic rules override AI**
- **User-blocked time is never moved**
- **Manually scheduled events are never moved**
- **Every system action is explainable (one line)**
- **Every system action is reversible**
- **No user data is shared with third parties**

## AI guardrails (critical)

### AI-excluded tasks
A task must be excluded from AI reasoning if either is true:
- The task title starts with a period: `.something`
- The user flags it as AI-excluded

AI-excluded tasks:
- are **never** sent to AI
- **never** receive AI-updated attributes
- **never** auto-change tier due to AI
- may still be scheduled deterministically

### AI is allowed to infer (structured only)
AI may propose (with confidence scores):
- category
- estimated duration
- energy intensity
- risk / impact
- dependencies
- transition candidates

AI may **not**:
- assign priority tiers
- override hard constraints
- generate free-form user-facing explanations (MVP)

## How prioritization works

- Every task has **exactly one governing priority tier** at any moment.
- Tier assignment follows a **fixed hierarchy** (predictability > personalization).
- AI proposes attributes; the **rules engine assigns tiers deterministically**.
- Tier changes:
  - **High-confidence** attribute corrections can apply automatically (with logging + one-line reason)
  - **Low-confidence** changes require user confirmation

## Scheduling basics

- Default scheduling granularity: **30 minutes**
- Tasks may be **split** across blocks
- The system may move **only** blocks it scheduled itself
- The system may **not** move:
  - user-blocked time
  - manually scheduled events
- When workload exceeds capacity:
  - protect higher-importance tasks
  - defer lower-tier tasks
  - notify the user (no silent failures)

## Transition Time (first-class)

Transition Time is system-generated time between tasks/states (e.g., driving, setup/teardown, changing clothes, context switching):

- **schedulable and visible**
- **not stack-ranked**
- **not snoozable**
- consumes time and energy
- influenced by deterministic templates + user-defined rules (and optional AI suggestions with confidence)

## Canonical documents (source of truth)

If behavior is unclear or disputed, consult in this order:

1. `context-pack.md` (global rules + product identity)
2. `decision-log/decisions.md` (locked decisions)
3. `engine/scoring-and-scheduling.md` (engine spec)
4. `prd/prd.md` (MVP scope + requirements)

**Canonical rule:** Chats generate artifacts. Artifacts replace chats.

## Suggested repo layout

This repo is designed to keep “source of truth” documents close to the code:

