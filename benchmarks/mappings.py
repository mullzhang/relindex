"""Compare dictionary-to-model pipelines in fresh processes (macOS/Linux)."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import resource
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from benchmarks.relations import positive_int

ROOT = Path(__file__).resolve().parents[1]
METHODS = ("python-dict", "relindex-rows", "relindex-mapping")
METRICS = (
    "import_seconds",
    "filter_seconds",
    "export_seconds",
    "prepare_seconds",
    "model_build_seconds",
    "total_seconds",
    "prepare_peak_process_bytes",
    "peak_process_bytes",
)


def inputs(size):
    mapping = {
        task: [] if task % 17 == 0 else [(task + j) % size for j in range(4)] + [task]
        for task in reversed(range(size))
    }
    return mapping, list(reversed(range(size + 1))), [(t, t) for t in range(0, size, 11)]


def peak_bytes():
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss if sys.platform == "darwin" else rss * 1024


def run_worker(method, size):
    import pulp

    from relindex import Relation

    mapping, domain_keys, forbidden = inputs(size)
    start = perf_counter()
    if method == "python-dict":
        candidates = {task: set(workers) for task, workers in mapping.items()}
        domain = set(domain_keys)
        blocked = set(forbidden)
    else:
        candidates = (
            Relation.from_mapping(mapping, key="task", value="worker")
            if method == "relindex-mapping"
            else Relation(
                ((task, worker) for task, workers in mapping.items() for worker in workers),
                schema=("task", "worker"),
            )
        )
        domain = Relation(((task,) for task in domain_keys), schema=("task",))
        blocked = Relation(forbidden, schema=("task", "worker"))
    imported = perf_counter()
    if method == "python-dict":
        filtered = {
            task: {worker for worker in workers if (task, worker) not in blocked}
            for task, workers in candidates.items()
        }
    else:
        filtered = candidates.anti_join(blocked, on=("task", "worker"))
    operated = perf_counter()
    if method == "python-dict":
        if any(workers and task not in domain for task, workers in filtered.items()):
            raise ValueError("Source key outside domain")
        output = {task: tuple(sorted(filtered.get(task, ()))) for task in sorted(domain)}
    elif method == "relindex-rows":
        groups = filtered.group_by("task", over=domain)
        output = {task: tuple(row[1] for row in rows) for (task,), rows in groups.items()}
        del groups
    else:
        output = filtered.to_mapping(key="task", value="worker", over=domain)
    exported = perf_counter()
    prepare_rss = peak_bytes()

    # All methods feed exactly the same dictionary loop into PuLP. An empty
    # optional task has the valid constant constraint 0 <= 1.
    build_start = perf_counter()
    problem = pulp.LpProblem("mapping_capacity", pulp.LpMinimize)
    x = {
        (task, worker): problem.add_variable(f"x_{i}_{j}", cat="Binary")
        for i, (task, workers) in enumerate(output.items())
        for j, worker in enumerate(workers)
    }
    problem += pulp.lpSum((worker + 1) * var for (_, worker), var in x.items())
    for i, (task, workers) in enumerate(output.items()):
        problem += pulp.lpSum(x[task, worker] for worker in workers) <= 1, f"capacity_{i}"
    built = perf_counter()
    rss = peak_bytes()

    # Reference generation, equality, model counts, and fingerprints are untimed.
    blocked_pairs = set(forbidden)
    expected = {
        task: tuple(sorted({w for w in mapping.get(task, ()) if (task, w) not in blocked_pairs}))
        for task in sorted(domain_keys)
    }
    if list(output.items()) != list(expected.items()):
        raise RuntimeError("Dictionary output differs from the direct specification")
    rows = sum(map(len, expected.values()))
    constraints = problem.constraints()
    nonzeros = sum(coef != 0 for row in constraints for _, coef in row.items())
    if (len(x), len(problem.variables()), len(constraints), nonzeros) != (
        rows,
        rows,
        size + 1,
        rows,
    ):
        raise RuntimeError("Model counts differ from the reference")
    digest = hashlib.sha256()
    for item in output.items():
        digest.update(repr(item).encode("ascii"))
    return {
        "method": method,
        "size": size,
        "input_values": sum(map(len, mapping.values())),
        "output_rows": rows,
        "groups": len(output),
        "empty_groups": sum(not v for v in output.values()),
        "variables": len(x),
        "constraints": len(constraints),
        "constraint_nonzeros": nonzeros,
        "import_seconds": imported - start,
        "filter_seconds": operated - imported,
        "export_seconds": exported - operated,
        "prepare_seconds": exported - start,
        "model_build_seconds": built - build_start,
        "total_seconds": exported - start + built - build_start,
        "prepare_peak_process_bytes": prepare_rss,
        "peak_process_bytes": rss,
        "result_sha256": digest.hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=positive_int, default=[1000, 10000, 100000])
    parser.add_argument("--repetitions", type=positive_int, default=3)
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/mappings.json"))
    parser.add_argument("--worker", choices=METHODS, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(run_worker(args.worker, args.sizes[0])))
        return
    samples, summary = [], []
    for size in args.sizes:
        selected = []
        for repetition in range(args.repetitions):
            for offset in range(len(args.methods)):
                method = args.methods[(repetition + offset) % len(args.methods)]
                raw = subprocess.check_output(
                    [
                        sys.executable,
                        "-m",
                        "benchmarks.mappings",
                        "--worker",
                        method,
                        "--sizes",
                        str(size),
                    ],
                    cwd=ROOT,
                    text=True,
                )
                sample = json.loads(raw)
                sample["repetition"] = repetition
                selected.append(sample)
        if len({s["result_sha256"] for s in selected}) != 1:
            raise RuntimeError(f"Mismatching outputs for {size=}")
        samples.extend(selected)
        for method in args.methods:
            matching = [s for s in selected if s["method"] == method]
            record = {"size": size, "method": method, "output_rows": matching[0]["output_rows"]}
            for metric in METRICS:
                values = [s[metric] for s in matching]
                record[metric] = {
                    "median": statistics.median(values),
                    "min": min(values),
                    "max": max(values),
                }
            summary.append(record)
            print(
                f"{size:>7} {method:<18} prepare={record['prepare_seconds']['median']:.4f}s "
                f"model={record['model_build_seconds']['median']:.4f}s",
                flush=True,
            )
    import relindex.relation

    sources = {
        name: ROOT / name
        for name in (
            "benchmarks/mappings.py",
            "benchmarks/relations.py",
            "uv.lock",
        )
    }
    sources["src/relindex/relation.py"] = Path(relindex.relation.__file__)
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "versions": {name: importlib.metadata.version(name) for name in ("relindex", "pulp")},
        "methods": args.methods,
        "repetitions": args.repetitions,
        "source_sha256": {
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sources.items()
        },
        "samples": samples,
        "summary": summary,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
