"""Small DuckDB helpers for name-based, validated relation writes."""
from __future__ import annotations

from collections.abc import Iterable, Sequence


class SchemaMismatchError(ValueError):
    """Raised before a write when source and target schemas are incompatible."""


def quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def relation_columns(connection, relation: str) -> list[str]:
    cursor = connection.execute(
        f"SELECT * FROM {quote_identifier(relation)} LIMIT 0"
    )
    return [description[0] for description in cursor.description]


def _validate_unique_columns(label: str, columns: Sequence[str]) -> None:
    duplicates = sorted({name for name in columns if columns.count(name) > 1})
    if duplicates:
        raise SchemaMismatchError(
            f"Schema mismatch for {label}: duplicate columns: {', '.join(duplicates)}"
        )


def create_table_from_relation(connection, target_table: str, source_relation: str) -> list[str]:
    """Create/replace a table using an explicit projection from a relation."""
    columns = relation_columns(connection, source_relation)
    _validate_unique_columns(target_table, columns)
    if not columns:
        raise SchemaMismatchError(f"Schema mismatch for {target_table}: source has no columns")
    projection = ", ".join(quote_identifier(column) for column in columns)
    connection.execute(
        f"CREATE OR REPLACE TABLE {quote_identifier(target_table)} AS "
        f"SELECT {projection} FROM {quote_identifier(source_relation)}"
    )
    return columns


def insert_relation_by_name(
    connection,
    target_table: str,
    source_relation: str,
    *,
    required_columns: Iterable[str] | None = None,
    optional_columns: Iterable[str] = (),
    ignored_source_columns: Iterable[str] = (),
) -> list[str]:
    """Validate schemas, then insert an explicit name-mapped projection.

    Required columns must exist in both relations. Optional target columns may
    be absent from the source and then receive their database default/NULL.
    Source-only columns are rejected unless the caller explicitly classifies
    them as safe helper fields.
    """
    target_columns = relation_columns(connection, target_table)
    source_columns = relation_columns(connection, source_relation)
    _validate_unique_columns(target_table, target_columns)
    _validate_unique_columns(source_relation, source_columns)

    optional = set(optional_columns)
    ignored = set(ignored_source_columns)
    required = set(required_columns) if required_columns is not None else set(target_columns) - optional

    missing_target = sorted(required - set(target_columns))
    if missing_target:
        raise SchemaMismatchError(
            f"Schema mismatch for {target_table}: target missing required columns: {', '.join(missing_target)}"
        )
    missing_source = sorted(required - set(source_columns))
    if missing_source:
        raise SchemaMismatchError(
            f"Schema mismatch for {target_table}: missing required columns: {', '.join(missing_source)}"
        )
    unexpected = sorted(set(source_columns) - set(target_columns) - ignored)
    if unexpected:
        raise SchemaMismatchError(
            f"Schema mismatch for {target_table}: unexpected source columns: {', '.join(unexpected)}"
        )

    insert_columns = [column for column in target_columns if column in source_columns]
    if not insert_columns:
        raise SchemaMismatchError(f"Schema mismatch for {target_table}: no compatible columns")
    names = ", ".join(quote_identifier(column) for column in insert_columns)
    connection.execute(
        f"INSERT INTO {quote_identifier(target_table)} ({names}) "
        f"SELECT {names} FROM {quote_identifier(source_relation)}"
    )
    return insert_columns
