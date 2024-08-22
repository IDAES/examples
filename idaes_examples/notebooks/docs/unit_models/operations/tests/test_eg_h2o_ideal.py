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
    as_quantity,
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

from idaes_examples.notebooks.docs.unit_models.operations.eg_h2o_ideal import (
    config_dict,
)

from idaes.models.properties.tests.test_harness import PropertyTestHarness

from idaes.core.util.model_diagnostics import DiagnosticsToolbox

from idaes.core import VaporPhase

from idaes.models.properties.modular_properties.eos.ideal import Ideal

import copy


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
            assert i in [
                "Liq",
            ]
        assert model.params.Liq.is_liquid_phase()

        assert isinstance(model.params.component_list, Set)
        assert len(model.params.component_list) == 2
        for i in model.params.component_list:
            assert i in ["water", "ethylene_glycol"]
            assert isinstance(model.params.get_component(i), Component)

        assert isinstance(model.params._phase_component_set, Set)
        assert len(model.params._phase_component_set) == 2
        for i in model.params._phase_component_set:
            assert i in [
                ("Liq", "water"),
                ("Liq", "ethylene_glycol"),
            ]

        assert model.params.config.state_definition == FpcTP

        assertStructuredAlmostEqual(
            model.params.config.state_bounds,
            {
                "flow_mol_phase_comp": (0, 100, 1000, pyunits.mol / pyunits.s),
                "temperature": (273.15, 298.15, 450, pyunits.K),
                "pressure": (1e3, 1e5, 1e6, pyunits.Pa),
            },
            item_callback=as_quantity,
        )

        assert value(model.params.pressure_ref) == 1e5
        assert value(model.params.temperature_ref) == 298.15

        assert value(model.params.water.mw) == 18.015e-3
        assert value(model.params.water.pressure_crit) == 221.2e5
        assert value(model.params.water.temperature_crit) == 647.3

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
        model.props[1].flow_mol_phase_comp["Liq", "water"].fix(100)
        model.props[1].flow_mol_phase_comp["Liq", "ethylene_glycol"].fix(100)
        model.props[1].temperature.fix(300)
        model.props[1].pressure.fix(101325)

        return model

    @pytest.mark.unit
    def test_build(self, model):
        # Check state variable values and bounds
        assert isinstance(model.props[1].flow_mol_phase_comp, Var)
        assert value(model.props[1].flow_mol_phase_comp["Liq", "water"]) == 100
        assert (
            value(model.props[1].flow_mol_phase_comp["Liq", "ethylene_glycol"]) == 100
        )
        assert model.props[1].flow_mol_phase_comp["Liq", "water"].ub == 1000
        assert model.props[1].flow_mol_phase_comp["Liq", "ethylene_glycol"].ub == 1000
        assert model.props[1].flow_mol_phase_comp["Liq", "water"].lb == 0
        assert model.props[1].flow_mol_phase_comp["Liq", "ethylene_glycol"].lb == 0

        assert isinstance(model.props[1].pressure, Var)
        assert value(model.props[1].pressure) == 101325
        assert model.props[1].pressure.ub == 1e6
        assert model.props[1].pressure.lb == 1e3

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
        assert len(model.props[1].scaling_factor) == 12
        assert model.props[1].scaling_factor[model.props[1].flow_mol] == 1e-2
        assert (
            model.props[1].scaling_factor[model.props[1].flow_mol_comp["water"]] == 1e-2
        )
        assert (
            model.props[1].scaling_factor[
                model.props[1].flow_mol_comp["ethylene_glycol"]
            ]
            == 1e-2
        )
        assert (
            model.props[1].scaling_factor[model.props[1].flow_mol_phase["Liq"]] == 1e-2
        )
        assert (
            model.props[1].scaling_factor[
                model.props[1].flow_mol_phase_comp["Liq", "water"]
            ]
            == 1e-2
        )
        assert (
            model.props[1].scaling_factor[
                model.props[1].flow_mol_phase_comp["Liq", "ethylene_glycol"]
            ]
            == 1e-2
        )
        assert (
            model.props[1].scaling_factor[model.props[1].mole_frac_comp["water"]]
            == 1000
        )
        assert (
            model.props[1].scaling_factor[
                model.props[1].mole_frac_comp["ethylene_glycol"]
            ]
            == 1000
        )
        assert (
            model.props[1].scaling_factor[
                model.props[1].mole_frac_phase_comp["Liq", "water"]
            ]
            == 1000
        )
        assert (
            model.props[1].scaling_factor[
                model.props[1].mole_frac_phase_comp["Liq", "ethylene_glycol"]
            ]
            == 1000
        )
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
        assert value(
            model.props[1].flow_mol_phase_comp["Liq", "water"]
        ) == pytest.approx(100, abs=1e-4)
        assert value(
            model.props[1].flow_mol_phase_comp["Liq", "ethylene_glycol"]
        ) == pytest.approx(100, abs=1e-4)

        assert value(model.props[1].temperature) == pytest.approx(300, abs=1e-4)
        assert value(model.props[1].pressure) == pytest.approx(101325, abs=1e-4)


