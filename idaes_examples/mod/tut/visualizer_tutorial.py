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
"""
IDAES Visualizer Tutorial script

This runs the same code as the Jupyter notebook by the same name.
See that notebook for details.
"""
# stdlib
from io import StringIO
import logging
import re
import sys
import warnings
# NGCC
import pyomo.environ as pyo
import idaes
from idaes.core.util.model_statistics import degrees_of_freedom
from pyomo.environ import (Constraint,
                           Var,
                           ConcreteModel,
                           Expression,
                           Objective,
                           SolverFactory,
                           TransformationFactory,
                           value)
from pyomo.network import Arc, SequentialDecomposition
from idaes.core import FlowsheetBlock
from idaes.models.unit_models import (PressureChanger,
                                      Mixer,
                                      Separator as Splitter,
                                      Heater,
                                      StoichiometricReactor,
                                      Flash)
# Import thermodynamic and reaction property packages
from idaes_examples.mod.hda import hda_ideal_VLE as thermo_props
from idaes_examples.mod.hda import hda_reaction as reaction_props

from idaes.models.unit_models.pressure_changer import ThermodynamicAssumption
from idaes.core.util.model_statistics import degrees_of_freedom

try:
    import idaes_ui
except ImportError:
    print("*** ERROR ***\n"
          "Cannot import 'idaes_ui'.\n"
          "To install IDAES with the UI enabled, run:\n"
          "     pip install idaes-pse[ui]\n"
          "Until this module is installed, the visualizer will NOT work!")
    idaes_ui = None

# Import idaes logger to set output levels
import idaes.logger as idaeslog

_log = logging.getLogger(__name__)

__author__ = "Dan Gunter"  # GH: dangunter, email: dkgunter@lbl.gov


def quiet():
    """Make sure we don't get any spurious output.
    This should not really be this hard(?).
    """
    # Don't silence any warnings if the import failed
    if idaes_ui is None:
        return

    def remove_handlers(g):
        for h in g.handlers:
            g.removeHandler(h)

    for logname in "idaes", "idaes.solve", "idaes.solve.fs", \
            "idaes.init", "idaes.init.fs", "pyomo":
        logger = logging.getLogger(logname)
        remove_handlers(logger)
        logger.addHandler(logging.NullHandler())
        logger.propagate = False

    warnings.simplefilter("ignore")

def function_markdown(f):
    
    def find_indent(s):
        for i, c in enumerate(s):
            if c != " ":
                return i
        return -1

    def fixup(s):
        s = re.sub(r":\w+:(`.*`)", r"\1", s)
        return s
    
    raw_docstr = f.__doc__
    lines = raw_docstr.split("\n")
    state = "desc"
    rlines = []

    for i, line in enumerate(lines):
        sline = fixup(line.strip())
        if state == "desc":
            if sline:
                rlines.append(sline)
            else:
                state = "ext"
        elif  state == "ext":
            m = re.match(r"([a-zA-Z]+):", sline)
            if m:
                rlines.append(f"{m.group(1)}:")
                rlines.append("")
                state = "args0"
            else:
                rlines.append(sline)
        elif state == "args0":
            indent = find_indent(line)
            indent_spc = "  "
            rlines.append(indent_spc + "* " + sline)
            state = "args"
        elif state == "args":
            if not sline:
                state = "ext"
                rlines.append("")
            else:
                ind = find_indent(line)
                if ind == indent:
                    rlines.append(indent_spc + "* " + sline)
                else:
                    rlines.append(indent_spc + "  " + sline)
    body = "\n".join(rlines)
    return body


