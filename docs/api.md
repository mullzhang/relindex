# API and semantics

`Relation` is the only public class. It represents an immutable finite set of
rows with named, ordered columns. Operations evaluate immediately in memory.
The core uses only the Python standard library.

## Constructing a relation

```python
from relindex import Relation

assignments = Relation(
    [("alice", "t1"), ("alice", "t1"), ("bob", "t2")],
    schema=("worker", "task"),
)
assert len(assignments) == 2
assert assignments.schema == ("worker", "task")
assert ("alice", "t1") in assignments
```

`rows` can be any iterable of tuples, including a generator. It is consumed
once and copied into immutable storage. Each row must have exactly as many
values as the schema has columns. Column names must be distinct, nonempty
built-in strings supplied in a tuple.

Values must be exactly built-in `int` or `str` objects. Subclasses, `bool`,
floats, `None`, dates, and mutable values are rejected. Convert external labels
explicitly when needed. Integer `1` and string `"1"` remain different labels.
Numeric coefficients, costs, and capacities belong in separate application
data structures; they are not relation columns in this initial API.

Malformed value types raise `TypeError`. Invalid schemas, arity mismatches,
unknown columns, or incompatible operations raise `ValueError`. Structural
validation also runs when the input contains no rows. Membership of an
invalid row returns `False`; it does not coerce the row.

Relations compare and hash by their ordered schema and row set. The compact
representation displays the schema and row count. Relations expose no row
iterator: use `tuples()` when passing keys to other libraries.

## Operations

All relation-valued operations return a new relation and remove duplicate
rows, including duplicates introduced by projection or joins.

| Method | Behavior |
| --- | --- |
| `project(*columns)` | Select and reorder columns. |
| `select(predicate)` | Keep rows for which the predicate returns `True`. |
| `rename(mapping)` | Rename columns simultaneously without moving values. |
| `join(other, on=(...))` | Inner equijoin on explicit, same-named columns. |
| `semi_join(other, on=(...))` | Keep complete left rows with a right match. |
| `anti_join(other, on=(...))` | Keep complete left rows without a right match. |
| `union(other)` | Rows in either relation. |
| `intersection(other)` | Rows in both relations. |
| `difference(other)` | Rows only in the left relation. |
| `cross(other)` | Cartesian product with disjoint column names. |
| `tuples()` | Canonically ordered tuple of row tuples. |
| `group_by(*columns, over=domain)` | Full rows grouped over every declared target. |

### Projection, selection, and renaming

```python
from relindex import Relation

routes = Relation(
    [("A", "B", 1), ("A", "C", 2), ("B", "C", 1)],
    schema=("origin", "destination", "period"),
)
first_period = routes.select(lambda row: row["period"] == 1)
assert first_period.project("destination", "origin").tuples() == (
    ("B", "A"),
    ("C", "B"),
)
assert routes.rename({"origin": "from_node"}).schema == (
    "from_node",
    "destination",
    "period",
)
```

A selection predicate receives a read-only mapping from column name to
value, in canonical row order. It must return a built-in `bool`. Its
exceptions propagate. On an empty relation the predicate is not evaluated,
so column accesses inside arbitrary Python code cannot be checked in advance.
Use a pure predicate for reproducible results.

Renaming is simultaneous: swapping two names is valid. Unknown source names
and duplicate resulting names are errors. Projection likewise rejects
unknown or repeated column names.

### Join rules

`on` is a nonempty tuple of unique columns present in both inputs. Multiple
columns form a composite equality key. The output schema contains the entire
left schema followed by the right non-key columns, in their original order.
Any right non-key name also present on the left is an error. Rename such a
column explicitly before joining.

```python
from relindex import Relation

available = Relation([(1, "A"), (2, "B")], schema=("period", "worker"))
required = Relation([("t1", 1)], schema=("task", "period"))
matched = available.join(required, on=("period",))
assert matched.schema == ("period", "worker", "task")
assert matched.tuples() == ((1, "A", "t1"),)
assert available.anti_join(required, on=("period",)).tuples() == ((2, "B"),)
```

Semi- and anti-joins retain the left schema. Right non-key columns do not
participate in matching and may have names that also appear on the left.
There is no automatic key inference or implicit Cartesian join.

### Set operations and products

Union, intersection, and difference require identical column names in the
same order. Use `project()` to reorder columns before combining sets.
`cross()` requires disjoint schemas and produces every pair of rows. Its
output size is the product of the input sizes; use a join when only matching
pairs are needed. Role-specific renames make self-products explicit.

