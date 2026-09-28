"""Dictionary boundaries, domains, and independent conversion specifications."""

import os
import subprocess
import sys
from types import MappingProxyType

import pytest
from hypothesis import given
from hypothesis import strategies as st

from relindex import Relation


def test_import_copies_buckets_and_keeps_set_semantics():
    source = {"t1": ["bob", "alice", "bob"], "t2": []}
    relation = Relation.from_mapping(source, key="task", value="worker")
    source["t1"].append("carol")
    source["t3"] = ["dave"]
    assert relation.schema == ("task", "worker")
    assert relation.tuples() == (("t1", "alice"), ("t1", "bob"))
    assert relation.project("task").tuples() == (("t1",),)
    assert relation == Relation(relation.tuples(), schema=relation.schema)


def test_import_accepts_mappings_and_consumes_each_bucket_once():
    class Once:
        def __init__(self):
            self.visited = False

        def __iter__(self):
            assert not self.visited
            self.visited = True
            yield "alice"
            yield "bob"

    source = MappingProxyType({"a": Once(), "b": {1, 2}, "c": (x for x in ["z", "z"])})
    assert Relation.from_mapping(source, key="task", value="worker").tuples() == (
        ("a", "alice"),
        ("a", "bob"),
        ("b", 1),
        ("b", 2),
        ("c", "z"),
    )


@pytest.mark.parametrize("source", [[], [("a", [1])], None, "abc"])
def test_import_requires_a_mapping(source):
    with pytest.raises(TypeError, match="mapping"):
        Relation.from_mapping(source, key="task", value="worker")


@pytest.mark.parametrize(
    "bucket", ["alice", b"abc", bytearray(b"a"), memoryview(b"a"), {}, 1, None]
)
def test_rejects_ambiguous_or_non_iterable_buckets(bucket):
    with pytest.raises(TypeError):
        Relation.from_mapping({"a": bucket}, key="task", value="worker")


class IntLabel(int):
    pass


class StrLabel(str):
    pass


@pytest.mark.parametrize("bad", [True, None, 1.5, (1,), IntLabel(1), StrLabel("a")])
def test_checks_keys_even_when_the_bucket_is_empty(bad):
    with pytest.raises(TypeError, match="built-in int or str"):
        Relation.from_mapping({bad: []}, key="task", value="worker")


@pytest.mark.parametrize("bad", [True, None, 1.5, [], {}, (1,), IntLabel(1), StrLabel("a")])
def test_checks_each_value_label(bad):
    with pytest.raises(TypeError, match="built-in int or str"):
        Relation.from_mapping({"a": [bad]}, key="task", value="worker")


def test_input_iterator_errors_propagate():
    def broken_bucket():
        yield "valid"
        raise RuntimeError("Source failed")

    with pytest.raises(RuntimeError, match="Source failed"):
        Relation.from_mapping({"a": broken_bucket()}, key="task", value="worker")


@pytest.mark.parametrize("key,value", [("task", "task"), ("", "worker"), ("task", None)])
def test_checks_column_names_on_empty_mapping_inputs_and_outputs(key, value):
    with pytest.raises((TypeError, ValueError)):
        Relation.from_mapping({}, key=key, value=value)
    with pytest.raises((TypeError, ValueError)):
        Relation([], schema=("task", "worker")).to_mapping(
            key=key, value=value, over=Relation([], schema=("task",))
        )


def test_export_projects_distinct_values_and_orders_both_axes():
    relation = Relation(
        [("2", "t", 1), (2, "t", 2), (2, "t", 3), (10, 1, 4), (-1, 1, 5)],
        schema=("worker", "task", "period"),
    )
    domain = Relation([("t",), ("empty",), (1,)], schema=("task",))
    result = relation.to_mapping(key="task", value="worker", over=domain)
    assert list(result.items()) == [(1, (-1, 10)), ("empty", ()), ("t", (2, "2"))]
    result["t"] = ()
    del result[1]
    assert len(relation) == 5
    assert relation.to_mapping(key="task", value="worker", over=domain)["t"] == (2, "2")


