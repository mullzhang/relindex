"""Examples and boundary conditions for the public relation contract."""

import os
import subprocess
import sys
from dataclasses import FrozenInstanceError

import pytest

from relindex import Relation


def test_set_semantics_and_canonical_export():
    relation = Relation([(2, "b"), (1, "a"), (2, "b")], schema=("id", "label"))
    assert len(relation) == 2
    assert relation.tuples() == ((1, "a"), (2, "b"))
    assert (1, "a") in relation
    assert (3, "a") not in relation
    assert relation == Relation(reversed(relation.tuples()), schema=relation.schema)
    assert hash(relation) == hash(Relation(relation.tuples(), schema=relation.schema))
    assert repr(relation) == "Relation(schema=('id', 'label'), size=2)"


def test_mixed_label_order_is_numeric_then_unicode():
    relation = Relation([("2",), (10,), ("a",), (-2,), ("10",), (2,)], schema=("id",))
    assert relation.tuples() == ((-2,), (2,), (10,), ("10",), ("2",), ("a",))


def test_freezes_input_and_exposes_no_mutable_storage():
    rows = [(1,)]
    relation = Relation(rows, schema=("id",))
    rows.append((2,))
    assert relation.tuples() == ((1,),)
    with pytest.raises(FrozenInstanceError):
        relation.schema = ("changed",)
    with pytest.raises(FrozenInstanceError):
        relation._rows = frozenset()


@pytest.mark.parametrize("bad", [True, 1.0, None, float("nan"), [], {}, (1,)])
def test_rejects_non_label_values(bad):
    with pytest.raises(TypeError, match="built-in int or str"):
        Relation([(bad,)], schema=("id",))


def test_rejects_label_subclasses():
    class Identifier(int):
        pass

    with pytest.raises(TypeError, match="built-in int or str"):
        Relation([(Identifier(1),)], schema=("id",))


@pytest.mark.parametrize("bad", [(True,), (1.0,), (None,), ([1],), [1], "1", ()])
def test_membership_does_not_coerce_or_accept_unhashable_values(bad):
    assert bad not in Relation([(1,)], schema=("id",))


@pytest.mark.parametrize("schema", ["id", ["id"], (1,), ("",), (None,)])
def test_rejects_invalid_schema_even_without_rows(schema):
    with pytest.raises(TypeError):
        Relation([], schema=schema)


def test_rejects_duplicate_columns_and_ragged_rows():
    with pytest.raises(ValueError, match="Duplicate"):
        Relation([], schema=("id", "id"))
    with pytest.raises(ValueError, match="Expected 2 values"):
        Relation([(1,)], schema=("a", "b"))
    with pytest.raises(TypeError, match="row must be a tuple"):
        Relation([[1]], schema=("id",))


def test_projection_is_a_set_and_can_reorder_columns():
    relation = Relation([(1, "a"), (1, "b"), (2, "b")], schema=("id", "label"))
    assert relation.project("id").tuples() == ((1,), (2,))
    assert relation.project("label", "id").tuples() == (("a", 1), ("b", 1), ("b", 2))
    assert relation.schema == ("id", "label")


def test_zero_arity_relations_and_empty_projection():
    empty = Relation([], schema=("id",)).project()
    truth = Relation([(1,), (2,)], schema=("id",)).project()
    assert empty.schema == truth.schema == ()
    assert empty.tuples() == ()
    assert truth.tuples() == ((),)
    value = Relation([(3,)], schema=("id",))
    assert truth.cross(value) == value
    assert value.cross(truth) == value
    assert empty.cross(value) == Relation([], schema=("id",))


def test_selection_uses_read_only_named_rows_and_canonical_order():
    relation = Relation([(2, "b"), (1, "a")], schema=("id", "label"))
    visited = []

    def predicate(row):
        visited.append(row["id"])
        with pytest.raises(TypeError):
            row["id"] = 0
        return row["label"] == "b"

    assert relation.select(predicate).tuples() == ((2, "b"),)
    assert visited == [1, 2]
    with pytest.raises(TypeError, match="return a bool"):
        relation.select(lambda row: 1)
    with pytest.raises(KeyError):
        relation.select(lambda row: row["missing"] == 1)
    with pytest.raises(TypeError, match="callable"):
        Relation([], schema=("id",)).select(None)


def test_rename_is_simultaneous_and_validates_empty_inputs():
    relation = Relation([(1, 2)], schema=("left", "right"))
    swapped = relation.rename({"left": "right", "right": "left"})
    assert swapped.schema == ("right", "left")
    assert swapped.tuples() == ((1, 2),)
    assert relation.rename({}) == relation
    with pytest.raises(ValueError, match="Duplicate"):
        relation.rename({"left": "right"})
    with pytest.raises(ValueError, match="Unknown"):
        Relation([], schema=("id",)).rename({"missing": "new"})
    with pytest.raises(TypeError, match="nonempty"):
        relation.rename({"left": ""})


