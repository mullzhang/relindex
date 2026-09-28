"""Measure construction and solving of the two small documented examples."""

import argparse
import hashlib
import importlib
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

ROOT = Path(__file__).resolve().parents[1]
CASES = {"assignment": (5, 6, 10, 5, 3.0), "network": (3, 4, 6, 3, 9.0)}


def run_worker(case, modeler):
    example = importlib.import_module(f"examples.{case}")
    data = example.example_data()
    if modeler == "pulp":
        import pulp

        start = perf_counter()
        model, variables = example.build_pulp(data)
        built = perf_counter()
        solver = pulp.HiGHS(msg=False, threads=1)
        start_solve = perf_counter()
        result = model.solve(solver)
        solved = perf_counter()
        if result.status_str != "Optimal":
            raise RuntimeError(result.status_str)
        counts = (
            len(variables),
            len(model.constraints()),
            sum(coef != 0 for row in model.constraints() for _, coef in row.items()),
            sum(coef != 0 for _, coef in model.objective.items()),
            float(pulp.value(model.objective)),
        )
    else:
        import pyomo.environ as pyo
        from pyomo.repn import generate_standard_repn

        start = perf_counter()
        model = example.build_pyomo(data)
        built = perf_counter()
        solver = pyo.SolverFactory("highs")
        solver.options["threads"] = 1
        start_solve = perf_counter()
        result = solver.solve(model)
        solved = perf_counter()
        if not pyo.check_optimal_termination(result):
            raise RuntimeError(str(result.solver.termination_condition))
        constraints = list(model.component_data_objects(pyo.Constraint, active=True))
        counts = (
            sum(1 for _ in model.component_data_objects(pyo.Var)),
            len(constraints),
            sum(
                coef != 0
                for row in constraints
                for coef in generate_standard_repn(row.body).linear_coefs
            ),
            sum(coef != 0 for coef in generate_standard_repn(model.objective.expr).linear_coefs),
            float(pyo.value(model.objective)),
        )
    if counts != CASES[case]:
        raise RuntimeError(f"Unexpected model or solution: {case} {modeler} {counts}")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "case": case,
        "modeler": modeler,
        "build_including_indices_seconds": built - start,
        "solve_including_transfer_seconds": solved - start_solve,
        "peak_process_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "variables": counts[0],
        "constraints": counts[1],
        "constraint_nonzeros": counts[2],
        "objective_nonzeros": counts[3],
        "objective": counts[4],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/models.json"))
    parser.add_argument("--worker", choices=("pulp", "pyomo"), help=argparse.SUPPRESS)
    parser.add_argument("--case", choices=CASES, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    if args.worker:
        if not args.case:
            parser.error("--worker requires --case")
        print(json.dumps(run_worker(args.case, args.worker)))
        return
    samples = []
    summary = []
    for case in CASES:
        for modeler in ("pulp", "pyomo"):
            selected = []
            for repetition in range(args.repetitions):
                raw = subprocess.check_output(
                    [
                        sys.executable,
                        "-m",
                        "benchmarks.models",
                        "--worker",
                        modeler,
                        "--case",
                        case,
                    ],
                    cwd=ROOT,
                    text=True,
                )
                sample = json.loads(raw)
                sample["repetition"] = repetition
                selected.append(sample)
            samples.extend(selected)
            record = {"case": case, "modeler": modeler}
            for metric in (
                "build_including_indices_seconds",
                "solve_including_transfer_seconds",
                "peak_process_bytes",
            ):
                values = [s[metric] for s in selected]
                record[metric] = {
                    "median": statistics.median(values),
                    "min": min(values),
                    "max": max(values),
                }
            summary.append(record)
            print(json.dumps(record), flush=True)
    sources = (
        ROOT / "src/relindex/relation.py",
        ROOT / "examples/assignment.py",
        ROOT / "examples/network.py",
        Path(__file__).resolve(),
        ROOT / "uv.lock",
    )
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("relindex", "pulp", "pyomo", "highspy")
        },
        "solver_threads": 1,
        "repetitions": args.repetitions,
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources
        },
        "samples": samples,
        "summary": summary,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
