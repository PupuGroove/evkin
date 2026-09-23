"""Validate and execute EVKIN migration scripts in numeric-version order."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable

MIGRATIONS_DIR = Path(__file__).resolve().parent
MIGRATION_PATTERN = re.compile(r"^(?P<version>\d{3})_[a-z0-9][a-z0-9_]*\.py$")

# These are operator/developer tools, not schema migrations. New helpers should
# live outside this directory instead of broadening this exception list.
NON_MIGRATION_FILES = frozenset({
    "migrate.py",
    "check_counts.py",
    "inspect_sqlite_schema.py",
})

# These collisions predate the validator and are imported by their exact file
# names in existing deployments. Renaming them could make historical state
# ambiguous. Only these exact pairs are allowed; any additional collision fails.
LEGACY_DUPLICATE_VERSIONS = {
    2: frozenset({"002_apply_no_backup.py", "002_migrate_old_evkin.py"}),
    37: frozenset({
        "037_create_skp_indicator_governance.py",
        "037_create_temporary_sdm_assignment.py",
    }),
}


class MigrationRegistryError(ValueError):
    """Raised before execution when migration filenames are ambiguous."""


def validate_migrations(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    """Return validated migrations sorted by numeric version then filename."""
    directory = Path(directory)
    versioned: list[tuple[int, Path]] = []
    invalid: list[str] = []
    grouped: dict[int, list[Path]] = defaultdict(list)

    for path in directory.iterdir():
        if not path.is_file() or path.suffix != ".py" or path.name in NON_MIGRATION_FILES:
            continue
        match = MIGRATION_PATTERN.fullmatch(path.name)
        if match is None:
            invalid.append(path.name)
            continue
        version = int(match.group("version"))
        versioned.append((version, path))
        grouped[version].append(path)

    errors: list[str] = []
    if invalid:
        errors.append("invalid migration filename(s): " + ", ".join(sorted(invalid)))
    for version, paths in sorted(grouped.items()):
        names = frozenset(path.name for path in paths)
        if len(names) > 1 and names != LEGACY_DUPLICATE_VERSIONS.get(version):
            errors.append(
                f"duplicate migration version {version:03d}: " + ", ".join(sorted(names))
            )
    if errors:
        raise MigrationRegistryError("; ".join(errors))

    return [path for _, path in sorted(versioned, key=lambda item: (item[0], item[1].name))]


def find_migrations() -> list[Path]:
    """Backward-compatible alias used by existing operator scripts."""
    return validate_migrations(MIGRATIONS_DIR)


def run_migration(path: Path) -> None:
    print(f"Running migration: {path.name}")
    result = subprocess.run([sys.executable, str(path)], check=False)
    if result.returncode != 0:
        raise SystemExit(f"Migration {path.name} failed with exit code {result.returncode}")


def execute_migrations(
    directory: Path = MIGRATIONS_DIR,
    runner: Callable[[Path], None] = run_migration,
) -> list[Path]:
    """Validate the complete registry before executing the first migration."""
    migrations = validate_migrations(directory)
    for migration in migrations:
        runner(migration)
    return migrations


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate names, versions and ordering without running migrations",
    )
    args = parser.parse_args(argv)
    migrations = validate_migrations(MIGRATIONS_DIR)
    if args.validate_only:
        print(f"Migration registry valid: {len(migrations)} file(s)")
        return
    if not migrations:
        print("No migrations found")
        return
    for migration in migrations:
        run_migration(migration)
    print("All migrations executed")


if __name__ == "__main__":
    main()
