from pyomo.environ import (
    Constraint,
    Var,
    ConcreteModel,
    Expression,
    Objective,
    TransformationFactory,
    value,
)
from pyomo.network import Arc
from idaes.core import FlowsheetBlock
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.core.solvers import get_solver

from idaes.models.unit_models import (
    PressureChanger,
    Mixer,
    Separator as Splitter,
    Heater,
    StoichiometricReactor,
    Feed,
    Product,
    Flash,
)
from idaes.models.unit_models.pressure_changer import ThermodynamicAssumption
from idaes.models.properties.modular_properties.base.generic_property import (
    GenericParameterBlock,
)
from idaes.models.properties.modular_properties.base.generic_reaction import (
    GenericReactionParameterBlock,
)

from idaes_examples.mod.hda.hda_ideal_VLE_modular import thermo_config
from idaes_examples.mod.hda.hda_reaction_modular import reaction_config
from idaes_examples.mod.hda.hda_flowsheet_extras import manual_propagation, automatic_propagation, fix_inlet_states


if __name__ == "__main__":
    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)

    m.fs.thermo_params = GenericParameterBlock(**thermo_config)
    m.fs.reaction_params = GenericReactionParameterBlock(
        property_package=m.fs.thermo_params, **reaction_config
    )

    m.fs.I101 = Feed(property_package=m.fs.thermo_params)
    m.fs.I102 = Feed(property_package=m.fs.thermo_params)

    m.fs.M101 = Mixer(
        property_package=m.fs.thermo_params,
        num_inlets=3,
    )

    m.fs.H101 = Heater(
        property_package=m.fs.thermo_params,
        has_pressure_change=False,
        has_phase_equilibrium=True,
    )

    m.fs.R101 = StoichiometricReactor(
        property_package=m.fs.thermo_params,
        reaction_package=m.fs.reaction_params,
        has_heat_of_reaction=True,
        has_heat_transfer=True,
        has_pressure_change=False,
    )

    m.fs.F101 = Flash(
        property_package=m.fs.thermo_params,
        has_heat_transfer=True,
        has_pressure_change=True,
    )

    m.fs.S101 = Splitter(
        property_package=m.fs.thermo_params,
        ideal_separation=False,
        outlet_list=["purge", "recycle"],
    )

    m.fs.C101 = PressureChanger(
        property_package=m.fs.thermo_params,
        compressor=True,
        thermodynamic_assumption=ThermodynamicAssumption.isothermal,
    )

    m.fs.F102 = Flash(
        property_package=m.fs.thermo_params,
        has_heat_transfer=True,
        has_pressure_change=True,
    )

    m.fs.P101 = Product(property_package=m.fs.thermo_params)
    m.fs.P102 = Product(property_package=m.fs.thermo_params)
    m.fs.P103 = Product(property_package=m.fs.thermo_params)

    m.fs.s01 = Arc(source=m.fs.I101.outlet, destination=m.fs.M101.inlet_1)
    m.fs.s02 = Arc(source=m.fs.I102.outlet, destination=m.fs.M101.inlet_2)
    m.fs.s03 = Arc(source=m.fs.M101.outlet, destination=m.fs.H101.inlet)
    m.fs.s04 = Arc(source=m.fs.H101.outlet, destination=m.fs.R101.inlet)
    m.fs.s05 = Arc(source=m.fs.R101.outlet, destination=m.fs.F101.inlet)
    m.fs.s06 = Arc(source=m.fs.F101.vap_outlet, destination=m.fs.S101.inlet)
    m.fs.s07 = Arc(source=m.fs.F101.liq_outlet, destination=m.fs.F102.inlet)
    m.fs.s08 = Arc(source=m.fs.S101.recycle, destination=m.fs.C101.inlet)
    m.fs.s09 = Arc(source=m.fs.C101.outlet, destination=m.fs.M101.inlet_3)
    m.fs.s10 = Arc(source=m.fs.F102.vap_outlet, destination=m.fs.P101.inlet)
    m.fs.s11 = Arc(source=m.fs.F102.liq_outlet, destination=m.fs.P102.inlet)
    m.fs.s12 = Arc(source=m.fs.S101.purge, destination=m.fs.P103.inlet)

    TransformationFactory("network.expand_arcs").apply_to(m)

    m.fs.purity = Expression(
        expr=m.fs.F102.control_volume.properties_out[0].flow_mol_phase_comp[
                 "Vap", "benzene"
             ]
             / (
                     m.fs.F102.control_volume.properties_out[0].flow_mol_phase_comp["Vap", "benzene"]
                     + m.fs.F102.control_volume.properties_out[0].flow_mol_phase_comp[
                         "Vap", "toluene"
                     ]
             )
    )

    m.fs.cooling_cost = Expression(
        expr=0.212e-7 * (-m.fs.F101.heat_duty[0]) + 0.212e-7 * (-m.fs.R101.heat_duty[0])
    )

    m.fs.heating_cost = Expression(
        expr=2.2e-7 * m.fs.H101.heat_duty[0] + 1.9e-7 * m.fs.F102.heat_duty[0]
    )

    m.fs.operating_cost = Expression(
        expr=(3600 * 24 * 365 * (m.fs.heating_cost + m.fs.cooling_cost))
    )

    assert degrees_of_freedom(m) == 29

    tear_guesses = fix_inlet_states(m)

    m.fs.H101.outlet.temperature.fix(600)

    m.fs.R101.control_volume.conversion = Var(initialize=0.75, bounds=(0, 1))

    m.fs.R101.conv_constraint = Constraint(
        expr=m.fs.R101.control_volume.conversion
             * (m.fs.R101.control_volume.properties_in[0].flow_mol_phase_comp["Vap", "toluene"])
             == (
                     m.fs.R101.control_volume.properties_in[0].flow_mol_phase_comp["Vap", "toluene"] -
                     m.fs.R101.control_volume.properties_out[0].flow_mol_phase_comp["Vap", "toluene"])
    )

    m.fs.R101.control_volume.conversion.fix(0.75)
    m.fs.R101.heat_duty.fix(0.0)

    m.fs.F101.vap_outlet.temperature.fix(325.0)
    m.fs.F101.deltaP.fix(0.0)

    m.fs.F102.vap_outlet.temperature.fix(375)
    m.fs.F102.deltaP.fix(-200000)

    m.fs.S101.split_fraction[0, "purge"].fix(0.2)
    m.fs.C101.outlet.pressure.fix(350000)

    # automatic_propagation(m, tear_guesses)
    manual_propagation(m, tear_guesses)

    optarg = {
        "nlp_scaling_method": "user-scaling",
        "OF_ma57_automatic_scaling": "yes",
        "max_iter": 1000,
        "tol": 1e-8,
    }

    solver = get_solver("ipopt_v2", options=optarg)

    # Solve the model
    results = solver.solve(m, tee=False)

    from pyomo.environ import TerminationCondition

    assert results.solver.termination_condition == TerminationCondition.optimal

    print("operating cost = $", value(m.fs.operating_cost))

    import pytest

    print("benzene purity = ", value(m.fs.purity))

    assert value(m.fs.purity) == pytest.approx(0.82429, abs=1e-3)

    assert value(m.fs.F102.heat_duty[0]) == pytest.approx(7346.67441, abs=1e-3)
    assert value(m.fs.F102.vap_outlet.pressure[0]) == pytest.approx(1.5000e05, abs=1e-3)

    m.fs.objective = Objective(expr=m.fs.operating_cost)

    m.fs.H101.outlet.temperature.unfix()
    m.fs.R101.heat_duty.unfix()
    m.fs.F101.vap_outlet.temperature.unfix()
    m.fs.F102.vap_outlet.temperature.unfix()

    m.fs.F102.deltaP.unfix()

    assert degrees_of_freedom(m) == 5

    m.fs.H101.outlet.temperature[0].setlb(500)
    m.fs.H101.outlet.temperature[0].setub(600)

    m.fs.R101.outlet.temperature[0].setlb(600)
    m.fs.R101.outlet.temperature[0].setub(800)

    m.fs.F101.vap_outlet.temperature[0].setlb(298.0)
    m.fs.F101.vap_outlet.temperature[0].setub(450.0)
    m.fs.F102.vap_outlet.temperature[0].setlb(298.0)
    m.fs.F102.vap_outlet.temperature[0].setub(450.0)
    m.fs.F102.vap_outlet.pressure[0].setlb(105000)
    m.fs.F102.vap_outlet.pressure[0].setub(110000)

    m.fs.overhead_loss = Constraint(
        expr=m.fs.F101.control_volume.properties_out[0].flow_mol_phase_comp["Vap", "benzene"] <= 0.20
             * m.fs.R101.control_volume.properties_out[0].flow_mol_phase_comp["Vap", "benzene"]
    )

    m.fs.product_flow = Constraint(
        expr=m.fs.F102.control_volume.properties_out[0].flow_mol_phase_comp[
                 "Vap", "benzene"
             ]
             >= 0.15
    )

    m.fs.product_purity = Constraint(expr=m.fs.purity >= 0.80)

    results = solver.solve(m, tee=False)

    # Check for solver solve status
    from pyomo.environ import TerminationCondition

    assert results.solver.termination_condition == TerminationCondition.optimal

    print("operating cost = $", value(m.fs.operating_cost))

    print()
    print("Product flow rate and purity in F102")
    m.fs.F102.report()

    print()
    print("benzene purity = ", value(m.fs.purity))

    print()
    print("Overhead loss in F101")
    m.fs.F101.report()

    #
    assert value(m.fs.operating_cost) == pytest.approx(312674.236, abs=1e-3)
    assert value(m.fs.purity) == pytest.approx(0.818827, abs=1e-3)

    print(
        f"""Optimal Values:

    H101 outlet temperature = {value(m.fs.H101.outlet.temperature[0]):.3f} K

    R101 outlet temperature = {value(m.fs.R101.outlet.temperature[0]):.3f} K

    F101 outlet temperature = {value(m.fs.F101.vap_outlet.temperature[0]):.3f} K

    F102 outlet temperature = {value(m.fs.F102.vap_outlet.temperature[0]):.3f} K
    F102 outlet pressure = {value(m.fs.F102.vap_outlet.pressure[0]):.3f} Pa
    """
    )

    assert value(m.fs.H101.outlet.temperature[0]) == pytest.approx(500, abs=1e-3)
    # assert value(m.fs.R101.outlet.temperature[0]) == pytest.approx(862.907, abs=1e-3)
    assert value(m.fs.F101.vap_outlet.temperature[0]) == pytest.approx(301.881, abs=1e-3)
    assert value(m.fs.F102.vap_outlet.temperature[0]) == pytest.approx(362.935, abs=1e-3)
    assert value(m.fs.F102.vap_outlet.pressure[0]) == pytest.approx(105000, abs=1e-2)