def create_model(second_flash=False) -> pyo.ConcreteModel:
    """# Create an IDAES flowsheet for hydrodealkylation (HDA)

## About HDA

Hydrodealkylation (HDA) is a chemical reaction that often involves reacting
an aromatic hydrocarbon in the presence of hydrogen gas to form a
simpler aromatic hydrocarbon devoid of functional groups. In this
example, toluene will be reacted with hydrogen gas at high temperatures
 to form benzene via the following reaction:

**C<sub>6</sub>H<sub>5</sub>CH<sub>3</sub> + H<sub>2</sub> → C<sub>6</sub>H<sub>6</sub> + CH<sub>4</sub>**

This reaction is often accompanied by an equilibrium side reaction
which forms diphenyl, which we will not cover in this example.

## References

This example is based on the 1967 AIChE Student Contest problem as
present by Douglas, J.M., Chemical  Design of Chemical Processes, 1988,
McGraw-Hill.
    """
    m = pyo.ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    m.fs.thermo_params = thermo_props.HDAParameterBlock()
    m.fs.reaction_params = reaction_props.HDAReactionParameterBlock(property_package=m.fs.thermo_params)
    m.fs.M101 = Mixer(property_package=m.fs.thermo_params, inlet_list=['toluene_feed', 'hydrogen_feed', 'vapor_recycle'])

    m.fs.H101 = Heater(property_package=m.fs.thermo_params, has_pressure_change=False, has_phase_equilibrium=True)
    m.fs.R101 = StoichiometricReactor(property_package=m.fs.thermo_params, reaction_package=m.fs.reaction_params, has_heat_of_reaction=True, has_heat_transfer=True, has_pressure_change=False)
    m.fs.F101 = Flash(property_package=m.fs.thermo_params, has_heat_transfer=True, has_pressure_change=True)
    m.fs.S101 = Splitter(property_package=m.fs.thermo_params, ideal_separation=False, outlet_list=['purge', 'recycle'])

    m.fs.C101 = PressureChanger(property_package=m.fs.thermo_params, compressor=True, thermodynamic_assumption=ThermodynamicAssumption.isothermal)

    if second_flash:
        m.fs.F102 = Flash(property_package=m.fs.thermo_params, has_heat_transfer=True, has_pressure_change=True)
    m.fs.s03 = Arc(source=m.fs.M101.outlet, destination=m.fs.H101.inlet)
    m.fs.s04 = Arc(source=m.fs.H101.outlet, destination=m.fs.R101.inlet)
    m.fs.s05 = Arc(source=m.fs.R101.outlet, destination=m.fs.F101.inlet)
    m.fs.s06 = Arc(source=m.fs.F101.vap_outlet, destination=m.fs.S101.inlet)
    m.fs.s08 = Arc(source=m.fs.S101.recycle, destination=m.fs.C101.inlet)
    m.fs.s09 = Arc(source=m.fs.C101.outlet,
                   destination=m.fs.M101.vapor_recycle)
    if second_flash:
        m.fs.s10 = Arc(source=m.fs.F101.liq_outlet, destination=m.fs.F102.inlet)
    TransformationFactory("network.expand_arcs").apply_to(m)
    if second_flash:
        m.fs.purity = Expression(
         expr=m.fs.F102.vap_outlet.flow_mol_phase_comp[0, "Vap", "benzene"] /
              (m.fs.F102.vap_outlet.flow_mol_phase_comp[0, "Vap", "benzene"]
               + m.fs.F102.vap_outlet.flow_mol_phase_comp[0, "Vap", "toluene"]))
    else:
        m.fs.purity = Expression(
        expr=m.fs.F101.vap_outlet.flow_mol_phase_comp[0, "Vap", "benzene"] /
             (m.fs.F101.vap_outlet.flow_mol_phase_comp[0, "Vap", "benzene"]
              + m.fs.F101.vap_outlet.flow_mol_phase_comp[0, "Vap", "toluene"]))
    m.fs.cooling_cost = Expression(expr=0.212e-7 * (-m.fs.F101.heat_duty[0]) +
                                        0.212e-7 * (-m.fs.R101.heat_duty[0]))
    if second_flash:
        m.fs.heating_cost = Expression(expr=2.2e-7 * m.fs.H101.heat_duty[0] +
                                          1.9e-7 * m.fs.F102.heat_duty[0])
    else:
        m.fs.heating_cost = Expression(expr=2.2e-7 * m.fs.H101.heat_duty[0] +
                                         1.9e-7 * m.fs.F101.heat_duty[0])
    m.fs.operating_cost = Expression(expr=(3600 * 24 * 365 *
                                           (m.fs.heating_cost +
                                            m.fs.cooling_cost)))
    return fix_initial_values(m, second_flash=second_flash)