def test_join_uses_multiple_explicit_keys_and_preserves_column_order():
    left = Relation([(1, 2, "a"), (1, 3, "b")], schema=("id", "period", "left"))
    right = Relation([(2, "x", 1), (2, "y", 1), (9, "z", 1)], schema=("period", "right", "id"))
    result = left.join(right, on=("period", "id"))
    assert result.schema == ("id", "period", "left", "right")
    assert result.tuples() == ((1, 2, "a", "x"), (1, 2, "a", "y"))
    assert left.semi_join(right, on=("id", "period")).tuples() == ((1, 2, "a"),)
    assert left.anti_join(right, on=("id", "period")).tuples() == ((1, 3, "b"),)


def test_join_all_columns_matches_intersection():
    left = Relation([(1, "x"), (2, "y")], schema=("a", "b"))
    right = Relation([("x", 1)], schema=("b", "a"))
    assert left.join(right, on=("a", "b")).tuples() == ((1, "x"),)


@pytest.mark.parametrize("method", ["join", "semi_join", "anti_join"])
@pytest.mark.parametrize("on", [(), ("missing",), ("id", "id")])
def test_invalid_join_keys_fail_even_for_empty_inputs(method, on):
    relation = Relation([], schema=("id",))
    with pytest.raises(ValueError):
        getattr(relation, method)(relation, on=on)


def test_join_name_collisions_and_unequal_label_types():
    relation = Relation([], schema=("id", "value"))
    with pytest.raises(ValueError, match="Non-key columns collide"):
        relation.join(relation, on=("id",))
    assert relation.semi_join(relation, on=("id",)) == relation
    with pytest.raises(TypeError, match="tuple"):
        relation.join(relation, on="id")
    assert not Relation([(1,)], schema=("id",)).join(Relation([("1",)], schema=("id",)), on=("id",))


@pytest.mark.parametrize("method", ["union", "intersection", "difference"])
def test_set_operations_require_exact_schema_even_when_empty(method):
    left = Relation([], schema=("a", "b"))
    right = Relation([], schema=("b", "a"))
    with pytest.raises(ValueError, match="Schemas must match"):
        getattr(left, method)(right)


def test_cross_has_explicit_names_and_empty_schema():
    left = Relation([(1,), (2,)], schema=("origin",))
    right = Relation([("a",), ("b",)], schema=("destination",))
    assert left.cross(right).tuples() == ((1, "a"), (1, "b"), (2, "a"), (2, "b"))
    assert left.cross(Relation([], schema=("destination",))).schema == ("origin", "destination")
    with pytest.raises(ValueError, match="Duplicate"):
        left.cross(left)


def test_grouping_retains_empty_targets_and_full_keys():
    relation = Relation([("b", 2), ("a", 1), ("b", 1)], schema=("worker", "task"))
    tasks = Relation([(3,), (2,), (1,)], schema=("task",))
    groups = relation.group_by("task", over=tasks)
    assert list(groups) == [(1,), (2,), (3,)]
    assert groups == {(1,): (("a", 1), ("b", 1)), (2,): (("b", 2),), (3,): ()}
    groups[(1,)] = ()
    assert len(relation) == 3
    assert relation.group_by("task", over=tasks)[(1,)] == (("a", 1), ("b", 1))


def test_grouping_with_composite_domain_and_empty_source():
    domain = Relation([(1, "x"), (1, "y")], schema=("period", "site"))
    relation = Relation([(4, "x", 1)], schema=("worker", "site", "period"))
    assert relation.group_by("period", "site", over=domain) == {
        (1, "x"): ((4, "x", 1),),
        (1, "y"): (),
    }
    assert Relation([], schema=("site", "period")).group_by("period", "site", over=domain) == {
        (1, "x"): (),
        (1, "y"): (),
    }


def test_grouping_rejects_missing_domain_keys_and_invalid_columns():
    relation = Relation([(1, 2)], schema=("a", "b"))
    with pytest.raises(ValueError, match="outside the declared domain"):
        relation.group_by("a", over=Relation([], schema=("a",)))
    with pytest.raises(ValueError, match="domain schema"):
        relation.group_by("a", over=Relation([], schema=("b",)))
    with pytest.raises(ValueError, match="At least one"):
        relation.group_by(over=Relation([()], schema=()))
    with pytest.raises(ValueError, match="Unknown"):
        relation.group_by("missing", over=Relation([], schema=("missing",)))
    with pytest.raises(ValueError, match="Duplicate"):
        relation.project("a", "a")
    with pytest.raises(ValueError, match="Unknown"):
        Relation([], schema=("a",)).project("missing")


def test_exports_do_not_depend_on_hash_seed():
    script = """
from relindex import Relation
r = Relation({('b', 1), ('a', 2), ('a', 1)}, schema=('label', 'id'))
d = Relation({(3,), (1,), (2,)}, schema=('id',))
print(r.tuples(), r.group_by('id', over=d))
"""
    outputs = [
        subprocess.check_output(
            [sys.executable, "-c", script],
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
            text=True,
        )
        for seed in (0, 1, 42)
    ]
    assert outputs[0] == outputs[1] == outputs[2]
