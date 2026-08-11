# Borrowed Setup-Data Credentials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow Yandex Station to borrow credentials stored by the current Yandex Music guided setup flow without breaking legacy config-based instances.

**Architecture:** Add a small provider-local subclass of `BorrowedCredentialSource` that preserves the shared validation and legacy lookup, then falls back to the linked provider's public `get_setup_value()` API when legacy storage contains no tokens. Wire only Yandex Station's borrow-source factory to this adapter; Yandex Music remains the sole credential writer.

**Tech Stack:** Python 3.14, Music Assistant provider API, `ya-passport-auth[ma]`, pytest, Ruff, mypy, Docker Compose.

## Global Constraints

- Borrowing must remain read-only; Yandex Station must not persist or rotate the owner's credentials.
- Legacy `owner.config.get_value()` storage must continue to work.
- Missing or invalid linked providers must retain the shared library's existing errors.
- Docker networking is outside this fix; this task verifies credential bootstrap and entry into discovery only.

---

### Task 1: Setup-data-aware borrowed credential source

**Files:**
- Create: `provider/borrow.py`
- Modify: `provider/provider.py:13-20,292-303`
- Test: `tests/test_borrow_mode.py:32-117`

**Interfaces:**
- Consumes: `BorrowedCredentialSource.read_tokens() -> tuple[SecretStr | None, SecretStr | None]` and linked provider `get_setup_value(key: str, default: ConfigValueType = None) -> ConfigValueType`.
- Produces: `YandexMusicCredentialSource.read_tokens() -> tuple[SecretStr | None, SecretStr | None]`.

- [ ] **Step 1: Write the failing regression test**

Add a setup-data owner fixture and a second bootstrap test:

```python
def _ym_owner_setup_data(token: str | None, x_token: str | None) -> mock.MagicMock:
    owner = _ym_owner(None, None)
    owner.get_setup_value = lambda key, default=None: {
        "token": token,
        "x_token": x_token,
    }.get(key, default)
    return owner


async def test_builds_session_from_linked_setup_data_tokens(self) -> None:
    provider = _borrow_provider(_ym_owner_setup_data("test-music-ym", "test-x-ym"))
    with (
        mock.patch(f"{_MOD}.ClientSession") as http_cls,
        mock.patch(f"{_MOD}.PassportClient"),
        mock.patch(f"{_MOD}.YandexSession") as session_cls,
    ):
        http_cls.return_value = mock.MagicMock(closed=False, close=mock.AsyncMock())
        session_instance = mock.MagicMock()
        session_instance.login_token = mock.AsyncMock(return_value=True)
        session_cls.return_value = session_instance

        assert await provider._init_session() is True

    kwargs = session_cls.call_args.kwargs
    assert kwargs["x_token"].get_secret() == "test-x-ym"
    assert kwargs["music_token"].get_secret() == "test-music-ym"
    assert _updates(provider) == []
```

- [ ] **Step 2: Run the regression test and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_borrow_mode.py::TestBorrowInitSession::test_builds_session_from_linked_setup_data_tokens
```

Expected: FAIL with `Linked Yandex Music instance 'ym-1' has no credentials` because the shared source reads only `owner.config.get_value()`.

- [ ] **Step 3: Add the minimal compatibility adapter**

Create `provider/borrow.py`:

```python
"""Compatibility helpers for borrowing Yandex Music credentials."""

from __future__ import annotations

from typing import Any

from ya_passport_auth import SecretStr
from ya_passport_auth.ma import BorrowedCredentialSource


def _secret_or_none(value: object) -> SecretStr | None:
    """Return a non-empty value as a protected secret."""
    if isinstance(value, SecretStr):
        return value if value.get_secret() else None
    return SecretStr(str(value)) if value else None


class YandexMusicCredentialSource(BorrowedCredentialSource):
    """Read Yandex Music credentials from setup data with legacy fallback."""

    def __init__(self, mass: Any, instance_id: str) -> None:
        super().__init__(mass, instance_id)
        self._station_mass = mass

    def read_tokens(self) -> tuple[SecretStr | None, SecretStr | None]:
        """Return owner tokens from legacy config or guided setup data."""
        music_token, x_token = super().read_tokens()
        if music_token is not None or x_token is not None:
            return music_token, x_token

        owner = self._station_mass.get_provider(self.instance_id)
        get_setup_value = getattr(owner, "get_setup_value", None)
        if not callable(get_setup_value):
            return None, None
        return (
            _secret_or_none(get_setup_value("token")),
            _secret_or_none(get_setup_value("x_token")),
        )
```

In `provider/provider.py`, remove `BorrowedCredentialSource` from the shared imports, import `YandexMusicCredentialSource` from `.borrow`, change `_build_borrow_source`'s return type to `YandexMusicCredentialSource | None`, and construct `YandexMusicCredentialSource(self.mass, ym_instance)`.

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_borrow_mode.py tests/test_borrow_setup_data.py
```

