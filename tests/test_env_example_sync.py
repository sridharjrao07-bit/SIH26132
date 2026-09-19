"""Guard: ``.env.example`` and ``Settings`` must not drift apart.

An operator who copies ``.env.example`` and fills it in must end up with a
configuration ``Settings`` accepts completely; conversely, every key the
example documents must map to a real field, or the example teaches people to
set variables that silently do nothing.  Both directions are cheap to check
and expensive to discover in production, so both are asserted here.
"""

from pathlib import Path

from app.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"

# Env vars intentionally documented in .env.example but read directly by tests
# or tooling rather than via Settings.  Empty today; extend with a reason.
NON_SETTINGS_KEYS = frozenset()


def _example_keys() -> set:
    keys = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0].strip())
    return keys


def _settings_env_names() -> set:
    # config.py forbids Field(alias=...), so the env name is the field name
    # upper-cased (SUPABASE_URL -> supabase_url).  Keep that invariant in mind
    # if aliases are ever introduced: this guard would need updating.
    return {name.upper() for name in Settings.model_fields}


def test_every_settings_field_is_documented_in_env_example():
    missing = _settings_env_names() - _example_keys()
    assert not missing, (
        f"Settings fields with no .env.example entry: {sorted(missing)}. "
        "Add them (with a commented default) or operators miss required config."
    )


def test_env_example_documents_no_dead_keys():
    stale = _example_keys() - _settings_env_names() - NON_SETTINGS_KEYS
    assert not stale, (
        f".env.example keys with no Settings field: {sorted(stale)}. Either the "
        "field was renamed/removed (delete the key) or it is a test-only toggle "
        "(add it to NON_SETTINGS_KEYS with a reason)."
    )
