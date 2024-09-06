import pyomo.environ as pyo
from pyomo.core.expr import EqualityExpression, identify_variables
from pyomo.util.subsystems import create_subsystem_block
from pyomo.common.collections import ComponentMap, ComponentSet
from pyomo.dae.flatten import flatten_dae_components


def _get_variables(cons, include_fixed=False):
    seen = set()
    variables = []
    for con in cons:
        for var in identify_variables(con.expr, include_fixed=include_fixed):
            if id(var) not in seen:
                seen.add(id(var))
                variables.append(var)
    return variables


def _remove_duplicates(items):
    seen = set()
    filtered = []
    for item in items:
        if id(item) not in seen:
            seen.add(id(item))
            filtered.append(item)
    return filtered


def get_subsystem_at_time(model, time, t):
    t0 = time.first()
    t1 = time.next(t0)
    indices = ComponentMap([(time, t1)])
    scalar_vars, dae_vars = flatten_dae_components(
        model, time, pyo.Var, indices=indices
    )
    scalar_cons, dae_cons = flatten_dae_components(
        model, time, pyo.Constraint, indices=indices
    )

    constraints = _remove_duplicates(
        [
            con[t]
            for con in dae_cons
            if t in con
            and con[t].active
            and isinstance(con[t].expr, EqualityExpression)
        ]
    )
    var_set = ComponentSet(_get_variables(constraints))
    variables = _remove_duplicates([var[t] for var in dae_vars if var[t] in var_set])

    subsystem = create_subsystem_block(constraints, variables)
    return subsystem, list(subsystem.input_vars.values())