def fix_initial_values(m: ConcreteModel, second_flash: bool = False) -> ConcreteModel:
    # fix toluene feed stream conditions
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "benzene"].fix(1e-5)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "toluene"].fix(1e-5)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "hydrogen"].fix(1e-5)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "methane"].fix(1e-5)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "benzene"].fix(1e-5)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "toluene"].fix(0.30)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "hydrogen"].fix(1e-5)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "methane"].fix(1e-5)
    m.fs.M101.toluene_feed.temperature.fix(303.2)
    m.fs.M101.toluene_feed.pressure.fix(350000)
    # fix H2 feed conditions
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "benzene"].fix(1e-5)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "toluene"].fix(1e-5)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "hydrogen"].fix(0.30)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "methane"].fix(0.02)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "benzene"].fix(1e-5)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "toluene"].fix(1e-5)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "hydrogen"].fix(1e-5)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "methane"].fix(1e-5)
    m.fs.M101.hydrogen_feed.temperature.fix(303.2)
    m.fs.M101.hydrogen_feed.pressure.fix(350000)
    # H101 outlet temp
    m.fs.H101.outlet.temperature.fix(600)
    # Stoichiometric reactor
    m.fs.R101.conversion = Var(initialize=0.75, bounds=(0, 1))

    m.fs.R101.conv_constraint = Constraint(
        expr=m.fs.R101.conversion * m.fs.R101.inlet.
            flow_mol_phase_comp[0, "Vap", "toluene"] ==
             (m.fs.R101.inlet.flow_mol_phase_comp[0, "Vap", "toluene"] -
              m.fs.R101.outlet.flow_mol_phase_comp[0, "Vap", "toluene"]))

    m.fs.R101.conversion.fix(0.75)
    m.fs.R101.heat_duty.fix(0)
    # Flash F101
    m.fs.F101.vap_outlet.temperature.fix(325.0)
    m.fs.F101.deltaP.fix(0)
    # Flash F102
    if second_flash:
        m.fs.F102.vap_outlet.temperature.fix(375)
        m.fs.F102.deltaP.fix(-200000)
    # Purge split fraction and compressor outlet
    m.fs.S101.split_fraction[0, "purge"].fix(0.2)
    m.fs.C101.outlet.pressure.fix(350000)

    # return model object
    return m


def initialize_model(m: ConcreteModel) -> ConcreteModel:
    # Use sequential decomposition
    seq = SequentialDecomposition()
    seq.options.select_tear_method = "heuristic"
    seq.options.tear_method = "Wegstein"
    seq.options.iterLim = 5
    # Using the SD tool
    G = seq.create_graph(m)
    heuristic_tear_set = seq.tear_set_arcs(G, method="heuristic")
    order = seq.calculation_order(G)
    # guesses
    tear_guesses = {
        "flow_mol_phase_comp": {
            (0, "Vap", "benzene"): 1e-5,
            (0, "Vap", "toluene"): 1e-5,
            (0, "Vap", "hydrogen"): 0.30,
            (0, "Vap", "methane"): 0.02,
            (0, "Liq", "benzene"): 1e-5,
            (0, "Liq", "toluene"): 0.30,
            (0, "Liq", "hydrogen"): 1e-5,
            (0, "Liq", "methane"): 1e-5},
        "temperature": {0: 303},
        "pressure": {0: 350000}}

    # Pass the tear_guess to the SD tool
    seq.set_guesses_for(m.fs.H101.inlet, tear_guesses)

    def initialize_unit(unit):
        unit.initialize(outlvl=idaeslog.DEBUG)

    seq.run(m, initialize_unit)
    return m


def solve_model(m: ConcreteModel):
    # Get solver
    solver = SolverFactory('ipopt')
    solver.options = {'tol': 1e-6, 'max_iter': 5000}
    # Solve the model
    results = solver.solve(m, tee=False)
    return results


def optimize_model(m: ConcreteModel):
    pass


def main():
    m = create_model()
    result = solve_model(initialize_model(m))
    print(f"Solver result: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

