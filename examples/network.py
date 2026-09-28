"""Minimum-cost flow with an explicit node domain, including an isolated node.

Run: uv run --locked --group examples python examples/network.py
"""

import json
from dataclasses import dataclass

import pulp
import pyomo.environ as pyo

from relindex import Relation


@dataclass(frozen=True)
class NetworkData:
    nodes: Relation
    arcs: Relation
    supply: dict[str, int]
    capacity: dict[tuple[str, str], int]
    cost: dict[tuple[str, str], int]


def example_data() -> NetworkData:
    return NetworkData(
        nodes=Relation([("A",), ("B",), ("C",), ("isolated",)], schema=("node",)),
        arcs=Relation([("A", "B"), ("B", "C"), ("A", "C")], schema=("origin", "destination")),
        supply={"A": 3, "B": 0, "C": -3, "isolated": 0},
        capacity={("A", "B"): 4, ("B", "C"): 4, ("A", "C"): 5},
        cost={("A", "B"): 1, ("B", "C"): 2, ("A", "C"): 5},
    )


def network_indices(data: NetworkData):
    outgoing = data.arcs.group_by("origin", over=data.nodes.rename({"node": "origin"}))
    incoming = data.arcs.group_by("destination", over=data.nodes.rename({"node": "destination"}))
    for (node,) in data.nodes.tuples():
        if not outgoing[(node,)] and not incoming[(node,)] and data.supply[node] != 0:
            raise ValueError(f"Isolated node has nonzero supply or demand: {node}")
    return outgoing, incoming


def build_pulp(data: NetworkData):
    outgoing, incoming = network_indices(data)
    problem = pulp.LpProblem("network", pulp.LpMinimize)
    keys = data.arcs.tuples()
    flow = {
        key: problem.add_variable(f"flow_{i}", lowBound=0, upBound=data.capacity[key])
        for i, key in enumerate(keys)
    }
    problem += pulp.lpSum(data.cost[key] * flow[key] for key in keys)
    for i, (node,) in enumerate(data.nodes.tuples()):
        problem += (
            pulp.lpSum(flow[key] for key in outgoing[(node,)])
            - pulp.lpSum(flow[key] for key in incoming[(node,)])
            == data.supply[node],
            f"balance_{i}",
        )
    return problem, flow


def solve_pulp(data: NetworkData):
    problem, flow = build_pulp(data)
    result = problem.solve(pulp.HiGHS(msg=False))
    if result.status_str != "Optimal":
        raise RuntimeError(f"PuLP did not find an optimum: {result.status_str}")
    return float(pulp.value(problem.objective)), {key: var.value() for key, var in flow.items()}


def build_pyomo(data: NetworkData):
    outgoing, incoming = network_indices(data)
    model = pyo.ConcreteModel()
    model.N = pyo.Set(initialize=[n for (n,) in data.nodes.tuples()])
    model.A = pyo.Set(dimen=2, initialize=data.arcs.tuples())
    model.flow = pyo.Var(
        model.A, domain=pyo.NonNegativeReals, bounds=lambda m, i, j: (0, data.capacity[i, j])
    )

    def balance_rule(m, node):
        if not outgoing[(node,)] and not incoming[(node,)]:
            return pyo.Constraint.Feasible
        return (
            pyo.quicksum(m.flow[key] for key in outgoing[(node,)])
            - pyo.quicksum(m.flow[key] for key in incoming[(node,)])
            == data.supply[node]
        )

    model.balance = pyo.Constraint(model.N, rule=balance_rule)
    model.objective = pyo.Objective(
        expr=pyo.quicksum(data.cost[key] * model.flow[key] for key in model.A),
        sense=pyo.minimize,
    )
    return model


def solve_pyomo(data: NetworkData):
    model = build_pyomo(data)
    result = pyo.SolverFactory("highs").solve(model)
    if not pyo.check_optimal_termination(result):
        raise RuntimeError(f"Pyomo did not find an optimum: {result.solver.termination_condition}")
    return float(pyo.value(model.objective)), {key: pyo.value(model.flow[key]) for key in model.A}


def main() -> None:
    data = example_data()
    for name, solve in (("PuLP", solve_pulp), ("Pyomo", solve_pyomo)):
        objective, flow = solve(data)
        print(
            json.dumps(
                {
                    "modeler": name,
                    "objective": objective,
                    "flows": [[*k, v] for k, v in flow.items()],
                }
            )
        )


if __name__ == "__main__":
    main()
