# Benchmarks

relindex trades validation, immutable relations, and deterministic exports for
explicit index semantics. The optimized implementation reduces repeated
validation, tuple construction, and global sorting. Handwritten dictionaries
remain faster in the measured workloads. These measurements do not establish
a general performance advantage or a supported maximum size.

## Reproduce

From the repository root on macOS or Linux:

```sh
mise run setup
mise run benchmark
mise run benchmark:models
mise run benchmark:mappings
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

This section records the original implementation at `4f7c645`. See the
optimization comparison below for current measurements; the reports preserve
the exact source hashes used for each run.

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
The dictionary benchmark below measures larger PuLP construction workloads;
it does not solve those models or extend these solver-performance results.

## Dictionary conversion and optimization

[mappings.py](../benchmarks/mappings.py) starts from an existing dictionary of
task labels to lists of worker labels. Each nonempty bucket has four candidates
and one deliberate duplicate. Every seventeenth task has an empty bucket;
the explicit task domain also includes one key absent from the dictionary.
Every eleventh diagonal task-worker pair is excluded. Input keys are inserted
in descending order so canonical output order requires actual sorting.

The three methods produce exactly the same dictionary with sorted scalar keys,
distinct sorted tuple values, and empty buckets:

| Method | Preparation |
| --- | --- |
| `python-dict` | Copy buckets into sets, filter with a set of forbidden pairs, and sort the output. |
| `relindex-rows` | Construct relations from row comprehensions, apply an anti-join, then flatten `group_by()` output. |
| `relindex-mapping` | Import with `from_mapping()`, apply the same anti-join, and export with `to_mapping()`. |

The handwritten baseline operates on the same valid built-in integer labels;
it is not a general-purpose replacement for relindex's input validation. Import
time includes domain and exclusion construction. Filtering and export have
separate timers; their sum with import is `prepare_seconds`. Each resulting
dictionary feeds an identical PuLP loop with binary variables and one
at-most-one constraint per task, including constant constraints for empty tasks.
Costs are `worker + 1`; model construction is timed separately, with no solve.

All methods import PuLP and relindex before timing. Input generation is also
excluded. Preparation RSS and post-build RSS are process high-water marks,
including imports, input data, retained intermediate results, and outputs.
They are not incremental allocations. The higher post-build mark includes the
model. Equality checks, fingerprints, and actual model-count checks run after
the timers and RSS readings. Each method and size uses three fresh processes,
with method order rotated between repetitions. Reports retain every sample
and the minimum, median, and maximum.

The [baseline report](../benchmarks/results/mappings-before.json) uses the
core from `4f7c645` with the same benchmark script. The
[current report](../benchmarks/results/mappings.json) uses the optimized core.
For each size, all methods and repetitions must agree with an independent
comprehension and have matching output fingerprints. At 100,000 input keys,
the model has 367,912 variables and 100,001 constraints, including 5,884 empty
groups; actual counts and constraint nonzeros are checked in every sample.

Recorded with CPython 3.14.6 and PuLP 4.0.0 on macOS 27.0 arm64. All 45
dictionary pipelines agree within each size, including across versions.
Median preparation times in seconds:

| Input keys | Previous row API | Optimized row API | New mapping API | Handwritten dictionary |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 0.0097 | 0.0045 | 0.0026 | 0.0007 |
| 10,000 | 0.1283 | 0.0521 | 0.0317 | 0.0091 |
| 100,000 | 1.7639 | 0.8845 | 0.6631 | 0.1230 |

At 100,000 keys, the new mapping pipeline is **2.66 times faster** than the
previous row pipeline, but the handwritten dictionary is still **5.39 times
faster** than the mapping pipeline. The optimized row API alone is 1.99 times
faster than before; changing from that API to the mapping methods provides
a further 1.33-times improvement on this case. This is a combination of core
improvements and cheaper conversions, not an inherent speed advantage of
dicts over sets.

PuLP construction takes a median 1.53 seconds for the mapping output.
Preparation plus model construction improves from 3.33 to 2.20 seconds
(1.51 times). Framework construction dominates more of the total after the
preparation improvement. Medians of individual phases need not sum to the
median total because samples vary.

Median process peak memory at 100,000 keys, in MiB:

| Method | Through preparation | Through model construction |
| --- | ---: | ---: |
| Previous row API | 272.3 | 365.0 |
| Optimized row API | 193.0 | 347.4 |
| New mapping API | 212.0 | 347.2 |
| Handwritten dictionary | 162.6 | 346.4 |

Direct mapping export uses per-key sets to deduplicate values from arbitrary
source widths. It reduces time here but uses more preparation memory than the
optimized full-row grouping. Neither conversion stores an index cache on the
relation. Reuse exported dictionaries for repeated lookups.

### Existing relation operations

The same change also speeds up the original join/project/anti-join/grouping
pipeline. The [before](../benchmarks/results/relations-before.json) and
[after](../benchmarks/results/relations-optimized.json) reports use the same
script, inputs, and outputs. All 72 pipelines agree within size and case,
including across versions. At 100,000 rows per main input:

| Case | Previous relindex seconds | Optimized relindex seconds | Speedup | Indexed Python seconds |
| --- | ---: | ---: | ---: | ---: |
| sparse | 0.9984 | 0.6621 | 1.51x | 0.1055 |
| fanout | 3.3232 | 1.9262 | 1.73x | 0.3608 |

Public input validation still checks every label and schema. Internal
operations freeze already validated results without validating every value
again. Column extraction functions are constructed once per operation instead
of allocating a generator for every row. `group_by()` sorts full rows within
each bucket instead of globally sorting the source. `to_mapping()` groups
scalar values directly and avoids a projected relation and full-row groups.
Set semantics, canonical output ordering, and empty-domain behavior are unchanged.

The two code versions were measured in separate sequential runs, rather than
interleaving versions. Background load was not controlled; three repetitions
on one machine are an estimate, not a statistical performance guarantee.
These input dictionaries use short integer labels and small, balanced buckets.
Mixed label types and wider projections are covered by correctness tests,
not by these timing results.

### Reproduce the baseline comparison

The baseline does not provide `from_mapping()` or `to_mapping()`, so it runs
only the handwritten and row-based methods. A temporary package copy selects
its implementation without modifying the checkout or its environment:

```sh
baseline_dir=$(mktemp -d)
mkdir "$baseline_dir/relindex"
git show 4f7c645:src/relindex/__init__.py > "$baseline_dir/relindex/__init__.py"
git show 4f7c645:src/relindex/relation.py > "$baseline_dir/relindex/relation.py"
PYTHONPATH="$baseline_dir" mise exec -- uv run --locked --group examples \
  python -m benchmarks.mappings --methods python-dict relindex-rows \
  --output /tmp/relindex-mappings-before.json
PYTHONPATH="$baseline_dir" mise exec -- uv run --locked \
  python -m benchmarks.relations --methods indexed-python relindex \
  --output /tmp/relindex-relations-before.json
mise run benchmark:mappings
mise exec -- uv run --locked python -m benchmarks.relations \
  --methods indexed-python relindex --output /tmp/relindex-relations-after.json
```

Both scripts hash the actually imported core, including when `PYTHONPATH`
selects the baseline. The original DuckDB comparison above is retained as
historical data; this focused before/after run does not rerun DuckDB.
