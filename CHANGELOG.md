# Changelog

## 0.3.0 — 2026-05-01

### Added
- `compute_signature()` and `signed_identity_headers()` accept optional
  keyword-only `user_id` and `display_name` kwargs. When both are provided,
  emit/expect the new 5-field canonical (`email|user_id|display_name|roles_sorted`).
- `current_user()` returns a dict with new keys `user_id` and `display_name`.
  In legacy 3-header mode, these fall back to safe sentinels
  (`user_id=0`, `display_name=email`) so consuming code can read them
  unconditionally.

### Backward-compatible
- Existing modules that pass only the legacy positional kwargs to
  `signed_identity_headers()` continue to emit the original 3-header set.
- `current_user()` accepts both header shapes from the platform shell during
  the auth-layer migration window. Once the shell is fully on 5-header
  emission, a future v0.4 will drop the legacy fallback.
