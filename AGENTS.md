# Repository Guidelines

## Project Structure & Modules
- `main.sh`: Orchestrator. Boots services, manages QQ/NapCat, env, and DB.
- `getmsgserv/`: Inbound HTTP server and preprocessing (`serv.py`, shell helpers).
- `SendQzone/`: QZone automation and APIs (`qzone-serv-pipe.py`, cookies tooling).
- `Sendcontrol/`: Audit/approval loop (`sendcontrol.sh`).
- `qqBot/`: Bot utilities (e.g., daily like, friend approval).
- `cache/` and `logs/`: Runtime DB (`cache/OQQWall.db`), temp data, logs.
- `tests/`: NapCat POST recorder/replayer, local test server.

## Build, Test, and Dev Commands
- Run locally: `bash main.sh` (creates/activates `venv`, installs deps, starts services).
- Restart subsystems: `bash main.sh -r` (or force `-rf`).
- Test mode: `bash main.sh --test` (skips QZone pipe; use test tools below).
- Dev servers (manual): `python3 getmsgserv/serv.py`, `python3 SendQzone/qzone-serv-pipe.py`, `./Sendcontrol/sendcontrol.sh`.
- Test utilities:
  - Recorder: `bash tests/start_recorder.sh` or `python3 tests/napcat_recorder.py --port 8083`.
  - Replayer: `python3 tests/napcat_replayer.py --target http://localhost:8082`.
  - Local sink: `python3 tests/test_server.py`.

## Coding Style & Naming
- Bash: functions in `lower_snake_case` (e.g., `sendmsggroup`), 2–4 space indent, quote variables, prefer `$(...)` over backticks. Reuse helpers in `Global_toolkit.sh`.
- Python: PEP 8-ish, 4-space indent, `snake_case` names, small modules. Add docstrings for public functions. Keep dependencies minimal; leverage stdlib first.
- Files: co-locate scripts with their domain (see directories above). Config lives in `oqqwall.config` and `AcountGroupcfg.json` (both gitignored).

## Testing Guidelines
- Use `tests/` tools to record real NapCat POSTs and replay against `getmsgserv/serv.py`.
- Store recordings under `tests/recordings/` (already gitignored). Name sessions `session_YYYYMMDD_HHMMSS.json`.
- When changing message formats or endpoints, add a replay script example to `tests/README.md` and verify end-to-end with `tests/test_server.py` when applicable.

## LM Work Debugging
- Enable debug logs: in `getmsgserv/LM_work/sendtoLM.py`, set `get_logging_config()` level to `logging.DEBUG` (temporary change) to increase verbosity.
- Run with sample input: `cat ./testmsg | python3 ./getmsgserv/LM_work/sendtoLM.py 50` (`50` is the `tag` used to persist results in SQLite `preprocess`).
- Prereqs: ensure `oqqwall.config` has a valid `apikey`, and initialize tables once via `bash main.sh`.
- Logs: console and `logs/sendtoLM_debug.log` (rotating file handler).

## Commit & Pull Request Guidelines
- Commits are currently short and pragmatic (e.g., “more”, “fix”). Prefer concise, descriptive titles: `fix(sendcontrol): handle empty queue`, `feat(qzone): auto-renew cookies`.
- PRs must include: purpose, scope of files touched, run instructions (`main.sh --test` steps), and screenshots/log snippets if UX/log output changed.
- Link related issues or wiki pages. Note any config changes (`oqqwall.config`, `AcountGroupcfg.json`).

## Security & Configuration
- Never commit API keys, cookies, or QR codes (already excluded in `.gitignore`).
- Validate `AcountGroupcfg.json` before run; `main.sh` performs schema checks and will warn on conflicts.
- Default HTTP ports: app `8082`, recorder `8083`. Adjust thoughtfully to avoid clashes.
