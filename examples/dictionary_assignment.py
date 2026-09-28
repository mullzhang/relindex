"""Filter a candidate dictionary and solve equivalent PuLP and Pyomo models.

Run: uv run --locked --group examples python examples/dictionary_assignment.py
"""

import json
from dataclasses import dataclass

import pulp
import pyomo.environ as pyo

from relindex import Relation


@dataclass(frozen=True)
class AssignmentData:
    candidates: dict[str, list[str]]
    tasks: Relation
    forbidden: Relation
    cost: dict[tuple[str, str], int]


def example_data() -> AssignmentData:
    candidates = {"t1": ["alice", "carol"], "t2": ["alice", "bob"], "t3": ["carol"]}
    return AssignmentData(
        candidates=candidates,
        tasks=Relation(((task,) for task in candidates), schema=("task",)),
        forbidden=Relation([("t1", "alice")], schema=("task", "worker")),
        cost={
            ("carol", "t1"): 1,
            ("alice", "t2"): 1,
            ("bob", "t2"): 2,
            ("carol", "t3"): 1,
        },
    )


def assignment_mapping(data: AssignmentData):
    eligible = Relation.from_mapping(data.candidates, key="task", value="worker").anti_join(
        data.forbidden, on=("task", "worker")
    )
    workers_for_task = eligible.to_mapping(key="task", value="worker", over=data.tasks)
    uncovered = tuple(task for task, workers in workers_for_task.items() if not workers)
    if uncovered:
        raise ValueError(f"Mandatory tasks without candidates: {uncovered}")
    return workers_for_task


def build_pulp(data: AssignmentData):
    workers_for_task = assignment_mapping(data)
    problem = pulp.LpProblem("dictionary_assignment", pulp.LpMinimize)
    keys = [(worker, task) for task, workers in workers_for_task.items() for worker in workers]
    x = {key: problem.add_variable(f"assign_{i}", cat="Binary") for i, key in enumerate(keys)}
    problem += pulp.lpSum(data.cost[key] * x[key] for key in keys)
    for i, (task, workers) in enumerate(workers_for_task.items()):
        problem += pulp.lpSum(x[worker, task] for worker in workers) == 1, f"cover_{i}"
    return problem, x


def build_pyomo(data: AssignmentData):
    workers_for_task = assignment_mapping(data)
    model = pyo.ConcreteModel()
    model.T = pyo.Set(initialize=list(workers_for_task))
    model.E = pyo.Set(
        dimen=2,
        initialize=[
            (worker, task) for task, workers in workers_for_task.items() for worker in workers
        ],
    )
    model.x = pyo.Var(model.E, domain=pyo.Binary)
    model.cover = pyo.Constraint(
        model.T,
        rule=lambda m, task: (
            pyo.quicksum(m.x[worker, task] for worker in workers_for_task[task]) == 1
        ),
    )
    model.objective = pyo.Objective(
        expr=pyo.quicksum(data.cost[key] * model.x[key] for key in model.E), sense=pyo.minimize
    )
    return model


def solve(data: AssignmentData):
    problem, x = build_pulp(data)
    result = problem.solve(pulp.HiGHS(msg=False))
    if result.status_str != "Optimal":
        raise RuntimeError(f"PuLP did not find an optimum: {result.status_str}")
    pulp_solution = (
        float(pulp.value(problem.objective)),
        tuple(k for k, v in x.items() if v.value() > 0.5),
    )

    model = build_pyomo(data)
    result = pyo.SolverFactory("highs").solve(model)
    if not pyo.check_optimal_termination(result):
        raise RuntimeError(f"Pyomo did not find an optimum: {result.solver.termination_condition}")
    pyomo_solution = (
        float(pyo.value(model.objective)),
        tuple(k for k in model.E if pyo.value(model.x[k]) > 0.5),
    )
    return {"PuLP": pulp_solution, "Pyomo": pyomo_solution}


def main() -> None:
    for name, (objective, selected) in solve(example_data()).items():
        print(json.dumps({"modeler": name, "objective": objective, "selected": selected}))


if __name__ == "__main__":
    main()
