# Benchmarks

relindex trades additional validation and relation objects for explicit index
semantics. On this workload, handwritten indexed Python is about 9-12 times
faster. Choose relindex for its contract and readable transformations when
that overhead is acceptable. These measurements do not establish a general
performance advantage or a supported maximum size.

## Reproduce

From the repository root on macOS or Linux:

```sh
mise run setup
mise run benchmark
mise run benchmark:models
```

For a shorter relation run:

```sh
uv run --locked --group benchmark python benchmarks/relations.py \
  --sizes 1000 10000 --repetitions 3 --output /tmp/relindex-benchmark.json
```

The [relation benchmark](../benchmarks/relations.py) writes
[raw results](../benchmarks/results/latest.json), and the
[model benchmark](../benchmarks/models.py) writes
[model results](../benchmarks/results/models.json). Re-running the default
commands replaces these reports intentionally. Each report records Python,
platform and library versions, source hashes, every sample, and summaries.
Reports are local measurements, not an independently reproduced result.

## Relation workload

Each main input has `n` rows: worker-skill facts and task-skill requirements.
The sparse case has `n` skill values, each used once per input. The fanout
case has `n / 4` skill values, each used four times per input at the default
sizes, so its join produces `4n` rows before exclusion. Both use balanced
keys; neither measures a skewed or adversarial key distribution.

Every eleventh diagonal worker-task pair is forbidden. The output consists
of distinct, canonically sorted eligible worker-task pairs and groups over
all `n + 1` declared tasks, including an additional uncovered task. Each
method's full key sequence and group sequence must have the same SHA-256
fingerprint in every repetition. The report includes input and output row
counts, density relative to `n * (n + 1)`, and empty-group counts. The extra
uncovered task is included in this denominator.

| Method | Implementation |
| --- | --- |
| Indexed Python | A dictionary keyed by skill, a forbidden-pair set, a set comprehension, sorting, and one grouping pass |
| relindex | Construct relations, hash join, project, anti-join, export, and `group_by` over an explicit domain |
| DuckDB | Create an in-memory connection and tables from Python lists using parameterized `unnest`, join and anti-join, apply `DISTINCT` and `ORDER BY`, fetch Python tuples, then group in Python |

Three repetitions run in separate processes for each method, size, and case.
Method order rotates between repetitions. DuckDB uses one thread. Imports
and synthetic input-list generation are outside timed regions. Timing starts
before constructing the engine-specific data and ends after grouping.
`prepare_seconds` includes construction, operations, Python tuple conversion,
and canonical sorting; `group_seconds` is measured separately. Their sum is
`total_seconds`. Preparation is not split into separate operator microbenchmarks.

This is a Python-input-to-Python-output pipeline comparison. DuckDB connection
setup, array parameter binding, table loading, and fetch costs are included;
its reported time is not isolated query execution time. These results cannot
predict performance on data already resident in DuckDB or on alternative
Arrow/columnar ingestion paths. There is no claim that this ingestion path
is DuckDB's fastest. The Python baseline already uses an index and avoids
scanning a full Cartesian product.

Process peak RSS comes from `resource.getrusage`. It includes the interpreter,
imports, input lists, engine allocations, and retained outputs, so it is not
an incremental memory cost attributable solely to relindex. Relation RSS is
sampled before fingerprint calculation. The unit conversion accounts for
macOS bytes and Linux KiB. These scripts do not support Windows RSS reporting.

## Recorded relation results

Run on 2026-09-29 JST (2026-09-28 UTC), macOS 27.0 arm64,
CPython 3.14.6, relindex 0.1.0, and DuckDB 1.5.6. All 54 measured
relation pipelines produced matching results within their size and case.
Times below are medians in seconds; the raw report preserves all samples
and minimum/maximum variation.

| Rows per main input | Case | Output pairs | Indexed Python | relindex | DuckDB pipeline |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1,000 | sparse | 909 | 0.0007 | 0.0075 | 0.4208 |
| 1,000 | fanout | 3,909 | 0.0020 | 0.0228 | 0.4028 |
| 10,000 | sparse | 9,090 | 0.0083 | 0.0878 | 3.9456 |
| 10,000 | fanout | 39,090 | 0.0246 | 0.2743 | 4.0211 |
| 100,000 | sparse | 90,909 | 0.1259 | 1.2437 | 38.8777 |
| 100,000 | fanout | 390,909 | 0.4245 | 3.8913 | 39.4807 |

At 100,000 rows per main input, relindex took 1.187-1.328 seconds in
the sparse case and 3.891-3.901 seconds in the fanout case across the three
runs. Its eager intermediates and repeated sorting have a measurable cost.
The large DuckDB totals above include Python-list ingestion and must not be
read as a ranking of the underlying join algorithms.

Median peak process memory at 100,000 rows per input, in MiB:

| Case | Indexed Python | relindex | DuckDB pipeline |
| --- | ---: | ---: | ---: |
| sparse | 120.6 | 125.4 | 144.4 |
| fanout | 148.0 | 257.5 | 204.4 |

These cases do not cover very wide relations, long string labels, repeated
queries against reusable indexes, adversarial hashing, heavy key skew, or
outputs approaching a full Cartesian product. Density is relative to the
worker/task universe, not the number of skill facts. Three repetitions on one
machine provide an initial cost estimate, not a confidence interval or a
production capacity claim. Background load and CPU frequency were not
controlled, and the reports record the architecture rather than the exact
CPU model or available RAM.

## Model construction and solving

The separate model benchmark runs the documented small assignment and network
examples through PuLP 4.0.0, Pyomo 6.10.1, and highspy 1.15.1. Each modeler and
example uses three fresh processes with HiGHS restricted to one thread.
Both example modules import both modeling libraries, so process RSS is not a
comparison of each library's standalone import footprint.

Construction time includes index preparation and framework model construction.
Imports and input generation are excluded. Solve time includes model transfer,
solver execution, and solution loading, while solver-object creation is outside
that timer. Counts are extracted from the actual models: constraint nonzeros
exclude objective coefficients and include no entries for constant rows.
All samples must match the expected counts and optimum. Unit tests separately
compare solutions with independent enumeration.

| Example | Modeler | Variables | Constraints | Constraint nonzeros | Build ms | Solve ms | Objective |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| assignment | pulp | 5 | 6 | 10 | 0.300 | 1.149 | 3 |
| assignment | pyomo | 5 | 6 | 10 | 0.718 | 3.772 | 3 |
| network | pulp | 3 | 4 | 6 | 0.226 | 0.821 | 9 |
| network | pyomo | 3 | 4 | 6 | 0.655 | 3.187 | 9 |

The assignment objective has five nonzero coefficients; the network objective
has three. The network's four constraints include the isolated node.
Per-sample times, ranges, process peak RSS, and version/source metadata are in
the model report. These tiny models establish working integration and separate
cost categories; they do not establish scaling or relative solver performance.
Larger model-building workloads remain unmeasured.
