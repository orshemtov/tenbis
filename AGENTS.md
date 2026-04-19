# AGENTS.md

## Do's

- Always strive to write the simplest code possible.
- Use Pydantic for modelling objects.
- Use `pydantic-settings` for environment variables.
- Import only at the top of the file.
- Prefer `mise run <task>` over raw `uv run` / `python` commands — keeps the interface consistent for humans and agents alike.
- All user-facing state (browser profiles, vouchers, debug dumps) lives under `data/`. Never write outside of it at runtime.
- Playwright selectors live in `selectors.py` exclusively. Keep flow modules (`tenbis_flow.py`, `whatsapp.py`) selector-free so UI churn is isolated to one file.
- Save a full-page screenshot + HTML dump to `data/debug/<timestamp>/` on any Playwright exception.
- Use `launch_persistent_context` (not `storage_state.json`) for all Playwright sessions. Persistent contexts survive IndexedDB-heavy apps like WhatsApp Web.

## Don'ts

- Never use: `from __future__ import annotations`.
- Avoid `if TYPE_CHECKING:` checks; most circular imports can be resolved without it.
- Do not commit `data/` or `.env`; both are in `.gitignore` and contain live session tokens.
- Do not add AWS, Telegram, or HTTPX dependencies — the whole point of this rewrite is Playwright-only, local operation.
- Do not auto-retry on auth failure; surface it as a clear error so the user runs `mise run login:tenbis` manually.
