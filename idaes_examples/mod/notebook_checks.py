#################################################################################
# The Institute for the Design of Advanced Energy Systems Integrated Platform
# Framework (IDAES IP) was produced under the DOE Institute for the
# Design of Advanced Energy Systems (IDAES).
#
# Copyright (c) 2018-2023 by the software owners: The Regents of the
# University of California, through Lawrence Berkeley National Laboratory,
# National Technology & Engineering Solutions of Sandia, LLC, Carnegie Mellon
# University, West Virginia University Research Corporation, et al.
# All rights reserved.  Please see the files COPYRIGHT.md and LICENSE.md
# for full copyright and license information.
#################################################################################

# Authors: Andrew Lee, Dan Gunter

# Check imports
pyomo_import_check = True
try:
    from pyomo.environ import *
    from pyomo.opt import SolverStatus, TerminationCondition
    from pyomo.network import Arc, SequentialDecomposition
except Exception as err:
    pyomo_import_check = False

idaes_import_check = True
try:
    from idaes.core import *
    from idaes.models.unit_models import (PressureChanger,
                                                  CSTR,
                                                  Flash,
                                                  Heater,
                                                  Mixer,
                                                  Separator)
    from idaes.models.unit_models.pressure_changer import ThermodynamicAssumption

    from idaes.core.util.model_statistics import degrees_of_freedom
except Exception as err:
    idaes_import_check = False


def run_checks():
    check_count = 0

    if pyomo_import_check:
        print("Pyomo Import Checks:        Passed")
        check_count += 1
    else:
        print("Pyomo Import Checks:        FAILED")

    if idaes_import_check:
        print("IDAES Import Checks:        Passed")
        check_count += 1
    else:
        print("IDAES Import Checks:        FAILED")

    # Test available solvers
    if SolverFactory('ipopt').available():
        print("Solver Availability Check:  Passed")
        check_count += 1
    else:
        print("Solver Availability Check:  FAILED")

    # Check model construction and solving
    m = ConcreteModel()

    m.fs = FlowsheetBlock(dynamic=False)

    m.fs.v = Var(m.fs.time)

    def cons_rule(b, t):
        return b.v[t] == 1

    m.fs.c = Constraint(m.fs.time, rule=cons_rule)

    # Create a solver
    solver = SolverFactory('ipopt')
    results = solver.solve(m.fs)

    if (results.solver.termination_condition == TerminationCondition.optimal
            and results.solver.status == SolverStatus.ok):
        print("Simple Model Check:         Passed")
        check_count += 1
    else:
        print("Simple Model Check:         FAILED")

    return check_count
