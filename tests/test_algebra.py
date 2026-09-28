"""Check algebra against independent finite-set specifications."""

from itertools import product

from hypothesis import given, settings
from hypothesis import strategies as st

from relindex import Relation

pair_sets = st.sets(st.tuples(st.integers(0, 4), st.integers(0, 4)))


@given(pair_sets, pair_sets)
def test_set_algebra_matches_python_sets(left, right):
    a, b = Relation(left, schema=("x", "y")), Relation(right, schema=("x", "y"))
    assert set(a.union(b).tuples()) == left | right
    assert set(a.intersection(b).tuples()) == left & right
    assert set(a.difference(b).tuples()) == left - right
    assert a.union(b) == b.union(a)
    assert a.union(a) == a
    assert a.difference(a) == Relation([], schema=a.schema)
    assert a.project("x").tuples() == tuple((x,) for x in sorted({x for x, _ in left}))


@given(pair_sets, pair_sets)
def test_hash_joins_match_existential_specifications(left, right):
    a = Relation(left, schema=("x", "key"))
    b = Relation(right, schema=("key", "z"))
    expected = {(x, k, z) for x, k in left for j, z in right if k == j}
    assert set(a.join(b, on=("key",)).tuples()) == expected
    matches = {row for row in left if any(row[1] == key for key, _ in right)}
    assert set(a.semi_join(b, on=("key",)).tuples()) == matches
    assert set(a.anti_join(b, on=("key",)).tuples()) == left - matches
    assert a.semi_join(b, on=("key",)).union(a.anti_join(b, on=("key",))) == a


@given(pair_sets, pair_sets, pair_sets, pair_sets)
@settings(max_examples=150)
def test_all_required_skills_matches_universal_quantification(candidates, has, requires, forbidden):
    c = Relation(candidates, schema=("worker", "task"))
    h = Relation(has, schema=("worker", "skill"))
    q = Relation(requires, schema=("task", "skill"))
    f = Relation(forbidden, schema=("worker", "task"))
    missing = c.join(q, on=("task",)).anti_join(h, on=("worker", "skill")).project("worker", "task")
    result = c.difference(missing).difference(f)
    expected = {
        (w, t)
        for w, t in candidates
        if all((w, s) in has for task, s in requires if task == t) and (w, t) not in forbidden
    }
    assert set(result.tuples()) == expected


@given(pair_sets)
def test_groups_partition_source_and_retain_declared_universe(rows):
    relation = Relation(rows, schema=("worker", "task"))
    domain = Relation([(t,) for t in range(6)], schema=("task",))
    groups = relation.group_by("task", over=domain)
    assert set(groups) == {(t,) for t in range(6)}
    assert set().union(*(set(group) for group in groups.values())) == rows
    for (task,), group in groups.items():
        assert set(group) == {(w, t) for w, t in rows if t == task}


@given(st.sets(st.integers(0, 5)), st.sets(st.text(max_size=3)))
def test_cross_matches_cartesian_product(left, right):
    a = Relation([(x,) for x in left], schema=("x",))
    b = Relation([(y,) for y in right], schema=("y",))
    assert set(a.cross(b).tuples()) == set(product(left, right))
