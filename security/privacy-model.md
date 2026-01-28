### qzWhatNext – Privacy Model (Canonical)

**Version:** 0.1.1  
**Last Updated:** 2026-01-28  
**Status:** Locked (MVP)

This document describes what user data is stored, how it is protected, and what is shared externally.

---

### 1. Data Stored (MVP)

qzWhatNext stores:
- **Users**: Google user ID, email, optional name, timestamps
- **Tasks**: user-scoped task records and scheduling metadata
- **Scheduled blocks**: user-scoped schedule output blocks
- **Automation tokens**: hashed long-lived tokens (for iOS Shortcuts), plus non-sensitive prefix

---

### 2. Data NOT Stored / Committed

Must not be committed to the repo:
- `.env`
- `credentials.json`
- `token.json`, `sheets_token.json`
- `*.db` files
- Any API keys, OAuth secrets, private keys

---

### 3. External Sharing (MVP)

Third-party calls may occur only when explicitly configured:
- Google token verification (Google ID token verification)
- Optional integrations (Google Calendar/Sheets)
- Optional OpenAI inference for non-excluded tasks

**AI-excluded tasks** must never be sent to AI.

---

### 3.1 Google Calendar Data Minimization (MVP)

When Google Calendar is connected, qzWhatNext uses Calendar to compute availability for scheduling.

For **non-qzWhatNext-managed** calendar events, qzWhatNext reads **only**:
- start time
- end time

It does **not** need (and does not persist) event titles, descriptions, attendees, locations, or conferencing metadata to enforce “do not schedule during this time.”

---

### 4. Authentication Data Handling

- **JWTs**: signed by server secret; treated as secrets; never logged.
- **Shortcut tokens**: long-lived tokens used via `X-Shortcut-Token`.
  - Raw tokens are shown once at creation.
  - Only a **hash** is stored at rest.
  - Tokens are revocable.

---

### 5. Logging Rules (MVP)

- Never log raw tokens, OAuth credentials, or API keys.
- Prefer logging entity IDs over task titles/notes for privacy-sensitive flows (especially for excluded tasks).

