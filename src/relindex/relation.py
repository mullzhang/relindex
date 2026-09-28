"""Immutable, named, finite relations for optimization indices."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from itertools import product
from operator import itemgetter
from types import MappingProxyType
from typing import Self, cast

type Scalar = int | str
type Row = tuple[Scalar, ...]


def _scalar_sort_key(value: Scalar) -> tuple[int, Scalar]:
    return (0 if type(value) is int else 1, value)


def _sort_key(row: Row) -> tuple[tuple[int, Scalar], ...]:
    return tuple(map(_scalar_sort_key, row))


def _validate_columns(columns: tuple[str, ...]) -> None:
    if not isinstance(columns, tuple):
        raise TypeError("Column names must be supplied as a tuple")
    if any(type(column) is not str or not column for column in columns):
        raise TypeError("Column names must be nonempty strings")
    if len(set(columns)) != len(columns):
        raise ValueError(f"Duplicate column names: {columns!r}")


def _key_function(positions: tuple[int, ...]) -> Callable[[Row], Row]:
    if not positions:
        return lambda row: ()
    if len(positions) == 1:
        position = positions[0]
        return lambda row: (row[position],)
    return cast(Callable[[Row], Row], itemgetter(*positions))


def _validate_value(value: Scalar) -> None:
    if type(value) not in (int, str):
        raise TypeError(f"Row values must be built-in int or str, got {value!r}")


@dataclass(frozen=True, slots=True, init=False)
class Relation:
    """A set of distinct tuples with an ordered tuple of column names.

    Values are exactly built-in ``int`` or ``str`` objects. All operations
    preserve set semantics and return new relations. Column order is part of
    the schema. Row order is canonical only when exporting with ``tuples``
    or grouping; internal operations do not depend on hash iteration order.
    """

    schema: tuple[str, ...]
    _rows: frozenset[Row] = field(repr=False)

    def __init__(self, rows: Iterable[Row], *, schema: tuple[str, ...]) -> None:
        _validate_columns(schema)
        distinct: set[Row] = set()
        for row in rows:
            if not isinstance(row, tuple):
                raise TypeError("Each row must be a tuple")
            if len(row) != len(schema):
                raise ValueError(
                    f"Expected {len(schema)} values for schema {schema!r}, got row {row!r}"
                )
            for value in row:
                _validate_value(value)
            distinct.add(tuple(row))
        object.__setattr__(self, "schema", tuple(schema))
        object.__setattr__(self, "_rows", frozenset(distinct))

    @classmethod
    def _from_validated_rows(cls, rows: Iterable[Row], *, schema: tuple[str, ...]) -> Self:
        """Freeze internal results whose labels, arity, and schema are already valid."""
        relation = object.__new__(cls)
        object.__setattr__(relation, "schema", schema)
        object.__setattr__(relation, "_rows", frozenset(rows))
        return relation

    @classmethod
    def from_mapping[Key: Scalar](
        cls, mapping: Mapping[Key, Iterable[Scalar]], *, key: str, value: str
    ) -> Self:
        """Import scalar keys and iterable values as distinct (key, value) rows.

        Each bucket is consumed once. Bare strings, bytes-like objects, and
        nested mappings are not buckets. Keys are validated even when their
        buckets are empty. Empty keys produce no rows: retain the complete
        key domain separately for ``to_mapping(over=...)``.
        """
        if not isinstance(mapping, Mapping):
            raise TypeError("Input must be a mapping of labels to iterables of labels")
        schema = (key, value)
        _validate_columns(schema)

        def rows() -> Iterable[Row]:
            for label, bucket in mapping.items():
                _validate_value(label)
                if isinstance(bucket, (str, bytes, bytearray, memoryview, Mapping)):
                    raise TypeError(
                        "Mapping values must be iterables of labels, "
                        "not strings, bytes-like objects, or mappings"
                    )
                for item in bucket:
                    _validate_value(item)
                    yield label, item

        return cls._from_validated_rows(rows(), schema=schema)

    def __len__(self) -> int:
        return len(self._rows)

    def __contains__(self, row: object) -> bool:
        if not isinstance(row, tuple) or len(row) != len(self.schema):
            return False
        if any(type(value) not in (int, str) for value in row):
            return False
        return row in self._rows

    def __repr__(self) -> str:
        return f"Relation(schema={self.schema!r}, size={len(self)})"

    def tuples(self) -> tuple[Row, ...]:
        """Export in lexicographic order, with integers before strings.

        Integers use numeric order and strings use Unicode order. The result
        is independent of input order and the Python hash seed. Export sorts
        the rows on each call; retain the returned tuple for repeated reuse.
        """
        return tuple(sorted(self._rows, key=_sort_key))

    def _positions(self, columns: tuple[str, ...]) -> tuple[int, ...]:
        _validate_columns(columns)
        unknown = tuple(column for column in columns if column not in self.schema)
        if unknown:
            raise ValueError(f"Unknown columns {unknown!r} in schema {self.schema!r}")
        return tuple(self.schema.index(column) for column in columns)

    def project(self, *columns: str) -> Relation:
        """Select and reorder columns, removing duplicate projected rows.

        A zero-column projection yields ``{()}`` for a nonempty relation and
        the empty relation for an empty input.
        """
        key = _key_function(self._positions(columns))
        return Relation._from_validated_rows(map(key, self._rows), schema=columns)

    def select(self, predicate: Callable[[Mapping[str, Scalar]], bool]) -> Relation:
        """Keep rows whose predicate returns True.

        Predicates receive read-only mappings in canonical row order. They
        must return a bool, and their exceptions propagate to the caller.
        """
        if not callable(predicate):
            raise TypeError("The selection predicate must be callable")
        selected = []
        for row in self.tuples():
            accepted = predicate(MappingProxyType(dict(zip(self.schema, row, strict=True))))
            if type(accepted) is not bool:
                raise TypeError("The selection predicate must return a bool")
            if accepted:
                selected.append(row)
        return Relation._from_validated_rows(selected, schema=self.schema)

    def rename(self, mapping: Mapping[str, str]) -> Relation:
        """Rename columns simultaneously; reject unknown or colliding names."""
        self._positions(tuple(mapping))
        schema = tuple(mapping[column] if column in mapping else column for column in self.schema)
        _validate_columns(schema)
        return Relation._from_validated_rows(self._rows, schema=schema)

    def _join_positions(
        self, other: Relation, on: tuple[str, ...]
    ) -> tuple[tuple[int, ...], tuple[int, ...]]:
        _validate_columns(on)
        if not on:
            raise ValueError("Join keys cannot be empty; use cross() for a Cartesian product")
        return self._positions(on), other._positions(on)

    def join(self, other: Relation, *, on: tuple[str, ...]) -> Relation:
        """Inner equijoin on explicit, same-named columns using a hash index.

        Output columns are the left schema followed by the right non-key
        columns. Non-key name collisions are errors; rename them explicitly.
        """
        left_positions, right_positions = self._join_positions(other, on)
        right_columns = tuple(column for column in other.schema if column not in on)
        collisions = tuple(column for column in right_columns if column in self.schema)
        if collisions:
            raise ValueError(f"Non-key columns collide: {collisions!r}; rename them before joining")
        payload_positions = other._positions(right_columns)
        left_key = _key_function(left_positions)
        right_key = _key_function(right_positions)
        payload = _key_function(payload_positions)
        index: dict[Row, list[Row]] = defaultdict(list)
        for row in other._rows:
            index[right_key(row)].append(payload(row))
        return Relation._from_validated_rows(
            (row + suffix for row in self._rows for suffix in index.get(left_key(row), ())),
            schema=self.schema + right_columns,
        )

    def _existence_join(self, other: Relation, on: tuple[str, ...], *, present: bool) -> Relation:
        left_positions, right_positions = self._join_positions(other, on)
        left_key = _key_function(left_positions)
        right_keys = set(map(_key_function(right_positions), other._rows))
        return Relation._from_validated_rows(
            (row for row in self._rows if (left_key(row) in right_keys) == present),
            schema=self.schema,
        )

    def semi_join(self, other: Relation, *, on: tuple[str, ...]) -> Relation:
        """Keep left rows having at least one matching right row."""
        return self._existence_join(other, on, present=True)

    def anti_join(self, other: Relation, *, on: tuple[str, ...]) -> Relation:
        """Keep left rows having no matching right row."""
        return self._existence_join(other, on, present=False)

    def _require_same_schema(self, other: Relation) -> None:
        if self.schema != other.schema:
            raise ValueError(f"Schemas must match exactly: {self.schema!r} != {other.schema!r}")

    def union(self, other: Relation) -> Relation:
        """Return rows present in either relation with the same schema."""
        self._require_same_schema(other)
        return Relation._from_validated_rows(self._rows | other._rows, schema=self.schema)

    def intersection(self, other: Relation) -> Relation:
        """Return rows present in both relations with the same schema."""
        self._require_same_schema(other)
        return Relation._from_validated_rows(self._rows & other._rows, schema=self.schema)

    def difference(self, other: Relation) -> Relation:
        """Return rows present only in the left relation."""
        self._require_same_schema(other)
        return Relation._from_validated_rows(self._rows - other._rows, schema=self.schema)

    def cross(self, other: Relation) -> Relation:
        """Cartesian product of relations with disjoint column names."""
        schema = self.schema + other.schema
        _validate_columns(schema)
        return Relation._from_validated_rows(
            (left + right for left, right in product(self._rows, other._rows)), schema=schema
        )

    def group_by(self, *columns: str, over: Relation) -> dict[Row, tuple[Row, ...]]:
        """Group complete rows over an explicit domain, including empty groups.

        Domain columns must equal the grouping columns in the same order.
        Any source key outside the domain raises ValueError. Both dictionary
        insertion order and rows within each group are canonical. The returned
        dictionary is an independent snapshot, not mutable relation storage.
        """
        if not columns:
            raise ValueError("At least one grouping column is required")
        group_key = _key_function(self._positions(columns))
        if over.schema != columns:
            raise ValueError(f"Group domain schema must be {columns!r}, got {over.schema!r}")
        groups: dict[Row, list[Row]] = {key: [] for key in over.tuples()}
        for row in self._rows:
            key = group_key(row)
            if key not in groups:
                raise ValueError(f"Group key {key!r} is outside the declared domain")
            groups[key].append(row)
        return {key: tuple(sorted(rows, key=_sort_key)) for key, rows in groups.items()}

    def to_mapping(
        self, *, key: str, value: str, over: Relation
    ) -> dict[Scalar, tuple[Scalar, ...]]:
        """Export one key column to distinct values over an explicit domain.

        Other columns are projected away. ``over`` must have schema ``(key,)``;
        its keys remain present even with no values. Source keys outside the
        domain are errors. Keys and values have canonical order, and the
        returned dictionary is an independent snapshot with tuple values.
        """
        key_position, value_position = self._positions((key, value))
        if over.schema != (key,):
            raise ValueError(f"Mapping domain schema must be {(key,)!r}, got {over.schema!r}")
        groups: dict[Scalar, set[Scalar]] = {label: set() for (label,) in over._rows}
        for row in self._rows:
            label = row[key_position]
            bucket = groups.get(label)
            if bucket is None:
                raise ValueError(f"Mapping key {label!r} is outside the declared domain")
            bucket.add(row[value_position])
        return {
            label: tuple(sorted(groups[label], key=_scalar_sort_key))
            for label in sorted(groups, key=_scalar_sort_key)
        }
