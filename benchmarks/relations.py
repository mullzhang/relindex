"""Measure equivalent sparse-index pipelines in fresh processes (macOS/Linux)."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import resource
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

METHODS = ("indexed-python", "relindex", "duckdb")


def inputs(size, case):
    buckets = size if case == "sparse" else max(1, size // 4)
    has = [(i, i % buckets) for i in range(size)]
    requires = [(i, i % buckets) for i in range(size)]
    forbidden = [(i, i) for i in range(0, size, 11)]
    return has, requires, forbidden


def python_groups(keys, size):
    groups = {(i,): [] for i in range(size + 1)}
    for key in keys:
        groups[(key[1],)].append(key)
    return {key: tuple(rows) for key, rows in groups.items()}


def run_worker(method, size, case):
    # Imports are outside elapsed pipeline time, but included in process RSS.
    if method == "relindex":
        from relindex import Relation
    elif method == "duckdb":
        import duckdb

    has, requires, forbidden = inputs(size, case)
    start = perf_counter()
    if method == "indexed-python":
        index = defaultdict(list)
        for task, skill in requires:
            index[skill].append(task)
        blocked = set(forbidden)
        keys = tuple(
            sorted(
                {
                    (worker, task)
                    for worker, skill in has
                    for task in index[skill]
                    if (worker, task) not in blocked
                }
            )
        )
    elif method == "relindex":
        eligible = (
            Relation(has, schema=("worker", "skill"))
            .join(Relation(requires, schema=("task", "skill")), on=("skill",))
            .project("worker", "task")
            .anti_join(Relation(forbidden, schema=("worker", "task")), on=("worker", "task"))
        )
        domain = Relation([(i,) for i in range(size + 1)], schema=("task",))
        keys = eligible.tuples()
    else:
        with duckdb.connect(config={"threads": 1}) as con:
            for table, rows, first, second in (
                ("has_skill", has, "worker", "skill"),
                ("requires", requires, "task", "skill"),
                ("forbidden", forbidden, "worker", "task"),
            ):
                con.execute(
                    f"CREATE TABLE {table} AS SELECT unnest(?) AS {first}, unnest(?) AS {second}",
                    [[a for a, _ in rows], [b for _, b in rows]],
                )
            keys = tuple(
                con.execute("""
                SELECT DISTINCT h.worker, r.task
                FROM has_skill AS h JOIN requires AS r ON h.skill = r.skill
                ANTI JOIN forbidden AS f ON h.worker = f.worker AND r.task = f.task
                ORDER BY h.worker, r.task
            """).fetchall()
            )
    prepared = perf_counter()
    groups = (
        eligible.group_by("task", over=domain)
        if method == "relindex"
        else python_groups(keys, size)
    )
    end = perf_counter()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = rss if sys.platform == "darwin" else rss * 1024
    digest = hashlib.sha256()
    for key in keys:
        digest.update(repr(key).encode("ascii"))
    for group, rows in groups.items():
        digest.update(repr((group, rows)).encode("ascii"))
    buckets = size if case == "sparse" else max(1, size // 4)
    base, remainder = divmod(size, buckets)
    return {
        "method": method,
        "size": size,
        "case": case,
        "input_rows": {"has_skill": size, "requires": size, "forbidden": len(forbidden)},
        "skill_buckets": buckets,
        "max_rows_per_skill_per_input": base + bool(remainder),
        "join_rows_before_exclusion": (buckets - remainder) * base**2 + remainder * (base + 1) ** 2,
        "output_rows": len(keys),
        "domain_sizes": {"workers": size, "tasks": size + 1},
        "possible_pairs": size * (size + 1),
        "density": len(keys) / (size * (size + 1)),
        "groups": len(groups),
        "empty_groups": sum(not rows for rows in groups.values()),
        "prepare_seconds": prepared - start,
        "group_seconds": end - prepared,
        "total_seconds": end - start,
        "peak_process_bytes": peak_bytes,
        "result_sha256": digest.hexdigest(),
    }


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Expected a positive integer")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=positive_int, default=[1000, 10000, 100000])
    parser.add_argument("--repetitions", type=positive_int, default=3)
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/latest.json"))
    parser.add_argument("--worker", choices=METHODS, help=argparse.SUPPRESS)
    parser.add_argument(
        "--case", choices=("sparse", "fanout"), default="sparse", help=argparse.SUPPRESS
    )
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(run_worker(args.worker, args.sizes[0], args.case)))
        return

    root = Path(__file__).resolve().parents[1]
    samples = []
    summary = []
    for size in args.sizes:
        for case in ("sparse", "fanout"):
            case_samples = []
            # Rotate method order so every repetition does not favor the same method.
            for repetition in range(args.repetitions):
                for offset in range(len(args.methods)):
                    method = args.methods[(repetition + offset) % len(args.methods)]
                    raw = subprocess.check_output(
                        [
                            sys.executable,
                            str(Path(__file__).resolve()),
                            "--worker",
                            method,
                            "--sizes",
                            str(size),
                            "--case",
                            case,
                        ],
                        text=True,
                    )
                    sample = json.loads(raw)
                    sample["repetition"] = repetition
                    case_samples.append(sample)
            if len({sample["result_sha256"] for sample in case_samples}) != 1:
                raise RuntimeError(f"Result mismatch for {case=} {size=}")
            samples.extend(case_samples)
            for method in args.methods:
                selected = [sample for sample in case_samples if sample["method"] == method]
                times = [sample["total_seconds"] for sample in selected]
                record = {
                    "method": method,
                    "size": size,
                    "case": case,
                    "output_rows": selected[0]["output_rows"],
                    "median_seconds": statistics.median(times),
                    "min_seconds": min(times),
                    "max_seconds": max(times),
                    "median_peak_process_bytes": statistics.median(
                        s["peak_process_bytes"] for s in selected
                    ),
                }
                summary.append(record)
                print(
                    f"{size:>7} {case:<7} {method:<14} {record['median_seconds']:.4f}s", flush=True
                )
    import relindex.relation

    sources = {
        "src/relindex/relation.py": Path(relindex.relation.__file__),
        "benchmarks/relations.py": Path(__file__).resolve(),
        "uv.lock": root / "uv.lock",
    }
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "processor": platform.machine(),
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("relindex",) + (("duckdb",) if "duckdb" in args.methods else ())
        },
        "source_sha256": {
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sources.items()
        },
        "methods": args.methods,
        "repetitions": args.repetitions,
        "samples": samples,
        "summary": summary,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
