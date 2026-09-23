from pathlib import Path

import duckdb
import pytest

from backend.migrations import migrate


def migration(directory: Path, name: str, source: str = "pass\n") -> Path:
    path = directory / name
    path.write_text(source, encoding="utf-8")
    return path


def test_unique_versions_are_sorted_numerically(tmp_path):
    migration(tmp_path, "010_tenth.py")
    migration(tmp_path, "002_second.py")
    migration(tmp_path, "001_first.py")
    assert [path.name for path in migrate.validate_migrations(tmp_path)] == [
        "001_first.py", "002_second.py", "010_tenth.py"
    ]


def test_duplicate_version_is_rejected(tmp_path):
    migration(tmp_path, "002_first.py")
    migration(tmp_path, "002_second.py")
    with pytest.raises(migrate.MigrationRegistryError, match="duplicate migration version 002"):
        migrate.validate_migrations(tmp_path)


@pytest.mark.parametrize("name", ["2_short.py", "ABC_invalid.py", "003-BAD.py", "004_.py"])
def test_malformed_filename_is_rejected(tmp_path, name):
    migration(tmp_path, name)
    with pytest.raises(migrate.MigrationRegistryError, match="invalid migration filename"):
        migrate.validate_migrations(tmp_path)


def test_invalid_registry_fails_before_database_mutation(tmp_path):
    database = tmp_path / "sentinel.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE TABLE sentinel(value INTEGER)")
        connection.execute("INSERT INTO sentinel VALUES (1)")

    migration(tmp_path, "001_first.py")
    migration(tmp_path, "001_duplicate.py")

    def destructive_runner(_path):
        with duckdb.connect(str(database)) as connection:
            connection.execute("DELETE FROM sentinel")

    with pytest.raises(migrate.MigrationRegistryError):
        migrate.execute_migrations(tmp_path, destructive_runner)
    with duckdb.connect(str(database)) as connection:
        assert connection.execute("SELECT value FROM sentinel").fetchall() == [(1,)]


def test_valid_migration_executes_on_temporary_database(tmp_path):
    database = tmp_path / "migration.duckdb"
    source = (
        "import duckdb\n"
        f"with duckdb.connect({str(database)!r}) as connection:\n"
        "    connection.execute('CREATE TABLE migrated(value INTEGER)')\n"
        "    connection.execute('INSERT INTO migrated VALUES (7)')\n"
    )
    migration(tmp_path, "001_create_fixture.py", source)
    migrate.execute_migrations(tmp_path)
    with duckdb.connect(str(database)) as connection:
        assert connection.execute("SELECT value FROM migrated").fetchall() == [(7,)]


def test_repository_legacy_exceptions_are_exact_and_registry_is_valid():
    migrations = migrate.validate_migrations(migrate.MIGRATIONS_DIR)
    names = {path.name for path in migrations}
    for allowed in migrate.LEGACY_DUPLICATE_VERSIONS.values():
        assert allowed <= names