class TestPerrysProperties(object):
    @pytest.fixture(scope="class")
    def density_temperatures(self):
        # water, ethylene glycol reference temperatures
        # from Perry's Chemical Engineers' Handbook 7th Ed. 2-94 to 2-98
        components = ["water", "ethylene_glycol"]
        temperatures = dict(zip(components, [[273.16, 333.15], [260.15, 719.7]]))

        return temperatures

    @pytest.fixture(scope="class")
    def densities(self):
        # water, ethylene glycol densities from
        # Perry's Chemical Engineers' Handbook 7th Ed. 2-94 to 2-98
        components = ["water", "ethylene_glycol"]
        densities = dict(zip(components, [[55.583, 54.703], [18.31, 5.234]]))

        return densities

    @pytest.fixture(scope="class")
    def heat_capacity_temperatures(self):
        # water, ethylene glycol reference temperatures
        # from Perry's Chemical Engineers' Handbook 7th Ed. 2-170 to 2-174
        components = ["water", "ethylene_glycol"]
        temperatures = dict(zip(components, [[273.16, 533.15], [260.15, 493.15]]))

        return temperatures

    @pytest.fixture(scope="class")
    def heat_capacities(self):
        # water, ethylene glycol heat capacities from
        # Perry's Chemical Engineers' Handbook 7th Ed. 2-170 to 2-174
        components = ["water", "ethylene_glycol"]
        heat_capacities = dict(
            zip(components, [[0.7615e5, 0.8939e5], [1.36661e5, 2.0598e5]])
        )

        return heat_capacities

    @pytest.fixture(scope="class")
    def heat_capacity_reference(self):
        # water, ethylene glycol heat capacities from
        # NIST Chemistry WebBook, https://webbook.nist.gov/chemistry/
        components = ["water", "ethylene_glycol"]
        heat_capacities = dict(zip(components, [0.7538e5, 0.1498e5]))

        return heat_capacities

    @pytest.fixture(scope="class")
    def heat_capacity_reference_temperatures(self):
        # water, ethylene glycol reference temperatures
        # from NIST Chemistry WebBook, https://webbook.nist.gov/chemistry/
        components = ["water", "ethylene_glycol"]
        temperatures = dict(zip(components, [298.0, 298.0]))

        return temperatures

    @pytest.mark.parametrize("component", ["water", "ethylene_glycol"])
    @pytest.mark.parametrize("test_point", [0, 1])
    @pytest.mark.skipif(solver is None, reason="Solver not available")
    @pytest.mark.component
    def test_liquid_densities(
        self, component, test_point, density_temperatures, densities
    ):

        config_dict_component_only = copy.deepcopy(config_dict)
        for key in config_dict["components"].keys():
            if key == component:
                pass
            else:
                config_dict_component_only["components"].pop(key)

        model = ConcreteModel()

        model.params = GenericParameterBlock(**config_dict_component_only)

        model.props = model.params.build_state_block([1], defined_state=True)

        model.props[1].calculate_scaling_factors()

        # Fix state
        model.props[1].flow_mol_phase_comp["Liq", component].fix(100)

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
                model.props[1].dens_mol, to_units=pyunits.kmol / pyunits.m**3
            )
        ) == pytest.approx(densities[component][test_point], rel=1e-4)

    @pytest.mark.parametrize("component", ["water", "ethylene_glycol"])
    @pytest.mark.parametrize("test_point", [0, 1])
    @pytest.mark.skipif(solver is None, reason="Solver not available")
    @pytest.mark.component
    def test_liquid_heat_capacities_enthalpy(
        self,
        component,
        test_point,
        heat_capacity_temperatures,
        heat_capacities,
        heat_capacity_reference,
        heat_capacity_reference_temperatures,
    ):

        config_dict_component_only = copy.deepcopy(config_dict)
        for key in config_dict["components"].keys():
            if key == component:
                pass
            else:
                config_dict_component_only["components"].pop(key)

        model = ConcreteModel()

        model.params = GenericParameterBlock(**config_dict_component_only)

        model.props = model.params.build_state_block([1], defined_state=True)

        model.props[1].calculate_scaling_factors()

        # Fix state
        model.props[1].flow_mol_phase_comp["Liq", component].fix(100)

        model.props[1].pressure.fix(101325)

        # calculate reference point

        model.props[1].temperature.fix(heat_capacity_reference_temperatures[component])

        results = solver.solve(model)

        enth_mol_ref = value(model.props[1].enth_mol) * pyunits.get_units(
            model.props[1].enth_mol
        )
        temp_ref = heat_capacity_reference_temperatures[component] * pyunits.K
        cp_mol_ref = (
            heat_capacity_reference[component]
            * 1e-3
            * pyunits.J
            / pyunits.mol
            / pyunits.K
        )

        # calculate test point

        model.props[1].temperature.fix(
            heat_capacity_temperatures[component][test_point]
        )

        results = solver.solve(model)

        enth_mol_test = value(model.props[1].enth_mol) * pyunits.get_units(
            model.props[1].enth_mol
        )
        temp_test = heat_capacity_temperatures[component][test_point] * pyunits.K
        cp_mol_test = (
            heat_capacities[component][test_point]
            * 1e-3
            * pyunits.J
            / pyunits.mol
            / pyunits.K
        )

        # Check for optimal solution
        assert_optimal_termination(results)

        # Check results

        assert value(
            pyunits.convert(enth_mol_test, to_units=pyunits.J / pyunits.mol)
        ) == pytest.approx(
            value(
                pyunits.convert(
                    0.5 * (cp_mol_test + cp_mol_ref) * (temp_test - temp_ref)
                    + enth_mol_ref,
                    to_units=pyunits.J / pyunits.mol,
                )
            ),
            rel=1e-1,  # using 1e-1 tol to check against trapezoid rule estimation of integral
        )


