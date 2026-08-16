# AGENTS.md — how to work in this repo

This file is read on **every** task. It is intentionally short: it defines *how you operate*,
not every coding rule. The detailed conventions live in `.agents/skills/` and load automatically
when relevant — follow them.

## Skills carry the "how"

Prefer the installed skills over guessing:

- Project structure, client/server API contract, and repo conventions → **catalog-service-conventions**
- FastAPI, Pydantic, Postgres, and React specifics → the matching framework skill

This file does not repeat those rules. It sets the operating loop below.

## Definition of done — non-negotiable

**A task is not complete until you have verified it.** After making any code change, and before you
tell the user the task is done:

1. Run the checks for whatever you touched (use judgment on scope — client, server, or both):
   - Client (`client/`): `npm run lint` and `npm run build`
   - Server (`server/`): `ruff check .`, `ruff format --check .`, and confirm `uvicorn main:app` boots
2. Fix every error and warning **you introduced**. Do not silence a check (ignore comments, disabling
   rules) just to make it pass.
3. Only then report completion — briefly state what changed and confirm the checks passed.

If a check fails on code you did not touch, flag it in your summary instead of silently fixing
unrelated things.

## Never write to a database — non-negotiable

**You must not execute statements that modify any database.** This includes, against every
environment (local, cloud, or otherwise):

- Schema changes: `CREATE`, `ALTER`, `DROP`, `TRUNCATE`, migrations of any kind.
- Data changes: `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `COPY ... FROM`.
- Any script, ORM call, or tool invocation whose effect is a write.

Read-only inspection (`SELECT`, `\d`, `EXPLAIN` without side effects) is allowed for verification.

When a task needs a schema or data change, **produce the SQL for a human to review and run** —
put it in the response (do not keep a `server/sql/` folder in the repo) and tell the user to apply
it themselves. Never apply it for them, even to "verify" your work. If you cannot verify without a
DB change, say so and stop.

## Operating principles (intent, not rigid scripts)

You have room to choose the best implementation — keep to the intent, not a fixed recipe:

- Make small, focused changes; one concern at a time.
- Add dependencies deliberately, never as a side effect of an unrelated task.
- Never commit secrets; configuration comes from environment variables.
- Work on a branch; never push directly to `main`.
