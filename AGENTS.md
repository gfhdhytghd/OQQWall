# Repository Guidelines

This document orients contributors and agents working in this repo. Keep changes small, focused, and consistent with the existing scripts and layout.

## Project Structure & Modules
- `main.sh`: Orchestrator for services, QQ/NapCat, env, and DB.
- `getmsgserv/`: Inbound HTTP server and preprocessing (`serv.py`, shell helpers).
- `SendQzone/`: QZone automation and APIs (`qzone-serv-pipe.py`, cookies tooling).
- `Sendcontrol/`: Audit/approval loop (`sendcontrol.sh`).
- `qqBot/`: Bot utilities (daily like, friend approval).
- `cache/`, `logs/`: Runtime DB (`cache/OQQWall.db`), temp data, logs.
- `tests/`: NapCat POST recorder/replayer and local test server.

## Build, Test, and Development Commands
- Run locally: `bash main.sh` — creates/activates `venv`, installs deps, starts services.
- Restart subsystems: `bash main.sh -r` (force: `-rf`).
- Test mode: `bash main.sh --test` — skips QZone pipe; use test tools.
- Dev servers (manual): `python3 getmsgserv/serv.py`, `python3 SendQzone/qzone-serv-pipe.py`, `./Sendcontrol/sendcontrol.sh`.

## Coding Style & Naming Conventions
- Bash: lower_snake_case functions (e.g., `sendmsggroup`), 2–4 space indent, quote variables, prefer `$(...)`. Reuse helpers in `Global_toolkit.sh`.
- Python: PEP 8‑ish, 4‑space indent, `snake_case` names, small modules. Use stdlib first; keep deps minimal. Add docstrings for public functions.
- Config lives in `oqqwall.config` and `AcountGroupcfg.json` (both gitignored).

## Testing Guidelines
- Record real NapCat POSTs with `bash tests/start_recorder.sh` or `python3 tests/napcat_recorder.py --port 8083`.
- Replay against the app: `python3 tests/napcat_replayer.py --target http://localhost:8082`.
- Local sink: `python3 tests/test_server.py`. Store recordings in `tests/recordings/` as `session_YYYYMMDD_HHMMSS.json`.
- When changing message formats/endpoints, add a replay example to `tests/README.md` and verify end‑to‑end.

## LM Work Debugging
- Increase verbosity in `getmsgserv/LM_work/sendtoLM.py` by setting `get_logging_config()` level to `logging.DEBUG`.
- Sample run: `cat ./testmsg | python3 ./getmsgserv/LM_work/sendtoLM.py 50` (tag `50` persists to SQLite `preprocess`).
- Ensure `oqqwall.config` has a valid `apikey`; initialize tables via `bash main.sh`. Logs: console and `logs/sendtoLM_debug.log`.

## Commit & Pull Request Guidelines
- Commits: concise, descriptive titles (e.g., `fix(sendcontrol): handle empty queue`, `feat(qzone): auto-renew cookies`).
- PRs include purpose, scope of files touched, run instructions (e.g., `main.sh --test` steps), and screenshots/log snippets if UX/log output changed. Link related issues/wiki and note any config changes.

## Security & Configuration
- Never commit API keys, cookies, or QR codes.
- Validate `AcountGroupcfg.json` before run; `main.sh` performs schema checks and warns on conflicts.
- Default ports: app `8082`, recorder `8083`. Change thoughtfully to avoid clashes.

