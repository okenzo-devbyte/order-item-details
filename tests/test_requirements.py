import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SOURCE_DIRS = ("api", "src", "scripts", "tests")

IMPORT_TO_DISTRIBUTION = {
    "argon2": "argon2-cffi",
    "jwt": "pyjwt",
    "pydantic_settings": "pydantic-settings",
}

DECLARED_NEVER_IMPORTED_BY_NAME = {
    "uvicorn": "run as a console script, never imported by the code",
    "httpx": "reached through fastapi.testclient.TestClient",
    "python-multipart": "FastAPI imports it implicitly to parse form data",
    "psycopg": "arrives with the Postgres pool, which no module imports yet",
}


def _declared_distributions() -> set[str]:
    names = set()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(
                re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].lower().replace("_", "-")
            )
    return names


def _local_top_level_names() -> set[str]:
    """Every top-level name that resolves to a file inside this repository.

    Derived from the tree rather than listed, so adding a local module does not
    turn these red until someone remembers to update a set. A directory counts
    when it holds any Python file, which covers real packages and also `scripts`,
    which is an implicit namespace package with no `__init__.py`.
    """
    names = set()
    for root in (ROOT, ROOT / "src", ROOT / "tests"):
        for entry in root.iterdir():
            if entry.is_dir() and any(entry.rglob("*.py")):
                names.add(entry.name)
            elif entry.suffix == ".py" and entry.stem != "__init__":
                names.add(entry.stem)
    return names


def _imported_names_by_file() -> dict[str, set[str]]:
    imported: dict[str, set[str]] = {}
    for folder in SOURCE_DIRS:
        for path in sorted((ROOT / folder).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        names.add(node.module.split(".")[0])
            imported[path.relative_to(ROOT).as_posix()] = names
    return imported


def _third_party_distributions() -> tuple[dict[str, set[str]], set[str]]:
    local = _local_top_level_names() | set(sys.stdlib_module_names)
    by_file: dict[str, set[str]] = {}
    everything: set[str] = set()
    for path, names in _imported_names_by_file().items():
        third_party = names - local
        by_file[path] = third_party
        everything.update(IMPORT_TO_DISTRIBUTION.get(name, name) for name in third_party)
    return by_file, everything


def test_every_imported_third_party_package_is_declared():
    """A declared dependency must outlive the code that imports it.

    Dropping a line while its importer still exists breaks a clean build, not the
    local venv, where the package stays installed and the mistake stays invisible.
    """
    declared = _declared_distributions()
    by_file, _ = _third_party_distributions()
    undeclared = {
        f"{distribution} (imported by {path})"
        for path, names in by_file.items()
        for name in names
        if (distribution := IMPORT_TO_DISTRIBUTION.get(name, name)) not in declared
    }
    assert not undeclared, f"undeclared imports: {sorted(undeclared)}"


def test_every_declared_package_is_imported():
    """The other direction: a declaration with no importer outlives its reason.

    Deleting the last module that used a package, without deleting the package,
    leaves a dependency nothing needs. It costs a slow build and a misleading
    claim about what the service depends on.
    """
    _, imported = _third_party_distributions()
    unused = _declared_distributions() - imported - set(DECLARED_NEVER_IMPORTED_BY_NAME)
    assert not unused, f"declared but never imported: {sorted(unused)}"


def test_the_allowlist_only_names_declared_packages():
    """An allowlist entry for a package nobody declares is dead weight.

    It hides the fact that the exception is no longer needed.
    """
    assert not set(DECLARED_NEVER_IMPORTED_BY_NAME) - _declared_distributions()
