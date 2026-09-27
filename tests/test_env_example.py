import re
from pathlib import Path

from pydantic import AliasChoices

from api.config import Settings

ROOT = Path(__file__).resolve().parents[1]

ENV_ASSIGNMENT = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)\s*=")

CREDENTIAL_VARIABLES = {
    "SECRET_KEY",
    "ADMIN_PASSWORD",
    "DATABASE_URL",
    "TEST_DATABASE_URL",
}

PLACEHOLDER_MARKERS = ("PASSWORD", "PROJECT", "REGION")

DOCUMENTED_NOT_A_SETTING = {
    "TEST_DATABASE_URL": "read by the test suite, not by any Settings field",
}


def _env_example() -> str:
    return (ROOT / ".env.example").read_text(encoding="utf-8")


def _known_setting_env_names() -> set[str]:
    names = set()
    for field_name, field in Settings.model_fields.items():
        alias = field.validation_alias
        if alias is None:
            names.add(field_name.upper())
        elif isinstance(alias, AliasChoices):
            names.update(
                choice.upper() for choice in alias.choices if isinstance(choice, str)
            )
        else:
            names.add(str(alias).upper())
    return names


def _documented_env_names(text: str) -> set[str]:
    """Every variable name written down, commented out or not.

    A commented `NAME=` still documents the variable. It just refuses to hand a
    blank value to whoever copies the file, which is what an active `NAME=` does.
    """
    names = set()
    for line in text.splitlines():
        match = ENV_ASSIGNMENT.match(line.strip())
        if match:
            names.add(match.group(1))
    return names


def _active_assignments(text: str) -> list[tuple[str, str]]:
    """Every (name, value) a developer gets by copying this file verbatim.

    Blank values are included rather than filtered here, because which ones are
    wrong depends on the question being asked.
    """
    pairs = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, _, value = stripped.partition("=")
        pairs.append((name.strip(), value.strip()))
    return pairs


def test_env_example_documents_every_setting():
    """A setting nobody wrote down is a setting nobody can set correctly.

    The three schema names are the reason this matters: their env var names are
    `DB_SCHEMA_*` while the field names are `schema_*`, so nothing about the field
    declaration hints at the name an operator has to use.
    """
    missing = _known_setting_env_names() - _documented_env_names(_env_example())
    assert not missing, f"undocumented in .env.example: {sorted(missing)}"


def test_env_example_documents_no_name_the_app_ignores():
    """The other direction: a documented name the app never reads is a silent no-op.

    `model_config` sets `extra="ignore"`, so a typo here costs an operator a
    variable they set and nothing else. This is the check that catches it.
    """
    unknown = (
        _documented_env_names(_env_example())
        - _known_setting_env_names()
        - set(DOCUMENTED_NOT_A_SETTING)
    )
    assert not unknown, f"documented but not a setting: {sorted(unknown)}"


def test_the_non_setting_allowlist_only_names_documented_variables():
    """An allowlist entry for a name the file does not mention is dead weight.

    It hides the fact that the exception is no longer needed.
    """
    documented = _documented_env_names(_env_example())
    assert not set(DOCUMENTED_NOT_A_SETTING) - documented


def test_env_example_has_no_active_empty_value():
    """An active blank hands the next developer a silent weak configuration.

    `SECRET_KEY=` would reach the app as an empty key, which the boot guard at
    api/main.py does not catch because it only compares against the one literal
    default. Commented out, the line is documentation and nothing else.
    """
    blank = [
        name
        for name, value in _active_assignments(_env_example())
        if not value
    ]
    assert not blank, f"active but empty, comment these out instead: {sorted(blank)}"


def test_env_example_only_ever_shows_a_placeholder_credential():
    """A credential pasted here is a credential committed to git.

    It cannot tell a real secret from a placeholder that happens to avoid the
    marker words, and `CREDENTIAL_VARIABLES` is maintained by hand, so a newly
    added secret-bearing setting is not covered here until someone adds its name.
    """
    for name, value in _active_assignments(_env_example()):
        if name in CREDENTIAL_VARIABLES and value:
            assert any(marker in value.upper() for marker in PLACEHOLDER_MARKERS), (
                f"{name} is active in .env.example; keep it commented out or "
                f"replace the value with a placeholder"
            )
