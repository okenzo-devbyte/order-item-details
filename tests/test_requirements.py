import ast
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIPPED_DIRECTORY_PREFIXES = (".", "_")

SKIPPED_DIRECTORY_NAMES = {"build", "dist", "node_modules", "venv"}

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


def _is_skipped(name: str) -> bool:
    return name in SKIPPED_DIRECTORY_NAMES or name.startswith(SKIPPED_DIRECTORY_PREFIXES)


def _source_directories() -> list[Path]:
    """Top-level directories holding Python that this repository owns.

    Found by walking the root rather than listed, so a new source directory is
    covered without editing anything. Dotted, underscore, venv and build
    directories are skipped: they are not ours, they are usually untracked, and
    `.venv` on a developer machine would put its contents into the local-name set
    where a clean checkout has nothing, which is the kind of difference that only
    shows up on someone else's machine.
    """
    directories = []
    for entry in sorted(ROOT.iterdir()):
        if entry.is_dir() and not _is_skipped(entry.name) and any(entry.rglob("*.py")):
            directories.append(entry)
    return directories


def _python_files(directory: Path) -> list[Path]:
    files = []
    for parent, dirs, names in os.walk(directory):
        dirs[:] = [name for name in dirs if not _is_skipped(name)]
        files.extend(Path(parent) / name for name in sorted(names) if name.endswith(".py"))
    return files


def _local_top_level_names(source_dirs: list[Path]) -> set[str]:
    """Every top-level name that resolves to a file inside this repository.

    Derived from the same directories that are scanned for imports, so the two
    cannot drift apart. A directory counts when it holds any Python file, which
    covers real packages and also `scripts`, an implicit namespace package with no
    `__init__.py`.
    """
    names = set()
    for directory in source_dirs:
        names.add(directory.name)
        for entry in directory.iterdir():
            if entry.is_file() and entry.suffix == ".py" and entry.stem != "__init__":
                names.add(entry.stem)
            elif entry.is_dir() and not _is_skipped(entry.name) and any(entry.rglob("*.py")):
                names.add(entry.name)
    return names


def _declared_distributions() -> set[str]:
    names = set()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(
                re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].lower().replace("_", "-")
            )
    return names


def _imported_names_by_file(source_dirs: list[Path]) -> dict[str, set[str]]:
    imported: dict[str, set[str]] = {}
    for directory in source_dirs:
        for path in _python_files(directory):
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
    source_dirs = _source_directories()
    local = _local_top_level_names(source_dirs) | set(sys.stdlib_module_names)
    by_file: dict[str, set[str]] = {}
    everything: set[str] = set()
    for path, names in _imported_names_by_file(source_dirs).items():
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
