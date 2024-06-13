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
Author: Brandon Paul
"""
import pytest
from pyomo.environ import (
    assert_optimal_termination,
    ConcreteModel,
    Set,
    value,
    Var,
    units as pyunits,
    as_quantity
)
from pyomo.common.unittest import assertStructuredAlmostEqual

from idaes.core import Component
from idaes.core.util.model_statistics import (
    degrees_of_freedom,
    fixed_variables_set,
    activated_constraints_set,
)
from idaes.core.solvers import get_solver

from idaes.models.properties.modular_properties.base.generic_property import (
    GenericParameterBlock,
)

from idaes.models.properties.modular_properties.state_definitions import FpcTP

from idaes_examples.notebooks.docs.unit_models.reactors.egprod_ideal import config_dict

from idaes.models.properties.tests.test_harness import PropertyTestHarness

from idaes.core.util.model_diagnostics import DiagnosticsToolbox


# -----------------------------------------------------------------------------
# Get default solver for testing
solver = get_solver()


class TestEGProdIdeal(PropertyTestHarness):
    def configure(self):
        self.prop_pack = GenericParameterBlock
        self.param_args = config_dict
        self.prop_args = {}
        self.has_density_terms = True


class TestParamBlock(object):
    @pytest.mark.unit
    def test_build(self):
        model = ConcreteModel()
        model.params = GenericParameterBlock(**config_dict)

        assert isinstance(model.params.phase_list, Set)
        assert len(model.params.phase_list) == 1
        for i in model.params.phase_list:
            assert i in ["Liq",]
        assert model.params.Liq.is_liquid_phase()

        assert isinstance(model.params.component_list, Set)
        assert len(model.params.component_list) == 4
        for i in model.params.component_list:
            assert i in ["ethylene_oxide", "water", "sulfuric_acid", "ethylene_glycol"]
            assert isinstance(model.params.get_component(i), Component)

        assert isinstance(model.params._phase_component_set, Set)
        assert len(model.params._phase_component_set) == 4
        for i in model.params._phase_component_set:
            assert i in [
                ("Liq", "ethylene_oxide"),
                ("Liq", "water"),
                ("Liq", "sulfuric_acid"),
                ("Liq", "ethylene_glycol"),
            ]

        assert model.params.config.state_definition == FpcTP

        assertStructuredAlmostEqual(
            model.params.config.state_bounds,
            {
                "flow_mol_phase_comp": (0, 100, 1000, pyunits.mol / pyunits.s),
                "temperature": (273.15, 298.15, 450, pyunits.K),
                "pressure": (5e4, 1e5, 1e6, pyunits.Pa),
            },
            item_callback=as_quantity,
        )

        assert value(model.params.pressure_ref) == 1e5
        assert value(model.params.temperature_ref) == 298.15

        assert value(model.params.ethylene_oxide.mw) == 44.054e-3
        assert value(model.params.ethylene_oxide.pressure_crit) == 71.9e5
        assert value(model.params.ethylene_oxide.temperature_crit) == 469

        assert value(model.params.water.mw) == 18.015e-3
        assert value(model.params.water.pressure_crit) == 221.2e5
        assert value(model.params.water.temperature_crit) == 647.3

        assert value(model.params.sulfuric_acid.mw) == 98.08e-3
        assert value(model.params.sulfuric_acid.pressure_crit) == 129.4262e5
        assert value(model.params.sulfuric_acid.temperature_crit) == 590.76

        assert value(model.params.ethylene_glycol.mw) == 62.069e-3
        assert value(model.params.ethylene_glycol.pressure_crit) == 77e5
        assert value(model.params.ethylene_glycol.temperature_crit) == 645

        dt = DiagnosticsToolbox(model)
        dt.assert_no_structural_warnings()


class TestStateBlock(object):
    @pytest.fixture(scope="class")
    def model(self):
        model = ConcreteModel()
        model.params = GenericParameterBlock(**config_dict)

        model.props = model.params.build_state_block([1], defined_state=True)

        model.props[1].calculate_scaling_factors()

        # Fix state
        model.props[1].flow_mol_phase_comp["Liq", "ethylene_oxide"].fix(100)
        model.props[1].flow_mol_phase_comp["Liq", "water"].fix(100)
        model.props[1].flow_mol_phase_comp["Liq", "sulfuric_acid"].fix(100)
        model.props[1].flow_mol_phase_comp["Liq", "ethylene_glycol"].fix(100)
        model.props[1].temperature.fix(300)
        model.props[1].pressure.fix(101325)

        return model

    @pytest.mark.unit
    def test_build(self, model):
        # Check state variable values and bounds
        assert isinstance(model.props[1].flow_mol_phase_comp, Var)
        assert value(model.props[1].flow_mol_phase_comp["Liq", "ethylene_oxide"]) == 100
        assert value(model.props[1].flow_mol_phase_comp["Liq", "water"]) == 100
        assert value(model.props[1].flow_mol_phase_comp["Liq", "sulfuric_acid"]) == 100
        assert value(model.props[1].flow_mol_phase_comp["Liq", "ethylene_glycol"]) == 100
        assert model.props[1].flow_mol_phase_comp["Liq", "ethylene_oxide"].ub == 1000
        assert model.props[1].flow_mol_phase_comp["Liq", "water"].ub == 1000
        assert model.props[1].flow_mol_phase_comp["Liq", "sulfuric_acid"].ub == 1000
        assert model.props[1].flow_mol_phase_comp["Liq", "ethylene_glycol"].ub == 1000
        assert model.props[1].flow_mol_phase_comp["Liq", "ethylene_oxide"].lb == 0
        assert model.props[1].flow_mol_phase_comp["Liq", "water"].lb == 0
        assert model.props[1].flow_mol_phase_comp["Liq", "sulfuric_acid"].lb == 0
        assert model.props[1].flow_mol_phase_comp["Liq", "ethylene_glycol"].lb == 0

        assert isinstance(model.props[1].pressure, Var)
        assert value(model.props[1].pressure) == 101325
        assert model.props[1].pressure.ub == 1e6
        assert model.props[1].pressure.lb == 5e4

        assert isinstance(model.props[1].temperature, Var)
        assert value(model.props[1].temperature) == 300
        assert model.props[1].temperature.ub == 450
        assert model.props[1].temperature.lb == 273.15

    @pytest.mark.unit
    def test_define_state_vars(self, model):
        sv = model.props[1].define_state_vars()

        assert len(sv) == 3
        for i in sv:
            assert i in ["flow_mol_phase_comp", "temperature", "pressure"]

    @pytest.mark.unit
    def test_define_port_members(self, model):
        sv = model.props[1].define_state_vars()

        assert len(sv) == 3
        for i in sv:
            assert i in ["flow_mol_phase_comp", "temperature", "pressure"]

    @pytest.mark.unit
    def test_define_display_vars(self, model):
        sv = model.props[1].define_display_vars()

        assert len(sv) == 3
        for i in sv:
            assert i in [
                "Molar Flowrate",
                "Temperature",
                "Pressure",
            ]

    @pytest.mark.unit
    def test_structural_diagnostics(self, model):
        dt = DiagnosticsToolbox(model)
        dt.assert_no_structural_warnings()

    @pytest.mark.unit
    def test_basic_scaling(self, model):
        assert len(model.props[1].scaling_factor) == 20
        assert model.props[1].scaling_factor[model.props[1].flow_mol] == 1e-2
        assert model.props[1].scaling_factor[model.props[1].flow_mol_comp["ethylene_oxide"]] == 1e-2
        assert model.props[1].scaling_factor[model.props[1].flow_mol_comp["water"]] == 1e-2
        assert model.props[1].scaling_factor[model.props[1].flow_mol_comp["sulfuric_acid"]] == 1e-2
        assert model.props[1].scaling_factor[model.props[1].flow_mol_comp["ethylene_glycol"]] == 1e-2
        assert model.props[1].scaling_factor[model.props[1].flow_mol_phase["Liq"]] == 1e-2
        assert model.props[1].scaling_factor[model.props[1].flow_mol_phase_comp["Liq", "ethylene_oxide"]] == 1e-2
        assert model.props[1].scaling_factor[model.props[1].flow_mol_phase_comp["Liq", "water"]] == 1e-2
        assert model.props[1].scaling_factor[model.props[1].flow_mol_phase_comp["Liq", "sulfuric_acid"]] == 1e-2
        assert model.props[1].scaling_factor[model.props[1].flow_mol_phase_comp["Liq", "ethylene_glycol"]] == 1e-2
        assert model.props[1].scaling_factor[model.props[1].mole_frac_comp["ethylene_oxide"]] == 1000
        assert model.props[1].scaling_factor[model.props[1].mole_frac_comp["water"]] == 1000
        assert model.props[1].scaling_factor[model.props[1].mole_frac_comp["sulfuric_acid"]] == 1000
        assert model.props[1].scaling_factor[model.props[1].mole_frac_comp["ethylene_glycol"]] == 1000
        assert model.props[1].scaling_factor[model.props[1].mole_frac_phase_comp["Liq", "ethylene_oxide"]] == 1000
        assert model.props[1].scaling_factor[model.props[1].mole_frac_phase_comp["Liq", "water"]] == 1000
        assert model.props[1].scaling_factor[model.props[1].mole_frac_phase_comp["Liq", "sulfuric_acid"]] == 1000
        assert model.props[1].scaling_factor[model.props[1].mole_frac_phase_comp["Liq", "ethylene_glycol"]] == 1000
        assert model.props[1].scaling_factor[model.props[1].pressure] == 1e-5
        assert model.props[1].scaling_factor[model.props[1].temperature] == 1e-2

    @pytest.mark.skipif(solver is None, reason="Solver not available")
    @pytest.mark.component
    def test_initialize(self, model):
        orig_fixed_vars = fixed_variables_set(model)
        orig_act_consts = activated_constraints_set(model)

        model.props.initialize(optarg={"tol": 1e-6})

        assert degrees_of_freedom(model) == 0

        fin_fixed_vars = fixed_variables_set(model)
        fin_act_consts = activated_constraints_set(model)

        assert len(fin_act_consts) == len(orig_act_consts)
        assert len(fin_fixed_vars) == len(orig_fixed_vars)

        for c in fin_act_consts:
            assert c in orig_act_consts
        for v in fin_fixed_vars:
            assert v in orig_fixed_vars

    @pytest.mark.skipif(solver is None, reason="Solver not available")
    @pytest.mark.component
    def test_solve(self, model):
        results = solver.solve(model)

        # Check for optimal solution
        assert_optimal_termination(results)

    @pytest.mark.unit
    def test_numerical_diagnostics(self, model):
        dt = DiagnosticsToolbox(model)
        dt.assert_no_numerical_warnings()

    @pytest.mark.skipif(solver is None, reason="Solver not available")
    @pytest.mark.component
    def test_solution(self, model):
        # Check results
        assert value(model.props[1].flow_mol_phase_comp[
            "Liq", "ethylene_oxide"
        ]) == pytest.approx(100, abs=1e-4)
        assert value(model.props[1].flow_mol_phase_comp[
            "Liq", "water"
        ]) == pytest.approx(100, abs=1e-4)
        assert value(model.props[1].flow_mol_phase_comp[
            "Liq", "sulfuric_acid"
        ]) == pytest.approx(100, abs=1e-4)
        assert value(model.props[1].flow_mol_phase_comp[
            "Liq", "ethylene_glycol"
        ]) == pytest.approx(100, abs=1e-4)

        assert value(
            model.props[1].temperature
        ) == pytest.approx(300, abs=1e-4)
        assert value(
            model.props[1].pressure
        ) == pytest.approx(101325, abs=1e-4)


class TestPerrysProperties(object):
    
    @pytest.fixture(scope="class")
    def model(self):
        model = ConcreteModel()
        model.params = GenericParameterBlock(**config_dict)

        model.props = model.params.build_state_block([1], defined_state=True)

        model.props[1].calculate_scaling_factors()

        return model

    @pytest.fixture(scope="class")
    def density_temperatures(self):
        # ethylene oxide, water, ethylene glycol reference temperatures
        # from Perry's Chemical Engineers' Handbook 7th Ed. 2-94 to 2-98
        components = ["ethylene_oxide", "water", "ethylene_glycol"]
        temperatures = dict(
            zip(
                components,
                [[160.65, 469.15], [273.16, 333.15], [260.15, 719.7]]
                )
            )

        return temperatures

    @pytest.fixture(scope="class")
    def densities(self):
        # ethylene oxide, water, ethylene glycol densities from
        # Perry's Chemical Engineers' Handbook 7th Ed. 2-94 to 2-98
        components = ["ethylene_oxide", "water", "ethylene_glycol"]
        densities = dict(
            zip(
                components,
                [[23.477, 7.055], [55.583, 54.703], [18.31, 5.234]]
                )
            )

        return densities

    @pytest.fixture(scope="class")
    def heat_capacity_temperatures(self):
        # ethylene oxide, water, ethylene glycol reference temperatures
        # from Perry's Chemical Engineers' Handbook 7th Ed. 2-94 to 2-98
        components = ["ethylene_oxide", "water", "ethylene_glycol"]
        temperatures = dict(
            zip(
                components,
                [[160.65, 283.85], [273.16, 533.15], [260.15, 493.15]]
                )
            )

        return temperatures

    @pytest.fixture(scope="class")
    def heat_capacities(self):
        # ethylene oxide, water, ethylene glycol densities from
        # Perry's Chemical Engineers' Handbook 7th Ed. 2-94 to 2-98
        components = ["ethylene_oxide", "water", "ethylene_glycol"]
        densities = dict(
            zip(
                components,
                [[0.8303, 0.8693], [0.7615, 0.8939], [1.36661, 2.0598]]
                )
            )

        return densities

    @pytest.mark.parametrize("component", ["ethylene_oxide", "water", "ethylene_glycol"])
    @pytest.mark.parametrize("test_point", [0, 1])
    @pytest.mark.skipif(solver is None, reason="Solver not available")
    @pytest.mark.component
    def test_liquid_densities(
            self,
            model,
            component,
            test_point,
            density_temperatures,
            densities
            ):
        # Fix state
        for phase, comp in model.props[1].flow_mol_phase_comp.keys():
            if comp == component:
                model.props[1].flow_mol_phase_comp[phase, comp].fix(100)
            else:
                model.props[1].flow_mol_phase_comp[phase, comp].fix(1e-5)

        # change lower bound for testing
        model.props[1].temperature.setlb(150)

        model.props[1].temperature.fix(density_temperatures[component][test_point])
        model.props[1].pressure.fix(101325)

        results = solver.solve(model)

        # Check for optimal solution
        assert_optimal_termination(results)

        # Check results
        assert value(
            pyunits.convert(
                model.props[1].dens_mol,
                to_units=pyunits.kmol/pyunits.m**3
                )
            ) == pytest.approx(densities[component][test_point], rel=1e-4)

    @pytest.mark.parametrize("component", ["ethylene_oxide", "water", "ethylene_glycol"])
    @pytest.mark.parametrize("test_point", [0, 1])
    @pytest.mark.skipif(solver is None, reason="Solver not available")
    @pytest.mark.component
    def test_liquid_heat_capacities(
            self,
            model,
            component,
            test_point,
            heat_capacity_temperatures,
            heat_capacities
            ):
        # Fix state
        for phase, comp in model.props[1].flow_mol_phase_comp.keys():
            if comp == component:
                model.props[1].flow_mol_phase_comp[phase, comp].fix(100)
            else:
                model.props[1].flow_mol_phase_comp[phase, comp].fix(1e-5)

        model.props[1].temperature.fix(heat_capacity_temperatures[component][test_point])
        model.props[1].pressure.fix(101325)

        results = solver.solve(model)

        # Check for optimal solution
        assert_optimal_termination(results)

        # Check results
        assert value(
            pyunits.convert(
                model.props[1].cp_mol,
                to_units=pyunits.J/pyunits.kmol/pyunits.K
                )
            ) == pytest.approx(heat_capacities[component][test_point], rel=1e-4)