Expected: all borrow tests pass, including both setup-data and legacy-config cases.

- [ ] **Step 5: Run repository verification**

Run:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check provider tests
.venv/bin/mypy provider tests
.venv/bin/pre-commit run --all-files
```

Expected: every command exits 0 with no test, lint, typing, or hook failures.

- [ ] **Step 6: Commit the bug fix**

```bash
git add provider/borrow.py provider/provider.py tests/test_borrow_mode.py docs/superpowers/plans/2026-08-11-borrowed-setup-data-credentials.md
git commit -m "fix(auth): read borrowed credentials from setup data"
```

### Task 2: Repository consistency and setup tooling

**Files:**
- Modify: `pyproject.toml`
- Modify: `provider/manifest.json`
- Modify: `uv.lock`
- Modify: `provider/setup_flow.py:180-257`
- Modify: `scripts/setup.sh:70-80`
- Create: `tests/test_project_consistency.py`

**Interfaces:**
- Consumes: runtime requirement strings from project metadata and typed setup-flow results.
- Produces: identical runtime dependency sets, strict-mypy-safe setup helpers, and safe standalone checkout recovery.

- [ ] **Step 1: Add and run a failing dependency consistency test**

Create `tests/test_project_consistency.py` to load `pyproject.toml` and
`provider/manifest.json`, then assert both runtime dependency sets equal
`{"ya-passport-auth[ma]==1.8.0", "segno==1.6.6"}`. Run the file and expect it
to fail because pyproject lacks segno and manifest still pins 1.7.0.

- [ ] **Step 2: Align dependencies and refresh the lock**

Add `segno==1.6.6` beside `ya-passport-auth[ma]==1.8.0` in pyproject, update
the manifest to the same two strings, then run `uv lock` and the consistency
test. Expected: the test passes and lock metadata contains both exact versions.

- [ ] **Step 3: Make setup-flow return types explicit**

Import `cast` from `typing`, cast both `session.progress_until(...)` results to
`Credentials`, and return `str(segno.make(...).svg_data_uri(...))` from
`_qr_image`. Run `.venv/bin/mypy provider/setup_flow.py`; expected: no errors.

- [ ] **Step 4: Recover only empty invalid standalone checkouts**

Before cloning, treat `ma-server/music_assistant` as the validity marker. If
the directory is invalid and empty, remove it with `rmdir` and clone. If it is
invalid and non-empty, exit with an actionable error without deleting content.
Re-run `./scripts/setup.sh`; expected: the current empty directory is safely
replaced rather than failing at `ln`.

- [ ] **Step 5: Run full repository gates**

Run pytest, Ruff, mypy, and pre-commit. Every command must exit 0.

### Task 3: Docker host-network runtime verification

**Files:**
- Modify: none
- Modify: `docker-compose.dev.yml`
- Test: validated Compose model, running environment, and logs

**Interfaces:**
- Consumes: the bind-mounted `provider/` directory and persisted `.ma-data` provider configuration.
- Produces: a running Music Assistant container whose Yandex Station provider passes borrowed credential bootstrap.

- [ ] **Step 1: Verify the old Compose model lacks host networking**

Run `docker compose -f docker-compose.dev.yml config` and confirm it contains
published port mappings but no `network_mode: host`.

- [ ] **Step 2: Switch the development service to host networking**

Add `network_mode: host` to the `ma` service and remove its `ports` block. Run
`docker compose -f docker-compose.dev.yml config`; expected: host networking is
present and no published port mappings remain.

- [ ] **Step 3: Recreate the container**

Run:

```bash
docker compose -f docker-compose.dev.yml up -d --force-recreate
```

Expected: `ma-provider-yandex-station-ma-1` is recreated and starts.

- [ ] **Step 4: Verify service and provider imports**

Run:

```bash
docker compose -f docker-compose.dev.yml ps
curl -fsS -o /tmp/yandex-station-ma-fixed.html -w '%{http_code}\n' http://127.0.0.1:8095/
docker compose -f docker-compose.dev.yml exec -T ma /app/venv/bin/python -c "import music_assistant.providers.yandex_station.borrow as b; print(b.__file__)"
```

Expected: container is `Up`, HTTP returns `200`, and `borrow.py` imports from the mounted provider.

- [ ] **Step 5: Verify the original runtime symptom is gone**

Run:

```bash
docker compose -f docker-compose.dev.yml logs --no-color --since=5m --tail=600 ma
```

Expected: no `has no credentials` exception for the linked Yandex Music instance. Logs show Yandex Station continuing into Quasar/Glagol discovery; any later mDNS or Docker publish-IP limitation is reported separately rather than attributed to authentication.
