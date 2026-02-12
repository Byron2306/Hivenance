# Security & Integrity Hardening Notes

## Integrity checks executed
- `git fsck --full` completed without object integrity errors.
- Full Python compile checks executed to detect malformed/injected code.
- Backend and pytest suites executed after changes.

## Hardening changes applied
1. **Removed OpenClaw control surface from runtime decisioning**
   - Coordinator no longer initializes OpenClaw for autonomy decisions.
   - UI OpenClaw chat endpoint now returns `410 openclaw_removed`.
2. **Reduced public attack surface in backend CORS policy**
   - Replaced permissive wildcard CORS with explicit allowlist from `CORS_ALLOW_ORIGINS`.
   - Restricted methods and headers and disabled credentialed wildcard behavior.
3. **Secret hygiene improvement**
   - Removed hardcoded 1inch API key from `config/settings.yaml` and switched to env-driven key loading.
4. **Manual operator gate**
   - QUEEN Telegram trade approval remains fail-closed by default when enabled.

## Remaining critical risks to address next
- `config/api_keys.json` still exists in-repo and contains sensitive credentials. Move to external secret manager or local-only untracked file.
- Rotate any credentials that have ever been committed to git history.
- Add signed release process and dependency auditing (SCA) for CI.
- Add request rate limiting and auth for all control endpoints exposed by UI agent.