## Deterministic export

`tuples()` returns an immutable tuple of tuples in lexicographic order:
integers sort numerically before strings, and strings sort by Unicode code
point order. The rule applies independently to each column. Neither input
order nor Python's hash seed changes the exported result.

```python
from relindex import Relation

labels = Relation([("10",), (10,), (2,), ("2",)], schema=("id",))
assert labels.tuples() == ((2,), (10,), ("10",), ("2",))
```

Export sorts on every call. Retain the returned tuple when creating many
variables or reusing keys. This ordering is a reproducibility contract, not
an implication that a mathematical relation has an inherent row order.

## Grouping over the complete constraint domain

```python
from relindex import Relation

eligible = Relation([("alice", "t1"), ("bob", "t1")], schema=("worker", "task"))
tasks = Relation([("t2",), ("t1",)], schema=("task",))
by_task = eligible.group_by("task", over=tasks)
assert by_task == {
    ("t1",): (("alice", "t1"), ("bob", "t1")),
    ("t2",): (),
}
```

`over` is required. Its schema must match the grouping columns in exactly
the same order. A single grouping column still produces tuple keys, such as
`("t1",)`. Composite groups work the same way. Each value contains complete
source rows in the original source schema order, ready to index variables.

The returned dictionary includes empty groups and rejects any source key
outside the domain. Its insertion order and the rows within each group are
canonical. It is an independent snapshot: editing the dictionary does not
change the relation. Grouping requires at least one column.

An empty group is not automatically invalid. A mandatory assignment may
require `sum(x) == 1`, making an empty group infeasible. A capacity condition
`sum(x) <= 3` is satisfied by the empty sum. The application must report the
former or construct the relevant constant constraint. The examples show
both cases and handle Pyomo's constant constraints explicitly.

Grouping scans the source once after sorting it. Reuse the resulting groups
when constructing constraints instead of scanning every candidate for every
constraint target.

## Empty and zero-column relations

Empty relations retain their schemas through every operation. For example,
an empty join still exposes the same columns as a nonempty join would.

A zero-column relation has either zero rows or the single empty tuple `()`.
`project()` with no columns returns the latter for a nonempty input and the
former for an empty input. A product with the one-row zero-column relation
leaves the other relation unchanged. Empty join keys and zero-column grouping
remain errors; use `cross()` to express a product.

## Requiring every skill

A join followed by projection finds a worker with **at least one** matching
required skill. For **all** required skills, start from an explicit candidate
universe and remove pairs with any missing requirement:

```python
from relindex import Relation

workers = Relation([("alice",), ("bob",)], schema=("worker",))
tasks = Relation([("analysis",), ("general",)], schema=("task",))
has_skill = Relation(
    [("alice", "python"), ("alice", "sql"), ("bob", "sql")],
    schema=("worker", "skill"),
)
requires = Relation(
    [("analysis", "python"), ("analysis", "sql")],
    schema=("task", "skill"),
)
forbidden = Relation([("bob", "general")], schema=("worker", "task"))
candidates = workers.cross(tasks)
missing = (
    candidates.join(requires, on=("task",))
    .anti_join(has_skill, on=("worker", "skill"))
    .project("worker", "task")
)
eligible = candidates.difference(missing).difference(forbidden)
assert eligible.tuples() == (("alice", "analysis"), ("alice", "general"))
```

A task with no requirements retains all its original candidates before
explicit exclusions. A worker with no skills can therefore qualify for a
task with no requirements. Start from a smaller justified candidate relation
when a full worker-by-task product is too large. This construction is tested
against direct universal quantification, including empty sets.

## Responsibility and limits

The application owns business keys, references to master data, coefficient
completeness, units, and model feasibility. Deduplicating complete rows does
not prove that a chosen subset of columns is a unique business key. Missing
dictionary coefficients are not replaced with zero. The assignment example
checks its one-skill-per-task assumption; it is not a general assignment-data
validation framework.

Use relation filters for data-known conditions that justify removing a
decision. Soft penalties and conditions depending on other decisions belong
in the optimization model. Having candidates for every target does not prove
that the model is feasible.

The implementation uses hash-based joins and eager intermediate relations.
Joins need memory proportional to their inputs and outputs; many-to-many
results can be large. Canonical exports and grouping add sorting costs.
There is no query optimizer, streaming execution, persistence, or solver
adapter. See the [measured comparison](benchmarks.md) before choosing it for
a large workload.
