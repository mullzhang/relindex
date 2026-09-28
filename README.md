# relindex

Relational index-set modeling for mathematical optimization.

Define sparse combinations with named relations, then pass ordinary Python
tuples to your optimization model. relindex has no runtime dependencies and
does not create variables, constraints, or solver sessions.

```python
from relindex import Relation

skills = Relation(
    [("alice", "python"), ("bob", "sql")],
    schema=("worker", "skill"),
)
requirements = Relation(
    [("report", "sql"), ("service", "python")],
    schema=("task", "skill"),
)
eligible = skills.join(requirements, on=("skill",)).project("worker", "task")
assert eligible.tuples() == (("alice", "service"), ("bob", "report"))
```

Rows are sets: duplicate inputs and duplicate projection results collapse.
Exports have a deterministic order. Column names and join keys are checked,
including on empty relations.

## Install from this checkout

Requires Python 3.12 or newer. This checkout is not yet a published release.

```sh
uv venv
uv pip install .
```

To develop and run examples, use the pinned mise tools:

```sh
mise trust
mise install
mise run setup
mise run check
mise run examples
```

## Keep every constraint target

The domain of a constraint can contain targets with no candidate variables.
Supply that domain explicitly when grouping:

```python
tasks = Relation([("report",), ("service",), ("uncovered",)], schema=("task",))
by_task = eligible.group_by("task", over=tasks)
assert by_task[("uncovered",)] == ()
assert by_task[("report",)] == (("bob", "report"),)
```

Each group contains complete variable keys. A model can report uncovered
mandatory tasks before solving, or explicitly handle a constant constraint.
relindex preserves empty groups without deciding whether they are feasible.

## Examples and reference

- [Assignment](examples/assignment.py): PuLP and Pyomo models with the same
  five candidates; both solve to cost 3 using HiGHS.
- [Network flow](examples/network.py): incoming and outgoing arcs over all
  nodes, including an isolated node.
- [API and semantics](docs/api.md): supported operations, ordering, types,
  empty relations, and requirements that must all be satisfied.
- [Benchmarks](docs/benchmarks.md): reproducible comparison with indexed
  Python and DuckDB, including memory measurements.
- [Contributing](CONTRIBUTING.md): checks, packaging, and supported tools.

The initial label types are built-in strings and integers. Coefficients and
application-specific validation belong to the caller. Only remove a
candidate when excluding that decision is valid for the intended model;
soft penalties and conditions depending on other decisions belong in the model.

Licensed under the [MIT License](LICENSE).