def test_export_requires_the_full_domain_and_preserves_empty_keys():
    relation = Relation.from_mapping({"t1": [], "t2": [1]}, key="task", value="worker")
    domain = Relation([("t1",), ("t2",), ("t3",)], schema=("task",))
    assert relation.to_mapping(key="task", value="worker", over=domain) == {
        "t1": (),
        "t2": (1,),
        "t3": (),
    }
    with pytest.raises(ValueError, match="outside the declared domain"):
        relation.to_mapping(
            key="task", value="worker", over=domain.select(lambda r: r["task"] != "t2")
        )
    with pytest.raises(TypeError):
        relation.to_mapping(key="task", value="worker")


@pytest.mark.parametrize("schema", [("worker",), ("task", "other"), ()])
def test_export_checks_domain_schema_even_without_rows(schema):
    with pytest.raises(ValueError, match="domain schema"):
        Relation([], schema=("task", "worker")).to_mapping(
            key="task", value="worker", over=Relation([], schema=schema)
        )


def test_export_checks_unknown_columns_even_without_rows():
    with pytest.raises(ValueError, match="Unknown"):
        Relation([], schema=("task", "worker")).to_mapping(
            key="task", value="missing", over=Relation([], schema=("task",))
        )


def test_empty_and_all_empty_inputs_retain_only_the_explicit_domain():
    domain = Relation([("a",), ("b",)], schema=("task",))
    for source in ({}, {"a": [], "b": []}):
        relation = Relation.from_mapping(source, key="task", value="worker")
        assert relation.schema == ("task", "worker")
        assert relation.tuples() == ()
        assert relation.to_mapping(key="task", value="worker", over=domain) == {"a": (), "b": ()}
        assert (
            relation.to_mapping(key="task", value="worker", over=Relation([], schema=("task",)))
            == {}
        )


labels = st.one_of(st.integers(-3, 3), st.sampled_from(["", "1", "a", "b"]))


def label_order(value):
    return (0 if type(value) is int else 1, value)


@given(st.dictionaries(labels, st.lists(labels, max_size=8), max_size=8), st.sets(labels))
def test_round_trip_matches_an_independent_dictionary_specification(source, extra_keys):
    relation = Relation.from_mapping(source, key="task", value="worker")
    domain_keys = set(source) | extra_keys
    domain = Relation(((k,) for k in domain_keys), schema=("task",))
    expected = {
        k: tuple(sorted(set(source.get(k, [])), key=label_order))
        for k in sorted(domain_keys, key=label_order)
    }
    assert set(relation.tuples()) == {(k, v) for k, values in source.items() for v in values}
    assert list(relation.to_mapping(key="task", value="worker", over=domain).items()) == list(
        expected.items()
    )


@given(st.sets(st.tuples(labels, labels, labels)))
def test_wide_projection_matches_a_direct_specification(rows):
    relation = Relation(rows, schema=("worker", "period", "task"))
    keys = {task for _, _, task in rows}
    domain = Relation(((k,) for k in keys), schema=("task",))
    expected = {
        k: tuple(sorted({worker for worker, _, task in rows if task == k}, key=label_order))
        for k in sorted(keys, key=label_order)
    }
    assert list(relation.to_mapping(key="task", value="worker", over=domain).items()) == list(
        expected.items()
    )


@given(st.sets(st.tuples(labels, labels, labels)))
def test_full_row_grouping_keeps_composite_keys_and_canonical_order(rows):
    relation = Relation(rows, schema=("worker", "period", "task"))
    keys = {(t, w) for w, _, t in rows} | {("empty", "worker")}
    domain = Relation(keys, schema=("task", "worker"))
    expected = {
        (task, worker): tuple(
            sorted(
                (row for row in rows if row[0] == worker and row[2] == task),
                key=lambda row: tuple(map(label_order, row)),
            )
        )
        for task, worker in sorted(keys, key=lambda row: tuple(map(label_order, row)))
    }
    assert list(relation.group_by("task", "worker", over=domain).items()) == list(expected.items())


def test_dictionary_export_is_independent_of_hash_seed():
    code = """
from relindex import Relation
r = Relation.from_mapping({k: {'z', 'a', 2} for k in {'t2', 't1'}}, key='t', value='w')
d = Relation([(k,) for k in {'t1', 'empty', 't2'}], schema=('t',))
print(r.to_mapping(key='t', value='w', over=d))
"""
    outputs = [
        subprocess.check_output(
            [sys.executable, "-c", code], env={**os.environ, "PYTHONHASHSEED": seed}, text=True
        )
        for seed in ("0", "1", "42")
    ]
    assert len(set(outputs)) == 1
