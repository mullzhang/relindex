# Contributing

Keep code, documentation, comments, and diagnostic messages in English.
The public package supports Python 3.12 and newer. Development uses the
Python and uv versions pinned in [mise.toml](mise.toml).

## Set up the checkout

Install [mise](https://mise.jdx.dev/getting-started.html), then run:

```sh
mise trust
mise install
mise run setup
mise run check
```

`mise run setup` installs the locked dependency groups into `.venv` using uv.
`uv.lock` is part of the reproducible development environment. Deliberate
dependency updates use `uv lock --upgrade`, followed by all checks and wheel
verification. Normal development and CI use `--locked`.

| Dependency group | Purpose |
| --- | --- |
| `dev` | pytest, Hypothesis, Ruff, and mypy |
| `examples` | PuLP 4, Pyomo 6, and the HiGHS Python binding |
| `benchmark` | DuckDB as an independent comparison |

These groups are not runtime requirements of the published wheel. The
examples solve through `highspy`; a separate solver executable is unnecessary.
The lockfile records exact modeling-library and solver versions.

## Validate a change

```sh
mise run format
mise run check
mise run examples
mise run verify:wheel
```

`check` verifies formatting, lint, strict typing of the public package,
unit and property tests, actual solver integration, documentation links,
and executable documentation examples. Solver tests run with their required
dependencies and fail on errors; they are not silently skipped.

To exercise only the relation library without modeling dependencies:

```sh
mise run test:core
```

The algebra tests compare with independent Python-set definitions. The
assignment example is checked against all 32 binary assignments, of which
four are feasible. The network example is checked against independent flow
enumeration on a small integral instance. Both examples retain the complete
constraint domain, including unused workers or isolated nodes.
Dictionary conversions are checked against independent comprehensions, including
mixed label types and wider projections. The dictionary assignment example is
checked against all 16 binary assignments and rejects uncovered tasks before
building either model.

`verify:wheel` builds a wheel and source distribution, rebuilds the wheel
from the source distribution, and compares package source bytes. It then
installs the wheel into a temporary environment outside the checkout, runs
core operations with no third-party packages, installs only the locked
example dependencies, and executes copied standalone examples. It checks
the `py.typed` marker and verifies that wheel metadata has no runtime
requirements. Build products stay in `dist/` and are ignored by Git.

GitHub Actions runs the check and wheel verification tasks on the pinned
development Python. A separate compatibility job runs tests on Python 3.12
and 3.13. Workflow execution must be confirmed by a real CI run; a local
pass alone does not establish remote CI status.

## Measure performance

```sh
mise run benchmark
mise run benchmark:models
mise run benchmark:mappings
```

The relation benchmark runs on macOS or Linux and reports fresh-process
timings, process peak RSS, exact-result fingerprints, versions, and source
hashes. Model construction and solving have a separate benchmark so solver
time does not become a relation-performance claim. See
[the methodology](docs/benchmarks.md) before interpreting the results.

## Package boundaries

`src/relindex/relation.py` owns the immutable relation contract, validation,
set operations, joins, grouping, and dictionary conversions. `src/relindex/__init__.py` exports
`Relation`. Examples own modeling-library calls and business assumptions;
they are deliberately outside the installed package. Benchmark and release
checks are development tools, not public API.

Prefer a small, explicit contract. Add a new label type, execution backend,
or solver adapter only when a concrete use case justifies both its semantics
and maintenance. Preserve set semantics, empty domains, and deterministic
exports when changing an operation.
