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
Flowsheets for HDA with Flash and HDA with Distillation for costing notebook.
"""

# Import Pyomo libraries
from pyomo.environ import (Constraint,
                           Var,
                           Param,
                           Expression,
                           ConcreteModel,
                           SolverFactory,
                           TransformationFactory,
                           units as pyunits,
                           TerminationCondition)
from pyomo.network import Arc, SequentialDecomposition

# Import IDAES core libraries
from idaes.core import FlowsheetBlock

# Import IDAES generic unit models
from idaes.models.unit_models import (PressureChanger,
                                      Mixer,
                                      Separator as Splitter,
                                      Heater,
                                      StoichiometricReactor,
                                      CSTR,
                                      Flash,
                                      Translator)
from idaes.models.unit_models.pressure_changer import \
    ThermodynamicAssumption

# Import IDAES distillation unit models
from idaes.models_extra.column_models.tray_column import TrayColumn
from idaes.models_extra.column_models.condenser import \
    CondenserType, TemperatureSpec

# Import IDAES core utilities
from idaes.core.util.initialization import propagate_state
from idaes.core.solvers import get_solver
import idaes.core.util.scaling as iscale
from pyomo.util.check_units import assert_units_consistent
from idaes.core.util.model_statistics import degrees_of_freedom

# Import costing methods - classes, heaters, vessels, compressors, columns
from idaes.models.costing.SSLW import (
    SSLWCosting,
    SSLWCostingData,
    VesselMaterial,
    TrayType,
    TrayMaterial,
    HeaterMaterial,
    HeaterSource,
)
from idaes.core import UnitModelCostingBlock

# Import idaes logger to set output levels
import idaes.logger as idaeslog
from idaes.core.util.constants import Constants

import sys
import os


def hda_with_flash(tee=True):
    if tee is True:
        outlvl = idaeslog.INFO
    else:
        outlvl = idaeslog.ERROR

    # Import thermodynamic and reaction property packages
    from idaes_examples.mod.hda import hda_ideal_VLE as thermo_props
    from idaes_examples.mod.hda import hda_reaction as reaction_props

    # build flowsheet
    print('Building flowsheet...')
    print()

    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)

    m.fs.thermo_params = thermo_props.HDAParameterBlock()
    m.fs.reaction_params = reaction_props.HDAReactionParameterBlock(
        property_package=m.fs.thermo_params)

    m.fs.M101 = Mixer(property_package=m.fs.thermo_params,
                      inlet_list=["toluene_feed", "hydrogen_feed",
                                  "vapor_recycle"])
    m.fs.H101 = Heater(property_package=m.fs.thermo_params,
                       has_pressure_change=False,
                       has_phase_equilibrium=True)
    m.fs.R101 = StoichiometricReactor(
                property_package=m.fs.thermo_params,
                reaction_package=m.fs.reaction_params,
                has_heat_of_reaction=True,
                has_heat_transfer=True,
                has_pressure_change=False)
    m.fs.F101 = Flash(property_package=m.fs.thermo_params,
                      has_heat_transfer=True,
                      has_pressure_change=True)
    m.fs.S101 = Splitter(property_package=m.fs.thermo_params,
                         ideal_separation=False,
                         outlet_list=["purge", "recycle"])
    m.fs.C101 = PressureChanger(
        property_package=m.fs.thermo_params,
        compressor=True,
        thermodynamic_assumption=ThermodynamicAssumption.isothermal)
    m.fs.F102 = Flash(property_package=m.fs.thermo_params,
                      has_heat_transfer=True,
                      has_pressure_change=True)

    m.fs.s03 = Arc(source=m.fs.M101.outlet, destination=m.fs.H101.inlet)
    m.fs.s04 = Arc(source=m.fs.H101.outlet, destination=m.fs.R101.inlet)
    m.fs.s05 = Arc(source=m.fs.R101.outlet, destination=m.fs.F101.inlet)
    m.fs.s06 = Arc(source=m.fs.F101.vap_outlet, destination=m.fs.S101.inlet)
    m.fs.s08 = Arc(source=m.fs.S101.recycle, destination=m.fs.C101.inlet)
    m.fs.s09 = Arc(source=m.fs.C101.outlet,
                   destination=m.fs.M101.vapor_recycle)
    m.fs.s10 = Arc(source=m.fs.F101.liq_outlet, destination=m.fs.F102.inlet)

    TransformationFactory("network.expand_arcs").apply_to(m)

    # set inputs
    print('Setting inputs...')
    print()

    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "benzene"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "toluene"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "hydrogen"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "methane"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "benzene"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "toluene"].fix(0.30*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "hydrogen"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "methane"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.temperature.fix(303.2*pyunits.K)
    m.fs.M101.toluene_feed.pressure.fix(350000*pyunits.Pa)

    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "benzene"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "toluene"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "hydrogen"].fix(0.30*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "methane"].fix(0.02*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "benzene"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "toluene"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "hydrogen"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "methane"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.temperature.fix(303.2*pyunits.K)
    m.fs.M101.hydrogen_feed.pressure.fix(350000*pyunits.Pa)

    m.fs.H101.outlet.temperature.fix(600*pyunits.K)

    m.fs.R101.conversion = Var(initialize=0.75, bounds=(0, 1))

    m.fs.R101.conv_constraint = Constraint(
        expr=m.fs.R101.conversion*m.fs.R101.inlet.
        flow_mol_phase_comp[0, "Vap", "toluene"] ==
        (m.fs.R101.inlet.flow_mol_phase_comp[0, "Vap", "toluene"] -
         m.fs.R101.outlet.flow_mol_phase_comp[0, "Vap", "toluene"]))

    m.fs.R101.conversion.fix(0.75*pyunits.dimensionless)
    m.fs.R101.heat_duty.fix(0*pyunits.W)

    m.fs.F101.vap_outlet.temperature.fix(325.0*pyunits.K)
    m.fs.F101.deltaP.fix(0*pyunits.Pa)

    m.fs.F102.vap_outlet.temperature.fix(375*pyunits.K)
    m.fs.F102.deltaP.fix(-200000*pyunits.Pa)

    m.fs.S101.split_fraction[0, "purge"].fix(0.2)
    m.fs.C101.outlet.pressure.fix(350000*pyunits.Pa)

    # initialize flowsheet
    print('Initializing flowsheet...')
    print()

    seq = SequentialDecomposition()
    seq.options.select_tear_method = "heuristic"
    seq.options.tear_method = "Wegstein"
    seq.options.iterLim = 3
    print('Limiting Wegstein tear to 3 iterations to obtain initial solution,'
          ' if not converged IPOPT will pick up and continue.')
    print()

    G = seq.create_graph(m)
    heuristic_tear_set = seq.tear_set_arcs(G, method="heuristic")
    order = seq.calculation_order(G)
    if tee is True:
        for o in heuristic_tear_set:
            print(o.name)
        for o in order:
            print(o[0].name)

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

    seq.set_guesses_for(m.fs.H101.inlet, tear_guesses)

    def function(unit):
        unit.initialize(outlvl=outlvl)

    seq.run(m, function)

    # solve model
    print('Solving flowsheet...')
    print()

    solver = SolverFactory('ipopt')
    solver.options = {'tol': 1e-6, 'max_iter': 5000}
    results = solver.solve(m, tee=tee)
    assert results.solver.termination_condition == TerminationCondition.optimal
    assert_units_consistent(m)

    print('Complete.')
    print()

    return m


def hda_with_distillation(tee=True):
    if tee is True:
        outlvl = idaeslog.INFO
    else:
        outlvl = idaeslog.ERROR

    # Import thermodynamic and reaction property packages
    from idaes_examples.mod.hda import hda_reaction as reaction_props
    from idaes.models.properties.activity_coeff_models.\
        BTX_activity_coeff_VLE import BTXParameterBlock
    from idaes_examples.mod.hda.hda_ideal_VLE import HDAParameterBlock

    # build flowsheet
    print('Building flowsheet...')
    print()

    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)

    m.fs.BTHM_params = HDAParameterBlock()
    m.fs.BT_params = BTXParameterBlock(
        valid_phase=('Liq', 'Vap'),
        activity_coeff_model="Ideal"
        )
    m.fs.reaction_params = reaction_props.HDAReactionParameterBlock(
        property_package=m.fs.BTHM_params)

    m.fs.M101 = Mixer(property_package=m.fs.BTHM_params,
                      inlet_list=["toluene_feed", "hydrogen_feed",
                                  "vapor_recycle"])
    m.fs.H101 = Heater(property_package=m.fs.BTHM_params,
                       has_phase_equilibrium=True)
    m.fs.R101 = CSTR(
            property_package=m.fs.BTHM_params,
            reaction_package=m.fs.reaction_params,
            has_heat_of_reaction=True,
            has_heat_transfer=True)
    m.fs.F101 = Flash(property_package=m.fs.BTHM_params,
                      has_heat_transfer=True,
                      has_pressure_change=True)
    m.fs.S101 = Splitter(property_package=m.fs.BTHM_params,
                         outlet_list=["purge", "recycle"])
    m.fs.C101 = PressureChanger(
                property_package=m.fs.BTHM_params,
                compressor=True,
                thermodynamic_assumption=ThermodynamicAssumption.isothermal)
    m.fs.translator = Translator(
        inlet_property_package=m.fs.BTHM_params,
        outlet_property_package=m.fs.BT_params
        )

    # Add constraint: Total flow = benzene flow + toluene flow (molar)
    m.fs.translator.eq_total_flow = Constraint(
        expr=m.fs.translator.outlet.flow_mol[0] ==
        m.fs.translator.inlet.flow_mol_phase_comp[0, "Liq", "benzene"] +
        m.fs.translator.inlet.flow_mol_phase_comp[0, "Liq", "toluene"])

    # Add constraint: Outlet temperature = Inlet temperature
    m.fs.translator.eq_temperature = Constraint(
        expr=m.fs.translator.outlet.temperature[0] ==
        m.fs.translator.inlet.temperature[0])

    m.fs.translator.eq_pressure = Constraint(
        expr=m.fs.translator.outlet.pressure[0] ==
        m.fs.translator.inlet.pressure[0])

    # Add constraint: Benzene mole fraction definition
    m.fs.translator.eq_mole_frac_benzene = Constraint(
        expr=m.fs.translator.outlet.mole_frac_comp[0, "benzene"] ==
        m.fs.translator.inlet.flow_mol_phase_comp[0, "Liq", "benzene"] /
        (m.fs.translator.inlet.flow_mol_phase_comp[0, "Liq", "benzene"] +
         m.fs.translator.inlet.flow_mol_phase_comp[0, "Liq", "toluene"]))

    # Add constraint: Toluene mole fraction definition
    m.fs.translator.eq_mole_frac_toluene = Constraint(
        expr=m.fs.translator.outlet.mole_frac_comp[0, "toluene"] ==
        m.fs.translator.inlet.flow_mol_phase_comp[0, "Liq", "toluene"] /
        (m.fs.translator.inlet.flow_mol_phase_comp[0, "Liq", "benzene"] +
         m.fs.translator.inlet.flow_mol_phase_comp[0, "Liq", "toluene"]))

    m.fs.H102 = Heater(property_package=m.fs.BT_params,
                       has_pressure_change=True,
                       has_phase_equilibrium=True)

    m.fs.s03 = Arc(source=m.fs.M101.outlet, destination=m.fs.H101.inlet)
    m.fs.s04 = Arc(source=m.fs.H101.outlet, destination=m.fs.R101.inlet)
    m.fs.s05 = Arc(source=m.fs.R101.outlet, destination=m.fs.F101.inlet)
    m.fs.s06 = Arc(source=m.fs.F101.vap_outlet, destination=m.fs.S101.inlet)
    m.fs.s08 = Arc(source=m.fs.S101.recycle, destination=m.fs.C101.inlet)
    m.fs.s09 = Arc(source=m.fs.C101.outlet,
                   destination=m.fs.M101.vapor_recycle)
    m.fs.s10a = Arc(source=m.fs.F101.liq_outlet,
                    destination=m.fs.translator.inlet)
    m.fs.s10b = Arc(source=m.fs.translator.outlet, destination=m.fs.H102.inlet)

    TransformationFactory("network.expand_arcs").apply_to(m)

    # set inputs
    print('Setting inputs...')
    print()

    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "benzene"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "toluene"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "hydrogen"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "methane"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "benzene"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "toluene"].fix(0.30*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "hydrogen"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "methane"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.toluene_feed.temperature.fix(303.2*pyunits.K)
    m.fs.M101.toluene_feed.pressure.fix(350000*pyunits.Pa)

    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "benzene"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "toluene"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "hydrogen"].fix(0.30*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "methane"].fix(0.02*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "benzene"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "toluene"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "hydrogen"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "methane"].fix(1e-5*pyunits.mol/pyunits.s)
    m.fs.M101.hydrogen_feed.temperature.fix(303.2*pyunits.K)
    m.fs.M101.hydrogen_feed.pressure.fix(350000*pyunits.Pa)

    m.fs.H101.outlet.temperature.fix(600*pyunits.K)

    m.fs.R101.conversion = Var(initialize=0.75, bounds=(0, 1))

    m.fs.R101.conv_constraint = Constraint(
        expr=m.fs.R101.conversion*m.fs.R101.inlet.
        flow_mol_phase_comp[0, "Vap", "toluene"] ==
        (m.fs.R101.inlet.flow_mol_phase_comp[0, "Vap", "toluene"] -
         m.fs.R101.outlet.flow_mol_phase_comp[0, "Vap", "toluene"]))

    m.fs.R101.conversion.fix(0.75*pyunits.dimensionless)
    m.fs.R101.heat_duty.fix(0*pyunits.W)

    m.fs.F101.vap_outlet.temperature.fix(325.0*pyunits.K)
    m.fs.F101.deltaP.fix(0*pyunits.Pa)

    m.fs.S101.split_fraction[0, "purge"].fix(0.2)
    m.fs.C101.outlet.pressure.fix(350000*pyunits.Pa)

    m.fs.H102.outlet.temperature.fix(375*pyunits.K)
    m.fs.H102.deltaP.fix(-200000*pyunits.Pa)

    # set scaling factors
    # Set scaling factors for heat duty, reaction extent and volume
    iscale.set_scaling_factor(m.fs.H101.control_volume.heat, 1e-2)
    iscale.set_scaling_factor(m.fs.R101.control_volume.heat, 1e-2)
    iscale.set_scaling_factor(m.fs.R101.control_volume.rate_reaction_extent, 1)
    iscale.set_scaling_factor(m.fs.R101.control_volume.volume, 1)
    iscale.set_scaling_factor(m.fs.F101.control_volume.heat, 1e-2)
    iscale.set_scaling_factor(m.fs.H102.control_volume.heat, 1e-2)

    # Set the scaling factors for the remaining variables and all constraints
    iscale.calculate_scaling_factors(m.fs.H101)
    iscale.calculate_scaling_factors(m.fs.R101)
    iscale.calculate_scaling_factors(m.fs.F101)
    iscale.calculate_scaling_factors(m.fs.H102)

    # initialize flowsheet
    print('Initializing flowsheet...')
    print()

    seq = SequentialDecomposition()
    seq.options.select_tear_method = "heuristic"
    seq.options.tear_method = "Wegstein"
    seq.options.iterLim = 3
    print('Limiting Wegstein tear to 3 iterations to obtain initial solution,'
          ' if not converged IPOPT will pick up and continue.')
    print()

    G = seq.create_graph(m)
    heuristic_tear_set = seq.tear_set_arcs(G, method="heuristic")
    order = seq.calculation_order(G)
    if tee is True:
        for o in heuristic_tear_set:
            print(o.name)
        for o in order:
            print(o[0].name)

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

    seq.set_guesses_for(m.fs.H101.inlet, tear_guesses)

    def function(unit):
        unit.initialize(outlvl=outlvl)

    seq.run(m, function)

    # solve model
    print('Solving flowsheet...')
    print()

    solver = get_solver()
    results = solver.solve(m, tee=tee)
    assert results.solver.termination_condition == TerminationCondition.optimal

    # add and initialize distilation column, and resolve
    print('Adding distillation column and resolving flowsheet...')
    print()

    from pyomo.common.log import LoggingIntercept
    import logging
    from io import StringIO
    stream = StringIO()
    with LoggingIntercept(stream, "pyomo.core", logging.WARNING):
        m.fs.D101 = TrayColumn(
                            number_of_trays=10,
                            feed_tray_location=5,
                            condenser_type=CondenserType.totalCondenser,
                            condenser_temperature_spec=TemperatureSpec.atBubblePoint,
                            property_package=m.fs.BT_params)

    m.fs.s11 = Arc(source=m.fs.H102.outlet, destination=m.fs.D101.feed)

    TransformationFactory("network.expand_arcs").apply_to(m)

    propagate_state(m.fs.s11)

    m.fs.D101.condenser.reflux_ratio.fix(0.5*pyunits.dimensionless)
    m.fs.D101.reboiler.boilup_ratio.fix(0.5*pyunits.dimensionless)
    m.fs.D101.condenser.condenser_pressure.fix(150000*pyunits.Pa)

    # set scaling factors
    # Set scaling factors for heat duty
    iscale.set_scaling_factor(m.fs.D101.condenser.control_volume.heat, 1e-2)
    iscale.set_scaling_factor(m.fs.D101.reboiler.control_volume.heat, 1e-2)

    # Set the scaling factors for the remaining variables and all constraints
    iscale.calculate_scaling_factors(m.fs.D101)

    m.fs.D101.initialize(outlvl=outlvl)
    results = solver.solve(m, tee=tee)
    assert results.solver.termination_condition == TerminationCondition.optimal
    assert_units_consistent(m)

    print('Complete.')
    print()

    # adding operating cost expressions

    # operating costs for HDA with distillation (model n)
    m.fs.cooling_cost = Expression(
        expr=0.25e-7 * (-m.fs.F101.heat_duty[0]) +
        0.2e-7 * (-m.fs.D101.condenser.heat_duty[0]))

    m.fs.heating_cost = Expression(
        expr=2.2e-7 * m.fs.H101.heat_duty[0] +
        1.2e-7 * m.fs.H102.heat_duty[0] +
        1.9e-7 * m.fs.D101.reboiler.heat_duty[0])

    m.fs.operating_cost = Expression(
        expr=(3600 * 24 * 365 * (m.fs.heating_cost + m.fs.cooling_cost)))

    # costing block
    m.fs.costing = SSLWCosting()

    # costing for heaters - m.fs.H101, m.fs.H101, m.fs.H102

    # loop over units
    for unit in [m.fs.H101, m.fs.H102]:
        unit.costing = UnitModelCostingBlock(
            flowsheet_costing_block=unit.parent_block().costing,
            costing_method=SSLWCostingData.cost_fired_heater,
            costing_method_arguments={
                    "material_type": HeaterMaterial.CarbonSteel,
                    "heat_source": HeaterSource.Fuel,
                }
        )

    # map unit models to unit classes
    # will pass to unit_mapping which calls costing methods based on unit class
    unit_class_mapping = {m.fs.R101: CSTR,
                          m.fs.F101: Flash}

    # costing for vessels - m.fs.R101, m.fs.F101

    # loop over units
    for unit in [m.fs.R101, m.fs.F101]:
        # get correct unit class for unit model
        unit_class = unit_class_mapping[unit]

        # add dimension variables and constraint if they don't exist
        if not hasattr(unit, "diameter"):
            unit.diameter = Var(initialize=1, units=pyunits.m)
        if not hasattr(unit, "length"):
            unit.length = Var(initialize=1, units=pyunits.m)
        if hasattr(unit, "volume"):  # if vol exists, set diameter from vol
            unit.volume_eq = Constraint(
                expr=unit.volume[0] == unit.length * unit.diameter**2
                * 0.25 * Constants.pi)
        else:  # fix diameter directly
            unit.diameter.fix(0.2214 * pyunits.m)
        # either way, fix L/D to calculate L from D
        unit.L_over_D = Constraint(expr=unit.length == 3 * unit.diameter)

        # define vessel costing
        unit.costing = UnitModelCostingBlock(
            flowsheet_costing_block=unit.parent_block().costing,
            costing_method=SSLWCostingData.unit_mapping[unit_class],
            costing_method_arguments={
                    "material_type": VesselMaterial.CarbonSteel,
                    "shell_thickness": 1.25 * pyunits.inch

                }
        )

    # costing for column - m.fs.D101

    # define column dimensions - same volume as m.fs.F102 with L/D of 5
    m.fs.D101.diameter = Param(initialize=0.1715, units=pyunits.m)
    m.fs.D101.length = Param(initialize=0.8575, units=pyunits.m)

    m.fs.D101.costing = UnitModelCostingBlock(
            flowsheet_costing_block=m.fs.costing,
            costing_method=SSLWCostingData.cost_vertical_vessel,
            costing_method_arguments={
                    "material_type": VesselMaterial.CarbonSteel,
                    "shell_thickness": 1.25 * pyunits.inch,
                    "include_platforms_ladders": True,
                    "number_of_trays": m.fs.D101.config.number_of_trays,
                    "tray_material": TrayMaterial.CarbonSteel,
                    "tray_type": TrayType.Sieve

                }
        )

    # Check that the degrees of freedom is zero
    assert degrees_of_freedom(m) == 0

    # define solver

    assert_units_consistent(m)
    results = solver.solve(m, tee=tee, symbolic_solver_labels=True)
    assert results.solver.termination_condition == TerminationCondition.optimal
    return m
