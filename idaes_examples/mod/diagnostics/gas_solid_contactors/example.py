##############################################################################
# Institute for the Design of Advanced Energy Systems Process Systems
# Engineering Framework (IDAES PSE Framework) Copyright (c) 2018-2019, by the
# software owners: The Regents of the University of California, through
# Lawrence Berkeley National Laboratory,  National Technology & Engineering
# Solutions of Sandia, LLC, Carnegie Mellon University, West Virginia
# University Research Corporation, et al. All rights reserved.
#
# Please see the files COPYRIGHT.txt and LICENSE.txt for full copyright and
# license information, respectively. Both files are also available online
# at the URL "https://github.com/IDAES/idaes-pse".
##############################################################################
"""Example of debugging a structural singularity using the IDAES diagnostics
toolbox. This script reproduces the functionality in the structural_singularity.ipynb
notebook, but breaks the example into helper functions that are easier to test.

As a script, this module runs the example end-to-end.

"""
from idaes_examples.mod.diagnostics.gas_solid_contactors.model import make_model
from idaes_examples.mod.diagnostics.util import get_subsystem_at_time
from idaes.core.util.model_statistics import degrees_of_freedom, large_residuals_set
from idaes.core.util.model_diagnostics import DiagnosticsToolbox
import pyomo.environ as pyo
from pyomo.core.expr import replace_expressions
from pyomo.util.subsystems import TemporarySubsystemManager
from pyomo.contrib.incidence_analysis import IncidenceGraphInterface
import logging


def check_dof_and_residuals(model):
    dof = degrees_of_freedom(model)
    has_large_residuals = bool(large_residuals_set(model, tol=1e-5))
    print(f"Degrees of freedom: {dof}")
    print(f"Has large residuals: {has_large_residuals}")
    return dof, has_large_residuals


def attempt_solve(model):
    solver = pyo.SolverFactory("ipopt")
    solver.options["max_iter"] = 20
    solver.options["print_user_options"] = "yes"
    solver.options["OF_print_info_string"] = "yes"
    res = solver.solve(model, tee=True)
    return res


def fix_degrees_of_freedom(model):
    model.fs.MB.gas_phase.properties[:, 0].flow_mol.fix()
    model.fs.MB.solid_phase.properties[:, 1].flow_mass.fix()
    model.piecewise_constant_constraints.deactivate()


def free_degrees_of_freedom(model):
    model.fs.MB.gas_phase.properties[:, 0].flow_mol.unfix()
    model.fs.MB.gas_phase.properties[0, 0].flow_mol.fix()
    model.fs.MB.solid_phase.properties[:, 1].flow_mass.unfix()
    model.fs.MB.solid_phase.properties[0, 1].flow_mass.fix()
    model.piecewise_constant_constraints.activate()


