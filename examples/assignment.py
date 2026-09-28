"""Solve the same sparse assignment with PuLP and Pyomo using HiGHS.

Run: uv run --locked --group examples python examples/assignment.py
"""

import json
from dataclasses import dataclass

import pulp
import pyomo.environ as pyo

from relindex import Relation


@dataclass(frozen=True)
class AssignmentData:
    workers: Relation
    tasks: Relation
    has_skill: Relation
    requires: Relation
    forbidden: Relation
    capacity: dict[str, int]
    cost: dict[tuple[str, str], int]


def example_data() -> AssignmentData:
    return AssignmentData(
        workers=Relation([("alice",), ("bob",), ("carol",)], schema=("worker",)),
        tasks=Relation([("t1",), ("t2",), ("t3",)], schema=("task",)),
        has_skill=Relation(
            [("alice", "python"), ("alice", "sql"), ("bob", "sql"), ("carol", "python")],
            schema=("worker", "skill"),
        ),
        requires=Relation(
            [("t1", "python"), ("t2", "sql"), ("t3", "python")],
            schema=("task", "skill"),
        ),
        forbidden=Relation([("alice", "t3")], schema=("worker", "task")),
        capacity={"alice": 2, "bob": 1, "carol": 2},
        cost={
            ("alice", "t1"): 3,
            ("alice", "t2"): 1,
            ("bob", "t2"): 2,
            ("carol", "t1"): 1,
            ("carol", "t3"): 1,
        },
    )


def assignment_indices(data: AssignmentData):
    requirements = data.requires.group_by("task", over=data.tasks)
    if any(len(rows) != 1 for rows in requirements.values()):
        raise ValueError("This example requires exactly one skill per task")
    eligible = (
        data.has_skill.join(data.requires, on=("skill",))
        .project("worker", "task")
        .anti_join(data.forbidden, on=("worker", "task"))
    )
    by_task = eligible.group_by("task", over=data.tasks)
    by_worker = eligible.group_by("worker", over=data.workers)
    uncovered = [task for (task,), keys in by_task.items() if not keys]
    if uncovered:
        raise ValueError(f"Mandatory tasks without candidates: {uncovered}")
    return eligible, by_task, by_worker


def build_pulp(data: AssignmentData):
    eligible, by_task, by_worker = assignment_indices(data)
    problem = pulp.LpProblem("assignment", pulp.LpMinimize)
    keys = eligible.tuples()
    x = {key: problem.add_variable(f"assign_{i}", cat="Binary") for i, key in enumerate(keys)}
    problem += pulp.lpSum(data.cost[key] * x[key] for key in keys)
    for i, keys_for_task in enumerate(by_task.values()):
        problem += pulp.lpSum(x[key] for key in keys_for_task) == 1, f"cover_{i}"
    for i, ((worker,), keys_for_worker) in enumerate(by_worker.items()):
        problem += (
            pulp.lpSum(x[key] for key in keys_for_worker) <= data.capacity[worker],
            f"capacity_{i}",
        )
    return problem, x


def solve_pulp(data: AssignmentData):
    problem, x = build_pulp(data)
    result = problem.solve(pulp.HiGHS(msg=False))
    if result.status_str != "Optimal":
        raise RuntimeError(f"PuLP did not find an optimum: {result.status_str}")
    return float(pulp.value(problem.objective)), tuple(
        key for key, var in x.items() if var.value() > 0.5
    )


def build_pyomo(data: AssignmentData):
    eligible, by_task, by_worker = assignment_indices(data)
    model = pyo.ConcreteModel()
    model.W = pyo.Set(initialize=[w for (w,) in data.workers.tuples()])
    model.T = pyo.Set(initialize=[t for (t,) in data.tasks.tuples()])
    model.E = pyo.Set(dimen=2, initialize=eligible.tuples())
    model.x = pyo.Var(model.E, domain=pyo.Binary)

    def cover_rule(m, task):
        return pyo.quicksum(m.x[key] for key in by_task[(task,)]) == 1

    def capacity_rule(m, worker):
        keys = by_worker[(worker,)]
        if not keys:
            return (
                pyo.Constraint.Feasible if data.capacity[worker] >= 0 else pyo.Constraint.Infeasible
            )
        return pyo.quicksum(m.x[key] for key in keys) <= data.capacity[worker]

    model.cover = pyo.Constraint(model.T, rule=cover_rule)
    model.capacity = pyo.Constraint(model.W, rule=capacity_rule)
    model.objective = pyo.Objective(
        expr=pyo.quicksum(data.cost[key] * model.x[key] for key in model.E),
        sense=pyo.minimize,
    )
    return model


def solve_pyomo(data: AssignmentData):
    model = build_pyomo(data)
    result = pyo.SolverFactory("highs").solve(model)
    if not pyo.check_optimal_termination(result):
        raise RuntimeError(f"Pyomo did not find an optimum: {result.solver.termination_condition}")
    return float(pyo.value(model.objective)), tuple(
        key for key in model.E if pyo.value(model.x[key]) > 0.5
    )


def main() -> None:
    data = example_data()
    for name, solve in (("PuLP", solve_pulp), ("Pyomo", solve_pyomo)):
        objective, selected = solve(data)
        print(json.dumps({"modeler": name, "objective": objective, "selected": selected}))


if __name__ == "__main__":
    main()
