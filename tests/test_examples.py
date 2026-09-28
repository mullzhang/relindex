"""Solver integration checked against independent, finite reference models."""

from dataclasses import replace
from itertools import product

import pytest

from examples import assignment, network
from relindex import Relation

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("solve", [assignment.solve_pulp, assignment.solve_pyomo])
def test_assignment_matches_exhaustive_enumeration(solve):
    data = assignment.example_data()
    # The reference reads input facts directly, without relindex operations.
    skills, requirements = set(data.has_skill.tuples()), set(data.requires.tuples())
    forbidden = set(data.forbidden.tuples())
    keys = sorted({(w, t) for w, s in skills for t, r in requirements if s == r} - forbidden)
    feasible = []
    for bits in product((0, 1), repeat=len(keys)):
        selected = tuple(key for bit, key in zip(bits, keys, strict=True) if bit)
        if any(sum(t == task for _, t in selected) != 1 for (task,) in data.tasks.tuples()):
            continue
        if any(
            sum(w == worker for w, _ in selected) > limit for worker, limit in data.capacity.items()
        ):
            continue
        feasible.append((sum(data.cost[key] for key in selected), selected))
    assert len(feasible) == 4
    assert min(feasible)[0] == 3
    assert solve(data) == min(feasible)


@pytest.mark.parametrize("build", [assignment.build_pulp, assignment.build_pyomo])
def test_uncovered_required_task_is_reported_before_model_building(build):
    data = assignment.example_data()
    data = replace(
        data,
        tasks=data.tasks.union(Relation([("t4",)], schema=("task",))),
        requires=data.requires.union(Relation([("t4", "missing")], schema=("task", "skill"))),
    )
    with pytest.raises(ValueError, match="Mandatory tasks without candidates.*t4"):
        build(data)


@pytest.mark.parametrize("solve", [assignment.solve_pulp, assignment.solve_pyomo])
def test_worker_without_candidates_is_retained(solve):
    data = assignment.example_data()
    data = replace(
        data,
        workers=data.workers.union(Relation([("unused",)], schema=("worker",))),
        capacity={**data.capacity, "unused": 0},
    )
    assert assignment.assignment_indices(data)[2][("unused",)] == ()
    assert solve(data)[0] == 3


def test_assignment_does_not_silently_interpret_multiple_skills_as_any_skill():
    data = assignment.example_data()
    data = replace(
        data, requires=data.requires.union(Relation([("t1", "sql")], schema=("task", "skill")))
    )
    with pytest.raises(ValueError, match="exactly one skill"):
        assignment.assignment_indices(data)


def test_models_have_only_the_expected_variables_and_all_constraints():
    data = assignment.example_data()
    pulp_model, variables = assignment.build_pulp(data)
    pyomo_model = assignment.build_pyomo(data)
    assert len(variables) == len(pulp_model.variables()) == len(pyomo_model.x) == 5
    assert len(pulp_model.constraints()) == len(pyomo_model.cover) + len(pyomo_model.capacity) == 6
    net = network.example_data()
    pulp_net, _ = network.build_pulp(net)
    pyomo_net = network.build_pyomo(net)
    assert len(pulp_net.constraints()) == len(pyomo_net.balance) == 4
    assert "isolated" in pyomo_net.balance


@pytest.mark.parametrize("solve", [network.solve_pulp, network.solve_pyomo])
def test_network_matches_independent_enumeration(solve):
    data = network.example_data()
    keys = data.arcs.tuples()
    costs = []
    for values in product(*(range(data.capacity[key] + 1) for key in keys)):
        flow = dict(zip(keys, values, strict=True))
        if all(
            sum(value for (origin, _), value in flow.items() if origin == node)
            - sum(value for (_, destination), value in flow.items() if destination == node)
            == supply
            for node, supply in data.supply.items()
        ):
            costs.append(sum(data.cost[key] * flow[key] for key in keys))
    objective, flow = solve(data)
    assert objective == min(costs) == 9
    assert flow == {("A", "B"): 3, ("A", "C"): 0, ("B", "C"): 3}


@pytest.mark.parametrize("build", [network.build_pulp, network.build_pyomo])
def test_isolated_nonzero_demand_is_never_dropped(build):
    data = network.example_data()
    data = replace(data, supply={**data.supply, "isolated": -1, "A": 4})
    with pytest.raises(ValueError, match="Isolated node.*isolated"):
        build(data)