def main():
    model = make_model()
    # Before trying to solve the model, let's make sure it conforms to our
    # expectations. I.e. it (a) has degrees of freedom and (b) is initialized to
    # a feasible point.
    check_dof_and_residuals(model)
    # Looks good so far, let's try to solve!
    attempt_solve(model)

    # Let's run the diagnostics toolbox on the model and see what it has to say
    fix_degrees_of_freedom(model)
    dt = DiagnosticsToolbox(model)

    # Before calling report_structural_issues, we'll effectively disable Pyomo
    # logging messages. This is not recommended in general, but we do it here
    # to supress unit inconsistency errors that otherwise flood our screen.
    # This model has unit inconsistency errors as it was created in IDAES 1.7,
    # before unit consistency was enforced for all models.
    logger = logging.getLogger("pyomo")
    orig_level = logger.level
    logger.setLevel(logging.CRITICAL)

    # Now we can finally see what the diagnostics toolbox has to say
    dt.report_structural_issues()
    # We got the following warnings:
    # - Inconsistent units
    # - Structural singularity
    # - Potential evaluation errors
    # We'll ignore inconsistent units and potential evaluation errors, and focus on
    # the structural singularity.
    dt.display_underconstrained_set()
    dt.display_overconstrained_set()

    # Suppose the above doesn't give us any leads. We'll try to break the problem
    # down into subsystems at each point in time. These should individually be
    # nonsingular.
    t0 = model.fs.time.first()
    t_block, inputs = get_subsystem_at_time(model, model.fs.time, t0)
    with TemporarySubsystemManager(to_fix=inputs):
        dt = DiagnosticsToolbox(t_block)
        dt.report_structural_issues()
        dt.display_underconstrained_set()
        dt.display_overconstrained_set()
    # The overconstrained system decomposes into smaller indepedent blocks, which
    # are easier to debug.

    # After some thought, we decide we need to make particle porosity a variable,
    # and add an equation linking flow rate and density. We'll make these changes
    # on a fresh copy of the model.
    model2 = make_model()
    model2.fs.MB.gas_phase.properties[:, 0].flow_mol.fix()
    model2.fs.MB.solid_phase.properties[:, 1].flow_mass.fix()
    model2.piecewise_constant_constraints.deactivate()

    # Add a new particle porosity variable
    model2.fs.MB.particle_porosity = pyo.Var(
        model2.fs.time,
        model2.fs.MB.length_domain,
        initialize=model2.fs.solid_properties.particle_porosity.value,
    )

    # Replace particle porosity parameter with this new variable. First, we'll
    # inspect which constraints contain the particle porosity "parameter"
    # (really a fixed variable, which is convenient).
    igraph = IncidenceGraphInterface(model2, include_fixed=True)
    porosity_param = model2.fs.solid_properties.particle_porosity
    print(f"Constraints containing {porosity_param.name}:")
    for con in igraph.get_adjacent_to(porosity_param):
        print(f"  {con.name}")
    # Particle porosity appears in gen_rate_expression and density_particle_constraint.
    # We now replace it using Pyomo's replace_expressions function.
    for t, x in model2.fs.time * model2.fs.MB.length_domain:
        substitution_map = {id(porosity_param): model2.fs.MB.particle_porosity[t, x]}
        sp = model2.fs.MB.solid_phase
        cons = [
            sp.properties[t, x].density_particle_constraint,
            sp.reactions[t, x].gen_rate_expression["R1"],
        ]
        for con in cons:
            con.set_value(
                replace_expressions(
                    con.expr,
                    substitution_map,
                    descend_into_named_expressions=True,
                )
            )

    # Add the constraint we are missing
    @model2.fs.MB.Constraint(model2.fs.time, model2.fs.MB.length_domain)
    def density_flowrate_constraint(mb, t, x):
        return (
            mb.velocity_superficial_solid[t] * mb.bed_area
            * mb.solid_phase.properties[t, x].dens_mass_particle
            == mb.solid_phase.properties[t, x].flow_mass
        )

    dt = DiagnosticsToolbox(model2)
    dt.report_structural_issues()

    # The structural singularity appears to be gone. Let's try to solve.
    model2.fs.MB.gas_phase.properties[:, 0].flow_mol.unfix()
    model2.fs.MB.gas_phase.properties[0, 0].flow_mol.fix()
    model2.fs.MB.solid_phase.properties[:, 1].flow_mass.unfix()
    model2.fs.MB.solid_phase.properties[0, 1].flow_mass.fix()
    model2.piecewise_constant_constraints.activate()

    attempt_solve(model2)

    # This doesn't look any better. Let's check for numerical issues.
    model2.fs.MB.gas_phase.properties[:, 0].flow_mol.fix()
    model2.fs.MB.solid_phase.properties[:, 1].flow_mass.fix()
    model2.piecewise_constant_constraints.deactivate()
    dt.report_numerical_issues()

    # We seem to have nearly parallel constraints. Let's see what they are.
    dt.display_near_parallel_constraints()
    # What is this "solid_super_vel"?
    model2.fs.MB.solid_super_vel[0].pprint()
    # This is the constraint we just added. Looks like it was already defined at
    # the solid inlet. We'll just deactivate the new constraint here.
    model2.fs.MB.density_flowrate_constraint[:, 1.0].deactivate()
    # But now we've added degrees of freedom. Let's re-check the structural
    # diagnostics
    dt = DiagnosticsToolbox(model2)
    dt.report_structural_issues()

    # After some thought, we decide we need to fix particle porosity at the solid inlet
    model2.fs.MB.particle_porosity[:, 1.0].fix()

    # Let's check the structural diagnostics again.
    dt = DiagnosticsToolbox(model2)
    dt.report_structural_issues()
    # Lood good!

    # Now let's try to solve
    model2.fs.MB.gas_phase.properties[:, 0].flow_mol.unfix()
    model2.fs.MB.gas_phase.properties[0, 0].flow_mol.fix()
    model2.fs.MB.solid_phase.properties[:, 1].flow_mass.unfix()
    model2.fs.MB.solid_phase.properties[0, 1].flow_mass.fix()
    model2.piecewise_constant_constraints.activate()

    attempt_solve(model2)


# Below are functions that can be used to construct the model at any point at
# which it may be interesting. These are used for testing.


def create_original_model():
    """Create the original model we attempt to solve"""
    model = make_model()
    return model


def create_original_square_model():
    """Create the model at the point at which the first diagnostic checks
    are run
    """
    model = make_model()
    model.fs.MB.gas_phase.properties[:, 0].flow_mol.fix()
    model.fs.MB.solid_phase.properties[:, 1].flow_mass.fix()
    model.piecewise_constant_constraints.deactivate()
    return model


def create_square_model_with_new_variable_and_constraint():
    model = make_model()
    porosity_param = model.fs.solid_properties.particle_porosity
    for t, x in model.fs.time * model.fs.MB.length_domain:
        substitution_map = {id(porosity_param): model.fs.MB.particle_porosity[t, x]}
        sp = model.fs.MB.solid_phase
        cons = [
            sp.properties[t, x].density_particle_constraint,
            sp.reactions[t, x].gen_rate_expression["R1"],
        ]
        for con in cons:
            con.set_value(
                replace_expressions(
                    con.expr,
                    substitution_map,
                    descend_into_named_expressions=True,
                )
            )

    # Add the constraint we are missing
    @model.fs.MB.Constraint(model.fs.time, model.fs.MB.length_domain)
    def density_flowrate_constraint(mb, t, x):
        return (
            mb.velocity_superficial_solid[t] * mb.bed_area
            * mb.solid_phase.properties[t, x].dens_mass_particle
            == mb.solid_phase.properties[t, x].flow_mass
        )
    return model


if __name__ == "__main__":
    main()
