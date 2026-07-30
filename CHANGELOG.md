# Changelog

## 1.6.1 — 2026-07-30

### Fixed
- **Breaking, corrects a v1.6.0 mistake before anyone adopted it:**
  `require_capability` / `require_any_capability` shipped in 1.6.0 as FastAPI
  dependency factories (`require_capability(cap) -> Callable`, used via
  `Depends(...)`), but the platform's published contract for module
  developers (`woodard-modules-workspace/docs/auth-and-deploy.md`, "Module
  capability gating") always specified an **imperative** call:
  `require_capability(request, capability) -> None`, called inline at the
  top of a route body and raising `HTTPException(403)` directly — not
  wired through `Depends(...)`. 1.6.0 shipped the wrong shape. Nothing
  outside this repo consumed 1.6.0 yet, so this corrects the signature now
  rather than after 16 module developers built against the (correct) docs.
  **Do not pin `woodard-module-helpers==1.6.0` — upgrade straight to 1.6.1.**
  New signatures:

  ```python
  def require_capability(request: Request, capability: str) -> None: ...
  def require_any_capability(request: Request, *capabilities: str) -> None: ...
  ```

  All 1.6.0 behaviour is preserved under the new call shape: the `admin`
  role and wildcard `"*"` capability both bypass the check, and a falsy or
  empty capability argument always denies (even for admin/`*`). No change
  to `current_user()`, `compute_capability_signature()`, the 5-header
  identity payload, or `compute_signature()`.
- The dependency-factory form was removed rather than kept alongside the
  imperative one under a different name. `require_role` /
  `require_any_role` keep the `Depends(...)` factory shape (they only ever
  need the injected `user` dict); capability checks need the raw `Request`
  to re-verify against `current_user`, and the documented contract already
  settled on calling them inline. Shipping both shapes in one library — one
  a factory, one imperative, for the same kind of check — is exactly the
  "two ways to do one thing" drift this fix exists to prevent.

## 1.6.0 — 2026-07-30

### Added
- Module-function capabilities (fine-grained grants under a module, e.g.
  `truman:enter`). Ride in their own header pair —
  `X-Woodard-Capabilities` / `X-Woodard-Capabilities-Signature` — with their
  own HMAC, so the existing 5-header identity payload and signature are
  completely unchanged. `compute_signature()`'s behaviour and payload are
  untouched.
- `current_user()` now returns an additional `capabilities: list[str]` key.
  Absent headers, a tampered signature, one capability header present
  without its counterpart, or a `WOODARD_SLUG` mismatch (or unset slug) all
  degrade to `capabilities: []` (logged as a warning) — the request still
  proceeds with identity intact, it just holds no capabilities.
  `ANONYMOUS_DEV` (no signing secret / local dev) gets `["*"]`, matching the
  existing wildcard-role convenience.
- `compute_capability_signature(email, user_id, module_slug, capabilities,
  secret)` — the capability-header analog of `compute_signature`. The
  payload is bound to `email`, `user_id`, AND `module_slug`
  (`f"{email}:{user_id}:{module_slug}:{capabilities_csv}"`, `capabilities_csv`
  sorted) so a capabilities header captured from one user's request cannot
  be replayed alongside a different user's identity headers, and a header
  minted for one module cannot be replayed at another. `module_slug` is
  read from the module's own `WOODARD_SLUG` env var during verification —
  a module never has to be told which module it is.
- `require_capability(cap)` / `require_any_capability(*caps)` — FastAPI
  dependencies mirroring `require_role` / `require_any_role`. The dev
  wildcard `"*"` and the platform `admin` role both bypass the check
  (admins bypass capability gates per the platform's access model — modules
  don't need to re-derive this). A falsy/empty capability argument always
  denies, even for admin or `*` callers.

### Backward-compatible
- No change to the 5-header (or legacy 3-header) identity payload or to
  `compute_signature()`. A module pinned to 1.5.0 that upgrades to 1.6.0
  without touching its code sees identical behaviour — the only difference
  is one additional dict key it never reads.
- A module that sends no capability headers gets `capabilities: []` and
  nothing else changes.

## 1.5.0 — 2026-07-15
- `load_config()`: fetch merged tunable config (config.yaml defaults +
  dev-hub overrides) from the shell at startup; fail-open to local defaults.
- `Settings.shell_url` (env `SHELL_URL`), default `http://127.0.0.1:8080`.

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