class TestRPP4Properties(object):
    @pytest.fixture(scope="class")
    def heat_capacity_temperatures(self):
        # water, ethylene glycol reference temperatures
        # from NIST Chemistry WebBook, https://webbook.nist.gov/chemistry/
        components = ["water", "ethylene_glycol"]
        temperatures = dict(zip(components, [[545, 632], [500, 600]]))

        return temperatures

    @pytest.fixture(scope="class")
    def heat_capacities(self):
        # water, ethylene glycol heat capacities from
        # from NIST Chemistry WebBook, https://webbook.nist.gov/chemistry/
        components = ["water", "ethylene_glycol"]
        heat_capacities = dict(zip(components, [[35.70, 36.69], [113.64, 125.65]]))

        return heat_capacities

    @pytest.fixture(scope="class")
    def heat_capacity_reference(self):
        # water, ethylene glycol heat capacities from
        # NIST Chemistry WebBook, https://webbook.nist.gov/chemistry/
        components = ["water", "ethylene_glycol"]
        heat_capacities = dict(zip(components, [35.22, 97.99]))

        return heat_capacities

    @pytest.fixture(scope="class")
    def heat_capacity_reference_temperatures(self):
        # water, ethylene glycol reference temperatures
        # from NIST Chemistry WebBook, https://webbook.nist.gov/chemistry/
        components = ["water", "ethylene_glycol"]
        temperatures = dict(zip(components, [500, 400]))

        return temperatures

    @pytest.fixture(scope="class")
    def saturation_pressure_temperatures(self):
        # water, ethylene glycol reference temperatures
        # from NIST Chemistry WebBook, https://webbook.nist.gov/chemistry/
        components = ["water", "ethylene_glycol"]
        temperatures = dict(zip(components, [[300.25, 350.16], [387, 473]]))

        return temperatures

    @pytest.fixture(scope="class")
    def saturation_pressures(self):
        # ethylene glycol saturation pressures from
        # from NIST Chemistry WebBook, https://webbook.nist.gov/chemistry/
        components = ["water", "ethylene_glycol"]
        pressures = dict(
            zip(components, [[0.03591e5, 0.4194e5], [0.04257e5, 1.0934e5]])
        )

        return pressures

    @pytest.mark.parametrize("component", ["water", "ethylene_glycol"])
    @pytest.mark.parametrize("test_point", [0, 1])
    @pytest.mark.skipif(solver is None, reason="Solver not available")
    @pytest.mark.component
    def test_vapor_heat_capacities_enthalpy(
        self,
        component,
        test_point,
        heat_capacity_temperatures,
        heat_capacities,
        heat_capacity_reference,
        heat_capacity_reference_temperatures,
    ):

        config_dict_component_only = copy.deepcopy(config_dict)
        for key in config_dict["components"].keys():
            if key == component:
                pass
            else:
                config_dict_component_only["components"].pop(key)

        config_dict_component_only["phases"] = {
            "Vap": {"type": VaporPhase, "equation_of_state": Ideal}
        }

        model = ConcreteModel()

        model.params = GenericParameterBlock(**config_dict_component_only)

        model.props = model.params.build_state_block([1], defined_state=True)

        model.props[1].calculate_scaling_factors()

        # Fix state
        model.props[1].flow_mol_phase_comp["Vap", component].fix(100)

        model.props[1].pressure.fix(101325)

        # calculate reference point

        model.props[1].temperature.fix(heat_capacity_reference_temperatures[component])

        results = solver.solve(model)

        enth_mol_ref = value(model.props[1].enth_mol) * pyunits.get_units(
            model.props[1].enth_mol
        )
        temp_ref = heat_capacity_reference_temperatures[component] * pyunits.K
        cp_mol_ref = (
            heat_capacity_reference[component]
            * 1e-3
            * pyunits.J
            / pyunits.mol
            / pyunits.K
        )

        # calculate test point

        model.props[1].temperature.fix(
            heat_capacity_temperatures[component][test_point]
        )

        results = solver.solve(model)

        enth_mol_test = value(model.props[1].enth_mol) * pyunits.get_units(
            model.props[1].enth_mol
        )
        temp_test = heat_capacity_temperatures[component][test_point] * pyunits.K
        cp_mol_test = (
            heat_capacities[component][test_point]
            * 1e-3
            * pyunits.J
            / pyunits.mol
            / pyunits.K
        )

        # Check for optimal solution
        assert_optimal_termination(results)

        # Check results

        assert value(
            pyunits.convert(enth_mol_test, to_units=pyunits.J / pyunits.mol)
        ) == pytest.approx(
            value(
                pyunits.convert(
                    0.5 * (cp_mol_test + cp_mol_ref) * (temp_test - temp_ref)
                    + enth_mol_ref,
                    to_units=pyunits.J / pyunits.mol,
                )
            ),
            rel=1.15e-1,  # using 1.15e-1 tol to check against trapezoid rule estimation of integral
            # all values match within 1e-1, except ethylene glycol test point 0
        )

    @pytest.mark.parametrize("component", ["water", "ethylene_glycol"])
    @pytest.mark.parametrize("test_point", [0, 1])
    @pytest.mark.skipif(solver is None, reason="Solver not available")
    @pytest.mark.component
    def test_saturation_pressures(
        self,
        component,
        test_point,
        saturation_pressure_temperatures,
        saturation_pressures,
    ):

        config_dict_component_only = copy.deepcopy(config_dict)
        for key in config_dict["components"].keys():
            if key == component:
                pass
            else:
                config_dict_component_only["components"].pop(key)

        config_dict_component_only["phases"] = {
            "Vap": {"type": VaporPhase, "equation_of_state": Ideal}
        }

        model = ConcreteModel()

        model.params = GenericParameterBlock(**config_dict_component_only)

        model.props = model.params.build_state_block([1], defined_state=True)

        model.props[1].calculate_scaling_factors()

        # Fix state
        model.props[1].flow_mol_phase_comp["Vap", component].fix(100)

        model.props[1].temperature.fix(
            saturation_pressure_temperatures[component][test_point]
        )
        model.props[1].pressure.fix(101325)

        results = solver.solve(model)

        # Check for optimal solution
        assert_optimal_termination(results)

        # Check results
        print(value(model.props[1].pressure_sat_comp[component]))
        assert value(model.props[1].pressure_sat_comp[component]) == pytest.approx(
            saturation_pressures[component][test_point], rel=1.5e-2
        )  # match within 1.5%
