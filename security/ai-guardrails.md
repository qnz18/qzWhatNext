### qzWhatNext – AI Guardrails (Canonical)

**Version:** 0.1.1  
**Last Updated:** 2026-01-17  
**Status:** Locked (MVP)

This document defines the non-negotiable AI safety and privacy rules. It must align with:
- `context-pack.md` (Section 4)
- `engine/scoring-and-scheduling.md` (AI exclusion enforcement)

---

### 1. AI Exclusion (MUST ENFORCE BEFORE ANY AI CALL)

A task is AI-excluded if:
- Its title begins with a period (`.`), OR
- The user explicitly flags `ai_excluded: true`

**AI-excluded tasks:**
- MUST NEVER be sent to AI
- MUST NEVER receive AI-updated attributes
- MUST NEVER change tiers due to AI inference
- MAY still be scheduled deterministically

This check must occur **before any OpenAI / LLM call** (trust-critical).

---

### 2. Allowed AI Outputs (Structured Only)

AI may propose structured attributes **with confidence scores**:
- category
- estimated duration + duration confidence
- energy intensity (not used for scheduling in MVP)
- risk_score / impact_score
- dependencies

AI may not propose priority tiers.

---

### 3. Disallowed AI Behavior

AI must not:
- Assign priority tiers (rules engine is authoritative)
- Override hard constraints (blocked time, manual events, locked blocks)
- Generate free-form user-facing explanations (MVP uses templates)
- Operate on AI-excluded tasks

---

### 4. Logging and Data Minimization

**Do not log secrets or tokens**, including:
- OAuth credentials
- JWTs
- Shortcut tokens (`X-Shortcut-Token`)

For AI-excluded tasks, avoid logging task content (title/notes) in plaintext where possible; prefer task IDs.

---

### 5. Automation Token (iOS Shortcuts) Safety

The system supports long-lived automation tokens for clients that cannot refresh JWTs.

Requirements:
- Tokens must be revocable
- Store only **hashed** tokens at rest
- Never display the raw token after creation (one-time reveal)
- Never log the raw token

