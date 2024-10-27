import os
import pandas as pd
import numpy as np

import pyomo.environ as pyo
from pyomo.common.config import ConfigValue, Bool
from pyomo.network import Arc
from pyomo.common.fileutils import this_file_dir

from idaes.core import FlowsheetBlockData, declare_process_block_class
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.models.properties.modular_properties.base.generic_property import (
    GenericParameterBlock,
)
import idaes.core.util.scaling as iscale
from idaes.models_extra.power_generation.properties.natural_gas_PR import (
    get_prop,
    EosType,
)
from idaes.models_extra.power_generation.unit_models.soc_submodels import (
    SolidOxideModuleSimple,
)
import idaes.models.unit_models as gum
from idaes.models.properties import iapws95
from idaes.core.util.initialization import propagate_state
import idaes.logger as idaeslog
import idaes.core.util as iutil
import idaes.core.util.tables as tables
from idaes.core.solvers import get_solver
from idaes.core.util.tags import svg_tag
from idaes.models_extra.power_generation.unit_models import CrossFlowHeatExchanger1D
from idaes.models.unit_models.heat_exchanger import HeatExchangerFlowPattern
from idaes.models_extra.power_generation.unit_models import Heater1D
from idaes.models.control.controller import PIDController, ControllerType
from pyomo.common.collections import ComponentSet
from pyomo.dae import DerivativeVar


def scale_indexed_constraint(con, sf):
    for c in con.values():
        iscale.constraint_scaling_transform(c, sf)


def set_indexed_variable_bounds(var, bounds):
    for subvar in var.values():
        subvar.bounds = bounds


@declare_process_block_class("SocStandaloneFlowsheet")
class SocStandaloneFlowsheetData(FlowsheetBlockData):
    sweep_comp = {
        "O2": 0.2074,
        "H2O": 0.0099,
        "CO2": 0.0003,
        "N2": 0.7732,
        "Ar": 0.0092,
    }

    CONFIG = FlowsheetBlockData.CONFIG
    CONFIG.declare(
        "thin_electrolyte_and_oxygen_electrode",
        ConfigValue(
            default=False,
            domain=Bool,
            description="Determines whether to use some thin submodels in SOEC",
            doc="""Determines whether to use thin submodels in SOEC,
                **default** - False.
                **Valid values:** {
                **True** - Use thin submodels,
                **False** - do not use thin submodels.}""",
        ),
    )
    CONFIG.declare(
        "include_interconnect",
        ConfigValue(
            default=False,
            domain=Bool,
            description="Determines whether to make interconnect in SOEC",
            doc="""Determines whether to make interconnect in SOEC,
                **default** - False.
                **Valid values:** {
                **True** - Make interconnect,
                **False** - do not make interconnect.}""",
        ),
    )
    CONFIG.declare(
        "quasi_steady_state",
        ConfigValue(
            default=False,
            domain=Bool,
            description="If True, force units to be steady-state even if flowsheet is dynamic",
            doc="""Determines whether to force units to be steady-state even if flowsheet is dynamic,
                **default** - False.
                **Valid values:** {
                **True** - Force steady state units,
                **False** - Create dynamic unit models where appropriate.}""",
        ),
    )

    def build(self):
        super().build()

        self._add_properties()
        self._add_units()
        self._add_arcs()
        self._add_constraints()
        self._set_initial_inputs()
        self._define_cell_params()
        self._scaling()
        self._add_tags()
        self._make_temperature_gradient_terms()
        self.manipulated_variables = ComponentSet(
            [
                self.makeup_mix.makeup.flow_mol,
                self.sweep_blower.inlet.flow_mol,
                self.soc_module.potential_cell,
                self.feed_recycle_split.recycle_ratio,
                self.sweep_recycle_split.recycle_ratio,
                self.condenser_split.recycle_ratio,
                self.feed_heater.electric_heat_duty,
                self.sweep_heater.electric_heat_duty,
                self.condenser_flash.vap_outlet.temperature,
                self.makeup_mix.makeup_mole_frac_comp_H2,
                self.makeup_mix.makeup_mole_frac_comp_H2O,
            ]
        )
        if self.config.dynamic:
            self.controller_set = ComponentSet()

    def _add_properties(self):
        self.water_prop_params = iapws95.Iapws95ParameterBlock()
        self.o2_side_prop_params = GenericParameterBlock(
            **get_prop(self.sweep_comp, ["Vap"], eos=EosType.IDEAL),
            doc="Air property parameters",
        )
        self.h2_side_prop_params = GenericParameterBlock(
            **get_prop(["H2", "H2O", "Ar", "N2"], ["Vap"], eos=EosType.IDEAL),
            doc="H2O + H2 gas property parameters",
        )
        self.h2_condensing_prop_params = GenericParameterBlock(
            **get_prop(
                ["H2", "H2O", "Ar", "N2"],
                [
                    "Liq",
                    "Vap",
                ],
                eos=EosType.PR,
            ),
            doc="H2O + H2 gas property parameters",
        )
        self.h2_condensing_prop_params.H2.config.parameter_data["kappa1"] = 0.0
        self.h2_condensing_prop_params.N2.config.parameter_data["kappa1"] = 0.0
        self.h2_condensing_prop_params.Ar.config.parameter_data["kappa1"] = 0.0
        self.h2_condensing_prop_params.H2O.config.parameter_data["kappa1"] = (
            -0.0665
        )  # p. 312 of (Sandler, 2006)
        # Use PR-SV for water phase equilibrium
        sqrt = pyo.sqrt

        def omega_func(cobj):
            return (
                0.378893
                + 1.4897153 * cobj.omega
                - 0.17131848 * cobj.omega**2
                + 0.0196554 * cobj.omega**3
            )

        def alpha_func(T, fw, cobj):
            TR = T / cobj.temperature_crit
            kappa1 = cobj.config.parameter_data["kappa1"]
            kappa = fw + kappa1 * (1 + sqrt(TR)) * (0.7 - TR)
            return (1 + kappa * (1 - sqrt(TR))) ** 2

        def dalpha_dT_func(T, fw, cobj):
            Tc = cobj.temperature_crit
            Tr = T / Tc
            kappa1 = cobj.config.parameter_data["kappa1"]
            kappa = fw + kappa1 * (1 + sqrt(Tr)) * (0.7 - Tr)
            dkappa_dT = kappa1 * ((0.7 - Tr) / (2 * sqrt(T * Tc)) - (1 + sqrt(Tr)) / Tc)
            return (
                2
                * (1 + kappa * (1 - sqrt(Tr)))
                * ((1 - sqrt(Tr)) * dkappa_dT - kappa / (2 * sqrt(T * Tc)))
            )

        def d2alpha_dT2_func(T, fw, cobj):
            Tc = cobj.temperature_crit
            Tr = T / Tc
            kappa1 = cobj.config.parameter_data["kappa1"]
            kappa = fw + kappa1 * (1 + sqrt(Tr)) * (0.7 - Tr)

            sqrt_alpha = 1 + kappa * (1 - sqrt(Tr))

            dsqrtalpha_dTr = -fw / (2 * sqrt(Tr)) - 1.7 * kappa1 + 2 * kappa1 * Tr
            d2sqrtalpha_dTr = 2 * kappa1 + fw / (4 * Tr**1.5)

            d2alpha_dTr2 = 2 * dsqrtalpha_dTr**2 + 2 * sqrt_alpha * d2sqrtalpha_dTr

            return d2alpha_dTr2 / Tc**2

        self.h2_condensing_prop_params.PR_func_fw = omega_func
        self.h2_condensing_prop_params.PR_func_alpha = alpha_func
        self.h2_condensing_prop_params.PR_func_dalpha_dT = dalpha_dT_func
        self.h2_condensing_prop_params.PR_func_d2alpha_dT2 = d2alpha_dT2_func

        generic_prop_packages = [
            self.o2_side_prop_params,
            self.h2_side_prop_params,
            self.h2_condensing_prop_params,
        ]
        for pp in generic_prop_packages:
            pp.set_default_scaling("enth_mol_phase", 1e-3)
            pp.set_default_scaling("pressure", 1e-5)
            pp.set_default_scaling("temperature", 1e-2)
            pp.set_default_scaling("flow_mol", 1e-3)

        _mf_scale = {"Ar": 100, "O2": 10, "N2": 10, "H2": 10, "H2O": 100, "CO2": 1000}
        for comp, s in _mf_scale.items():
            self.o2_side_prop_params.set_default_scaling(
                "mole_frac_comp", s, index=comp
            )
            self.o2_side_prop_params.set_default_scaling(
                "mole_frac_phase_comp", s, index=("Vap", comp)
            )
            self.o2_side_prop_params.set_default_scaling(
                "flow_mol_phase_comp", s * 1e-3, index=("Vap", comp)
            )

        _mf_scale = {
            "H2": 1,
            "H2O": 1,
            "N2": 10,
            "Ar": 10,
        }
        for comp, s in _mf_scale.items():
            for params in [self.h2_side_prop_params, self.h2_condensing_prop_params]:
                params.set_default_scaling("mole_frac_comp", s, index=comp)
                params.set_default_scaling(
                    "mole_frac_phase_comp", s, index=("Vap", comp)
                )
                params.set_default_scaling(
                    "flow_mol_phase_comp", s * 1e-3, index=("Vap", comp)
                )

        self.h2_condensing_prop_params.set_default_scaling(
            "mole_frac_phase_comp", 1, index=("Liq", "H2O")
        )
        self.h2_condensing_prop_params.set_default_scaling(
            "flow_mol_phase_comp", 1 * 1e-3, index=("Liq", "H2O")
        )

    def _define_cell_params(self):
        self.soc_module.number_cells.fix(4e5)
        soec = self.soc_module.solid_oxide_cell

        soec.fuel_channel.length_x.fix(873e-6)
        soec.length_y.fix(0.2345)
        soec.length_z.fix(0.2345)
        soec.fuel_channel.heat_transfer_coefficient.fix(100)

        soec.oxygen_channel.length_x.fix(873e-6)
        soec.oxygen_channel.heat_transfer_coefficient.fix(100)

        soec.fuel_electrode.length_x.fix(1e-3)
        soec.fuel_electrode.porosity.fix(0.326)
        soec.fuel_electrode.tortuosity.fix(3)
        soec.fuel_electrode.solid_heat_capacity.fix(595)
        soec.fuel_electrode.solid_density.fix(7740.0)
        soec.fuel_electrode.solid_thermal_conductivity.fix(6.23)
        soec.fuel_electrode.resistivity_log_preexponential_factor.fix(pyo.log(2.5e-5))
        soec.fuel_electrode.resistivity_thermal_exponent_dividend.fix(0)

        if self.config.thin_electrolyte_and_oxygen_electrode:
            soec.oxygen_electrode.contact_fraction.fix(1)
            soec.oxygen_electrode.log_preexponential_factor.fix(
                pyo.log(7.8125e-05 * 40e-6)
            )
            soec.oxygen_electrode.thermal_exponent_dividend.fix(0)

            soec.electrolyte.contact_fraction.fix(1)
            soec.electrolyte.log_preexponential_factor.fix(-9 + pyo.log(10.5e-6))
            soec.electrolyte.thermal_exponent_dividend.fix(8988)
        else:
            soec.oxygen_electrode.length_x.fix(40e-6)
            soec.oxygen_electrode.porosity.fix(0.30717)
            soec.oxygen_electrode.tortuosity.fix(3.0)
            soec.oxygen_electrode.solid_heat_capacity.fix(142.3)
            soec.oxygen_electrode.solid_density.fix(5300)
            soec.oxygen_electrode.solid_thermal_conductivity.fix(2.0)
            soec.oxygen_electrode.resistivity_log_preexponential_factor.fix(
                pyo.log(7.8125e-05)
            )
            soec.oxygen_electrode.resistivity_thermal_exponent_dividend.fix(0)

            soec.electrolyte.length_x.fix(10.5e-6)
            soec.electrolyte.heat_capacity.fix(400)
            soec.electrolyte.density.fix(6000)
            soec.electrolyte.thermal_conductivity.fix(2.17)
            soec.electrolyte.resistivity_log_preexponential_factor.fix(-9)
            soec.electrolyte.resistivity_thermal_exponent_dividend.fix(8988)

        soec.fuel_triple_phase_boundary.exchange_current_log_preexponential_factor.fix(
            22.5
        )
        soec.fuel_triple_phase_boundary.exchange_current_activation_energy.fix(110.8e3)
        soec.fuel_triple_phase_boundary.activation_potential_alpha1.fix(1 - 0.352184)
        soec.fuel_triple_phase_boundary.activation_potential_alpha2.fix(0.352184)

        soec.fuel_triple_phase_boundary.exchange_current_exponent_comp["H2"].fix(0.5)
        soec.fuel_triple_phase_boundary.exchange_current_exponent_comp["H2O"].fix(0.5)

        soec.oxygen_triple_phase_boundary.exchange_current_log_preexponential_factor.fix(
            25.5
        )
        soec.oxygen_triple_phase_boundary.exchange_current_activation_energy.fix(
            112.1e3
        )
        soec.oxygen_triple_phase_boundary.activation_potential_alpha1.fix(1 - 0.497231)
        soec.oxygen_triple_phase_boundary.activation_potential_alpha2.fix(0.497231)

        soec.oxygen_triple_phase_boundary.exchange_current_exponent_comp["O2"].fix(0.25)
        if self.config.include_interconnect:
            soec.interconnect.length_x.fix(5e-3)
            soec.interconnect.density.fix(7640)
            soec.interconnect.heat_capacity.fix(948)
            soec.interconnect.thermal_conductivity.fix(27)
            soec.interconnect.resistivity_log_preexponential_factor.fix(pyo.log(110e-8))
            soec.interconnect.resistivity_thermal_exponent_dividend.fix(0)

    def _add_units(self):
        zfaces = np.linspace(0, 1, 11).tolist()
        xfaces_electrode = [0.0, 1.0]
        xfaces_electrolyte = [0.0, 1.0]

        air_sweep = True
        dynamic_unit_models = self.config.dynamic and not self.config.quasi_steady_state

        soc_cell_config = {
            "has_holdup": True,
            "dynamic": dynamic_unit_models,
            "has_gas_holdup": False,
            "control_volume_zfaces": zfaces,
            "control_volume_xfaces_fuel_electrode": xfaces_electrode,
            "fuel_component_list": ["H2", "H2O", "Ar", "N2"],
            "fuel_triple_phase_boundary_stoich_dict": {
                "H2": -0.5,
                "H2O": 0.5,
                "Vac": 0.5,
                "O^2-": -0.5,
                "e^-": 1.0,
            },
            "inert_fuel_species_triple_phase_boundary": ["Ar", "N2"],
            "flow_pattern": HeatExchangerFlowPattern.countercurrent,
            "include_temperature_x_thermo": True,
        }
        if self.config.include_interconnect:
            soc_cell_config["flux_through_interconnect"] = True
            soc_cell_config["control_volume_xfaces_interconnect"] = [0.0, 1.0]

        if air_sweep:
            soc_cell_config["oxygen_component_list"] = ["Ar", "CO2", "H2O", "O2", "N2"]
            soc_cell_config["oxygen_triple_phase_boundary_stoich_dict"] = {
                "Ar": 0.0,
                "CO2": 0.0,
                "H2O": 0.0,
                "O2": -0.25,
                "N2": 0.0,
                "Vac": -0.5,
                "O^2-": 0.5,
                "e^-": -1.0,
            }
            soc_cell_config["inert_oxygen_species_triple_phase_boundary"] = [
                "Ar",
                "CO2",
                "H2O",
                "N2",
            ]
        else:
            soc_cell_config["oxygen_component_list"] = ["O2", "H2O"]
            soc_cell_config["oxygen_triple_phase_boundary_stoich_dict"] = {
                "O2": -0.25,
                "H2O": 0,
                "Vac": -0.5,
                "O^2-": 0.5,
                "e^-": -1.0,
            }
            soc_cell_config["inert_oxygen_species_triple_phase_boundary"] = ["H2O"]

        if self.config.thin_electrolyte_and_oxygen_electrode:
            soc_cell_config["thin_oxygen_electrode"] = True
            soc_cell_config["thin_electrolyte"] = True
        else:
            soc_cell_config["control_volume_xfaces_oxygen_electrode"] = xfaces_electrode
            soc_cell_config["control_volume_xfaces_electrolyte"] = xfaces_electrolyte
        self.soc_module = SolidOxideModuleSimple(
            dynamic=dynamic_unit_models,
            solid_oxide_cell_config=soc_cell_config,
            fuel_property_package=self.h2_side_prop_params,
            oxygen_property_package=self.o2_side_prop_params,
        )

        self.sweep_recycle_split = gum.Separator(
            doc="Sweep recycle splitter",
            property_package=self.o2_side_prop_params,
            outlet_list=["out", "recycle"],
        )
        self.feed_recycle_split = gum.Separator(
            doc="Feed recycle splitter",
            property_package=self.h2_side_prop_params,
            outlet_list=["out", "recycle"],
        )
        self.sweep_recycle_mix = gum.Mixer(
            doc="Sweep recycle mixer",
            property_package=self.o2_side_prop_params,
            inlet_list=["feed", "recycle"],
            momentum_mixing_type=gum.MomentumMixingType.none,
        )

        @self.sweep_recycle_mix.Constraint(self.time)
        def pressure_equality_eqn(b, t):
            return b.mixed_state[t].pressure == b.feed_state[t].pressure

        self.feed_recycle_mix = gum.Mixer(
            doc="Feed recycle mixer",
            property_package=self.h2_side_prop_params,
            inlet_list=["feed", "recycle"],
            momentum_mixing_type=gum.MomentumMixingType.none,
        )

        @self.feed_recycle_mix.Constraint(self.time)
        def pressure_equality_eqn(b, t):
            return b.mixed_state[t].pressure == b.feed_state[t].pressure

        self.sweep_exchanger = CrossFlowHeatExchanger1D(
            has_holdup=True,
            dynamic=dynamic_unit_models,
            cold_side={
                "property_package": self.o2_side_prop_params,
                "dynamic": False,
                "has_holdup": False,
                "has_pressure_change": False,
                "transformation_method": "dae.finite_difference",
                "transformation_scheme": "BACKWARD",
            },
            hot_side={
                "property_package": self.o2_side_prop_params,
                "dynamic": False,
                "has_holdup": False,
                "has_pressure_change": False,
                "transformation_method": "dae.finite_difference",
                "transformation_scheme": "BACKWARD",
            },
            shell_is_hot=True,
            flow_type=HeatExchangerFlowPattern.countercurrent,
            finite_elements=10,
            tube_arrangement="in-line",
        )
        self.feed_hot_exchanger = CrossFlowHeatExchanger1D(
            has_holdup=True,
            dynamic=dynamic_unit_models,
            cold_side={
                "property_package": self.h2_side_prop_params,
                "has_holdup": False,
                "dynamic": False,
                "has_pressure_change": False,
                "transformation_method": "dae.finite_difference",
                "transformation_scheme": "BACKWARD",
            },
            hot_side={
                "property_package": self.h2_side_prop_params,
                "has_holdup": False,
                "dynamic": False,
                "has_pressure_change": False,
                "transformation_method": "dae.finite_difference",
                "transformation_scheme": "BACKWARD",
            },
            shell_is_hot=True,
            flow_type=HeatExchangerFlowPattern.countercurrent,
            finite_elements=12,
            tube_arrangement="staggered",
        )
        self.feed_medium_exchanger = CrossFlowHeatExchanger1D(
            has_holdup=True,
            dynamic=dynamic_unit_models,
            cold_side={
                "property_package": self.h2_side_prop_params,
                "has_holdup": False,
                "dynamic": False,
                "has_pressure_change": False,
                "transformation_method": "dae.finite_difference",
                "transformation_scheme": "BACKWARD",
            },
            hot_side={
                "property_package": self.o2_side_prop_params,
                "has_holdup": False,
                "dynamic": False,
                "has_pressure_change": False,
                "transformation_method": "dae.finite_difference",
                "transformation_scheme": "BACKWARD",
            },
            shell_is_hot=True,
            finite_elements=6,
            flow_type=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement="staggered",
        )
        self.sweep_blower = gum.Compressor(
            doc="Sweep blower", property_package=self.o2_side_prop_params, dynamic=False
        )
        self.feed_heater = Heater1D(
            property_package=self.h2_side_prop_params,
            has_holdup=True,
            dynamic=dynamic_unit_models,
            has_fluid_holdup=False,
            has_pressure_change=False,
            finite_elements=4,
            tube_arrangement="in-line",
        )
        self.sweep_heater = Heater1D(
            property_package=self.o2_side_prop_params,
            has_holdup=True,
            dynamic=dynamic_unit_models,
            has_fluid_holdup=False,
            has_pressure_change=False,
            finite_elements=4,
            tube_arrangement="in-line",
        )
        self.condenser_flash = gum.Flash(
            property_package=self.h2_condensing_prop_params,
            has_heat_transfer=True,
            has_holdup=False,
            dynamic=False,
        )
        self.condenser_split = gum.Separator(
            dynamic=False,
            doc="Vent gas recirculation splitter",
            property_package=self.h2_side_prop_params,
            outlet_list=["out", "recycle"],
        )

        self.makeup_mix = gum.Mixer(
            dynamic=False,
            doc="Vent gas recirculation splitter",
            property_package=self.h2_side_prop_params,
            inlet_list=["makeup", "recycle"],
            momentum_mixing_type=gum.MomentumMixingType.none,
        )

        @self.makeup_mix.Constraint(self.time)
        def pressure_equality_eqn(b, t):
            return b.mixed_state[t].pressure == b.makeup_state[t].pressure

    def _add_arcs(self):
        self.ostrm01 = Arc(
            doc="SOEC sweep gas out to recycle splitter",
            source=self.soc_module.oxygen_outlet,
            destination=self.sweep_recycle_split.inlet,
        )
        self.hstrm01 = Arc(
            doc="SOEC hydrogen stream out to recycle splitter",
            source=self.soc_module.fuel_outlet,
            destination=self.feed_recycle_split.inlet,
        )
        self.ostrm02 = Arc(
            doc="SOEC sweep recycle to sweep mixer",
            source=self.sweep_recycle_split.recycle,
            destination=self.sweep_recycle_mix.recycle,
        )
        self.hstrm02 = Arc(
            doc="SOEC hydrogen recycle to feed mixer",
            source=self.feed_recycle_split.recycle,
            destination=self.feed_recycle_mix.recycle,
        )
        self.sweep03 = Arc(
            doc="Sweep mixer to sweep heater",
            source=self.sweep_recycle_mix.outlet,
            destination=self.sweep_heater.inlet,
        )
        self.feed03 = Arc(
            doc="Feed mixer to feed heater",
            source=self.feed_recycle_mix.outlet,
            destination=self.feed_heater.inlet,
        )
        self.sweep04 = Arc(
            doc="Sweep heater to SOEC",
            source=self.sweep_heater.outlet,
            destination=self.soc_module.oxygen_inlet,
        )
        self.feed04 = Arc(
            doc="Feed heater to SOEC",
            source=self.feed_heater.outlet,
            destination=self.soc_module.fuel_inlet,
        )
        self.ostrm03 = Arc(
            doc="Sweep to heat recovery hx",
            source=self.sweep_recycle_split.out,
            destination=self.sweep_exchanger.shell_inlet,
        )
        self.ostrm04 = Arc(
            doc="Sweep to medium temp heat recovery hx",
            source=self.sweep_exchanger.shell_outlet,
            destination=self.feed_medium_exchanger.shell_inlet,
        )
        self.sweep01 = Arc(
            doc="Sweep blower to translator",
            source=self.sweep_blower.outlet,
            destination=self.sweep_exchanger.tube_inlet,
        )
        self.sweep02 = Arc(
            doc="",
            source=self.sweep_exchanger.tube_outlet,
            destination=self.sweep_recycle_mix.feed,
        )
        self.hstrm03 = Arc(
            doc="",
            source=self.feed_recycle_split.out,
            destination=self.feed_hot_exchanger.shell_inlet,
        )
        self.hstrmShortcut = Arc(
            source=self.feed_hot_exchanger.shell_outlet,
            destination=self.condenser_flash.inlet,
        )
        self.hstrm06 = Arc(
            source=self.condenser_flash.vap_outlet,
            destination=self.condenser_split.inlet,
        )
        self.vgr = Arc(
            source=self.condenser_split.recycle, destination=self.makeup_mix.recycle
        )

        self.feed00 = Arc(
            source=self.makeup_mix.outlet,
            destination=self.feed_medium_exchanger.tube_inlet,
        )
        self.feed01 = Arc(
            doc="",
            source=self.feed_medium_exchanger.tube_outlet,
            destination=self.feed_hot_exchanger.tube_inlet,
        )
        self.feed02 = Arc(
            doc="",
            source=self.feed_hot_exchanger.tube_outlet,
            destination=self.feed_recycle_mix.feed,
        )
        pyo.TransformationFactory("network.expand_arcs").apply_to(self)

    def _add_constraints(self):
        for split in [
            self.feed_recycle_split,
            self.sweep_recycle_split,
            self.condenser_split,
        ]:
            split.recycle_split_fraction = pyo.Reference(
                split.split_fraction[:, "recycle"], ctype=pyo.Var
            )
            split.recycle_ratio = pyo.Var(
                self.time, units=pyo.units.dimensionless, bounds=(0, None)
            )

            @split.Constraint(self.time)
            def recycle_ratio_eqn(b, t):
                return b.recycle_ratio[t] == b.recycle_split_fraction[t] / (
                    1 - b.recycle_split_fraction[t]
                )

        self.h2_mass_production = pyo.Var(
            self.time, initialize=2, units=pyo.units.kg / pyo.units.s
        )

        @self.Constraint(self.time)
        def h2_mass_production_eqn(b, t):
            return b.h2_mass_production[t] == 0.002016 * (
                pyo.units.kg / pyo.units.mol
            ) * (
                b.condenser_split.out_state[t].flow_mol
                * b.condenser_split.out_state[t].mole_frac_comp["H2"]
                - b.makeup_mix.makeup_state[t].flow_mol
                * b.makeup_mix.makeup_state[t].mole_frac_comp["H2"]
            )

        self.h2_mass_consumption = pyo.Var(
            self.time, initialize=1, units=pyo.units.kg / pyo.units.s
        )

        @self.Constraint(self.time)
        def h2_mass_consumption_eqn(b, t):
            return b.h2_mass_consumption[t] == 0.002016 * (
                pyo.units.kg / pyo.units.mol
            ) * (
                b.makeup_mix.makeup_state[t].flow_mol
                * b.makeup_mix.makeup_state[t].mole_frac_comp["H2"]
            )

        self.makeup_mix.makeup_mole_frac_comp_H2 = pyo.Reference(
            self.makeup_mix.makeup.mole_frac_comp[:, "H2"]
        )
        self.makeup_mix.makeup_mole_frac_comp_H2O = pyo.Reference(
            self.makeup_mix.makeup.mole_frac_comp[:, "H2O"]
        )
        self.soc_module.fuel_inlet_mole_frac_comp_H2 = pyo.Reference(
            self.soc_module.fuel_inlet.mole_frac_comp[:, "H2"]
        )
        self.soc_module.fuel_inlet_mole_frac_comp_H2O = pyo.Reference(
            self.soc_module.fuel_inlet.mole_frac_comp[:, "H2O"]
        )
        self.soc_module.fuel_outlet_mole_frac_comp_H2 = pyo.Reference(
            self.soc_module.fuel_outlet.mole_frac_comp[:, "H2"]
        )
        self.soc_module.fuel_outlet_mole_frac_comp_H2O = pyo.Reference(
            self.soc_module.fuel_outlet.mole_frac_comp[:, "H2O"]
        )
        self.soc_module.oxygen_outlet_mole_frac_comp_O2 = pyo.Reference(
            self.soc_module.oxygen_outlet.mole_frac_comp[:, "O2"]
        )

        self.soec_water_consumption_rate = pyo.Var(self.time, initialize=0.75)

        @self.Constraint(self.time)
        def soec_water_consumption_rate_eqn(b, t):
            return b.soec_water_consumption_rate[t] == (
                b.makeup_mix.makeup_state[t].flow_mol
                * b.makeup_mix.makeup_state[t].mole_frac_comp["H2O"]
                - b.condenser_flash.liq_outlet.flow_mol[t]
                - b.condenser_split.out_state[t].flow_mol
                * b.condenser_split.out_state[t].mole_frac_comp["H2O"]
            )

        self.total_electric_power = pyo.Var(
            self.time, initialize=300e6, units=pyo.units.W
        )

        @self.Constraint(self.time)
        def total_electric_power_eqn(b, t):
            return b.total_electric_power[t] == (
                b.soc_module.electrical_work[t]
                + b.sweep_blower.control_volume.work[t]
                + b.sweep_heater.electric_heat_duty[t]
                + b.feed_heater.electric_heat_duty[t]
            )

        # Need new variables instead of just References because the temperature objects on the interconnect
        # are Expressions
        self.stack_fuel_inlet_temperature = pyo.Var(
            self.time, initialize=1000, units=pyo.units.K
        )
        self.stack_sweep_inlet_temperature = pyo.Var(
            self.time, initialize=1000, units=pyo.units.K
        )
        self.stack_core_temperature = pyo.Var(
            self.time, initialize=1000, units=pyo.units.K
        )

        @self.Constraint(self.time)
        def stack_fuel_inlet_temperature_eqn(b, t):
            return (
                b.stack_fuel_inlet_temperature[t]
                == b.soc_module.solid_oxide_cell.interconnect.temperature[t, 1, 1]
            )

        @self.Constraint(self.time)
        def stack_sweep_inlet_temperature_eqn(b, t):
            return (
                b.stack_sweep_inlet_temperature[t]
                == b.soc_module.solid_oxide_cell.interconnect.temperature[t, 1, 10]
            )

        @self.Constraint(self.time)
        def stack_core_temperature_eqn(b, t):
            return (
                b.stack_core_temperature[t]
                == (
                    b.soc_module.solid_oxide_cell.interconnect.temperature[t, 1, 5]
                    + b.soc_module.solid_oxide_cell.interconnect.temperature[t, 1, 6]
                )
                / 2
            )

    def _scaling(self):
        ssf = iscale.set_scaling_factor
        cst = iscale.constraint_scaling_transform

        ssf(self.total_electric_power, 1e-8)
        ssf(self.soec_water_consumption_rate, 1e-3)
        ssf(self.feed_recycle_split.recycle_ratio, 1)
        ssf(self.sweep_recycle_split.recycle_ratio, 1)
        ssf(self.condenser_split.recycle_ratio, 1)
        ssf(self.h2_mass_production, 1)

        scale_indexed_constraint(self.total_electric_power_eqn, 1e-8)
        scale_indexed_constraint(self.soec_water_consumption_rate_eqn, 1e-3)

        ssf(self.condenser_flash.control_volume.heat, 1e-7)

        ssf(self.feed_heater.control_volume.area, 1e-1)
        ssf(self.sweep_heater.control_volume.area, 1e-1)
        ssf(self.feed_heater.control_volume.heat, 1e-6)
        ssf(self.feed_heater.electric_heat_duty, 1e-6)
        ssf(self.feed_heater.control_volume._enthalpy_flow, 1e-8)
        ssf(self.feed_heater.control_volume.enthalpy_flow_dx, 1e-7)
        ssf(self.feed_heater.heat_holdup, 1e-9)

        ssf(self.sweep_heater.control_volume.heat, 1e-6)
        ssf(self.sweep_heater.electric_heat_duty, 1e-6)
        ssf(self.sweep_heater.control_volume._enthalpy_flow, 1e-8)
        ssf(self.sweep_heater.control_volume.enthalpy_flow_dx, 1e-7)
        ssf(self.sweep_heater.heat_holdup, 1e-9)

        def scale_hx(hx):
            shell = hx.hot_side
            tube = hx.cold_side
            ssf(shell.area, 1e-1)
            ssf(hx.hot_side.heat, 1e-6)
            ssf(tube.area, 1)
            ssf(hx.cold_side.heat, 1e-6)
            ssf(shell._enthalpy_flow, 1e-8)
            ssf(tube._enthalpy_flow, 1e-8)
            ssf(shell.enthalpy_flow_dx, 1e-7)
            ssf(tube.enthalpy_flow_dx, 1e-7)
            ssf(hx.heat_holdup, 1e-8)

        scale_hx(self.sweep_exchanger)
        scale_hx(self.feed_medium_exchanger)
        scale_hx(self.feed_hot_exchanger)

        for t in self.time:
            ssf(self.sweep_recycle_mix.feed_state[t].enth_mol_phase["Vap"], 1e-4)
            ssf(self.sweep_recycle_mix.recycle_state[t].enth_mol_phase["Vap"], 1e-4)
            ssf(self.sweep_recycle_mix.mixed_state[t].enth_mol_phase["Vap"], 1e-4)
            ssf(self.feed_recycle_mix.feed_state[t].enth_mol_phase["Vap"], 1e-4)
            ssf(self.feed_recycle_mix.recycle_state[t].enth_mol_phase["Vap"], 1e-4)
            ssf(self.feed_recycle_mix.mixed_state[t].enth_mol_phase["Vap"], 1e-4)
            cst(self.sweep_recycle_mix.pressure_equality_eqn[t], 1e-5)
            cst(self.feed_recycle_mix.pressure_equality_eqn[t], 1e-5)
            cst(self.makeup_mix.pressure_equality_eqn[t], 1e-5)

            ssf(
                self.sweep_blower.control_volume.properties_in[t].enth_mol_phase["Vap"],
                1e-4,
            )
            ssf(
                self.sweep_blower.control_volume.properties_out[t].enth_mol_phase[
                    "Vap"
                ],
                1e-4,
            )
            ssf(self.sweep_blower.properties_isentropic[t].enth_mol_phase["Vap"], 1e-4)
            ssf(self.sweep_blower.control_volume.work[t], 1e-6)

            ssf(self.stack_fuel_inlet_temperature[t], 1e-2)
            ssf(self.stack_sweep_inlet_temperature[t], 1e-2)
            ssf(self.stack_core_temperature[t], 1e-2)
            cst(self.stack_fuel_inlet_temperature_eqn[t], 1e-2)
            cst(self.stack_sweep_inlet_temperature_eqn[t], 1e-2)
            cst(self.stack_core_temperature_eqn[t], 1e-2)

        iscale.propagate_indexed_component_scaling_factors(self)

    @staticmethod
    def _set_gas_port(port, F, T, P, y, fix=True):
        port.temperature[:] = T
        port.pressure[:] = P
        port.flow_mol[:] = F
        for c, v in y.items():
            port.mole_frac_comp[:, c] = v
        if fix:
            port.temperature.fix()
            port.pressure.fix()
            port.flow_mol.fix()
            port.mole_frac_comp.fix()

    def _set_initial_inputs(self):
        self.makeup_mix.makeup.pressure.fix(1.2e5)
        self.makeup_mix.makeup.temperature.fix(378.15)
        self.makeup_mix.makeup.mole_frac_comp[:, "Ar"].fix(0.0008)
        self.makeup_mix.makeup.mole_frac_comp[:, "N2"].fix(0.0002)

        sweep_comp = self.sweep_comp.copy()
        sweep_comp["H2"] = 1e-19

        self.sweep_blower.inlet.temperature.fix(288.15)
        self.sweep_blower.inlet.pressure.fix(101300)
        for c, v in self.sweep_comp.items():
            self.sweep_blower.inlet.mole_frac_comp[:, c].fix(v)

        # Recycle splits
        self.sweep_recycle_split.split_fraction[:, "recycle"].set_value(0.50)
        self.feed_recycle_split.split_fraction[:, "recycle"].set_value(0.5)
        self.sweep_blower.efficiency_isentropic.fix(0.85)
        self.sweep_blower.control_volume.properties_out[:].pressure.fix(1.2e5)

        def fix_heater_params(heater):
            heater.di_tube.fix(0.0525018)
            heater.thickness_tube.fix(0.0039116)
            heater.pitch_x.fix(0.1)
            heater.pitch_y.fix(0.1)
            heater.length_tube_seg.fix(10)
            heater.number_passes.fix(1)
            heater.rfouling = 0.0001
            heater.fcorrection_htc_shell.fix(1)
            heater.cp_wall = 502.4

        fix_heater_params(self.feed_heater)
        self.feed_heater.number_rows_per_pass.fix(40)
        self.feed_heater.number_columns_per_pass.fix(40)
        self.feed_heater.electric_heat_duty[:].fix(2840706)

        fix_heater_params(self.sweep_heater)
        self.sweep_heater.number_rows_per_pass.fix(60)
        self.sweep_heater.number_columns_per_pass.fix(60)
        self.sweep_heater.electric_heat_duty[:].fix(4807703.46412979)

        self.condenser_flash.control_volume.deltaP.fix(0)

        def fix_hx_params(hx):
            hx.pitch_x.fix(0.1)
            hx.pitch_y.fix(0.1)
            hx.therm_cond_wall = 43.0
            hx.rfouling_tube = 0.0001
            hx.rfouling_shell = 0.0001
            hx.fcorrection_htc_tube.fix(1)
            hx.fcorrection_htc_shell.fix(1)

            hx.cp_wall.value = 502.4

        fix_hx_params(self.sweep_exchanger)
        # number of tube bundle segments, typically it is the same as or a multiple of the "finite_elements" in the config
        self.sweep_exchanger.number_passes.fix(10)
        # number of tube columns in the direction perpendicular to the shell side flow direction
        self.sweep_exchanger.number_columns_per_pass.fix(50)
        # number of tube rows at tube side inlet
        self.sweep_exchanger.number_rows_per_pass.fix(25)
        self.sweep_exchanger.di_tube.fix(0.0525018)
        self.sweep_exchanger.length_tube_seg.fix(5.5)
        self.sweep_exchanger.thickness_tube.fix(0.0039116)

        fix_hx_params(self.feed_medium_exchanger)

        self.feed_medium_exchanger.di_tube.fix(0.0525018)
        # tube thickness
        self.feed_medium_exchanger.thickness_tube.fix(0.0039116)
        self.feed_medium_exchanger.length_tube_seg.fix(3.5)
        # number of tube bundle segments, typically it is the same as or a multiple of the "finite_elements" in the config
        self.feed_medium_exchanger.number_passes.fix(3)
        # number of tube columns in the direction perpendicular to the shell side flow direction
        self.feed_medium_exchanger.number_columns_per_pass.fix(40)
        # number of tube rows at tube side inlet
        self.feed_medium_exchanger.number_rows_per_pass.fix(25)

        fix_hx_params(self.feed_hot_exchanger)

        self.feed_hot_exchanger.di_tube.fix(0.0525018)
        self.feed_hot_exchanger.thickness_tube.fix(0.0039116)
        self.feed_hot_exchanger.length_tube_seg.fix(4.3)
        self.feed_hot_exchanger.number_passes.fix(12)
        self.feed_hot_exchanger.number_columns_per_pass.fix(50)
        self.feed_hot_exchanger.number_rows_per_pass.fix(25)

    def initialize_build(
        self,
        outlvl=idaeslog.NOTSET,
        solver="ipopt",
        optarg=None,
        load_from=None,
        save_to="soc_flowsheet_init.json.gz",
        fuel_cell_mode=False,
    ):
        if self.config.dynamic:
            raise NotImplementedError(
                "Initialization is not supported for dynamic models."
            )

        if load_from is not None:
            if os.path.exists(load_from):
                init_log.info_low(f"SOC flowsheet load initial from {load_from}")
                # Here suffix=False avoids loading scaling factors
                iutil.from_json(
                    self, fname=load_from, wts=iutil.StoreSpec(suffix=False)
                )
                return

        solver_obj = get_solver(solver, optarg)
        init_log = idaeslog.getInitLogger(self.name, outlvl)
        solve_log = idaeslog.getSolveLogger(self.name, outlvl)

        def safe_solve(blk):
            assert degrees_of_freedom(blk) == 0
            with idaeslog.solver_log(solve_log, idaeslog.DEBUG) as slc:
                results = solver_obj.solve(blk, tee=slc.tee)
            pyo.assert_optimal_termination(results)

        if fuel_cell_mode:
            feed_comp = {"H2": 0.969, "H2O": 0.03, "N2": 0.0002, "Ar": 0.0008}
            self.makeup_mix.makeup.flow_mol.fix(474.75)
            for t in self.time:
                for j in self.makeup_mix.makeup_state.component_list:
                    self.makeup_mix.makeup.mole_frac_comp[t, j].fix(feed_comp[j])
        else:
            feed_comp = {"H2": 1e-14, "H2O": 0.999 - 1e-14, "N2": 0.0002, "Ar": 0.0008}
            self.makeup_mix.makeup.flow_mol.fix(1320)
            for t in self.time:
                for j in self.makeup_mix.makeup_state.component_list:
                    self.makeup_mix.makeup.mole_frac_comp[t, j].fix(feed_comp[j])

        if fuel_cell_mode:
            self._set_gas_port(
                self.feed_recycle_mix.feed,
                F=480,
                T=921.34,
                P=1.2e5,
                y={"H2": 0.96, "H2O": 0.03, "Ar": 0.008, "N2": 0.002},
                fix=False,
            )
            self._set_gas_port(
                self.feed_recycle_mix.recycle,
                F=250,
                T=921.34,
                P=1.2e5,
                y={"H2": 0.71, "H2O": 0.28, "Ar": 0.008, "N2": 0.002},
                fix=False,
            )
            self._set_gas_port(
                self.makeup_mix.recycle,
                F=10,
                T=320.53,
                P=1.2e5,
                y={
                    "H2": 0.71 / 0.75,
                    "H2O": 0.04,
                    "Ar": 0.008 / 0.75,
                    "N2": 0.002 / 0.75,
                },
                fix=False,
            )
            self.sweep_blower.inlet.flow_mol.fix(6098.2)
            self._set_gas_port(
                self.sweep_recycle_mix.feed,
                F=6120.0,
                T=859.60,
                P=1.2e5,
                y={
                    "O2": 0.20740,
                    "H2O": 0.0099000,
                    "CO2": 0.00030000,
                    "N2": 0.77320,
                    "Ar": 0.0092000,
                },
                fix=False,
            )
            self._set_gas_port(
                self.sweep_recycle_mix.recycle,
                F=5892.0,
                T=1009.7,
                P=1.2e5,
                y={
                    "O2": 0.17673,
                    "H2O": 0.010283,
                    "CO2": 0.00031161,
                    "N2": 0.80312,
                    "Ar": 0.0095560,
                },
                fix=False,
            )
        else:
            self._set_gas_port(
                self.feed_recycle_mix.feed, F=1325, T=897, P=1.2e5, y=feed_comp
            )
            self._set_gas_port(
                self.feed_recycle_mix.feed, F=1325, T=897, P=1.2e5, y=feed_comp
            )
            feed_comp["H2"] = 0.7
            feed_comp["H2O"] = 0.299
            self._set_gas_port(
                self.feed_recycle_mix.recycle,
                F=1325,
                T=1020,
                P=1.2e5,
                y=feed_comp,
                fix=False,
            )
            self._set_gas_port(
                self.makeup_mix.recycle,
                F=1,
                T=(273.15 + 105),
                P=1.2e5,
                y={"H2": 0.85, "H2O": 0.15, "N2": 0.0002, "Ar": 0.0008},
            )
            sweep_comp = self.sweep_comp.copy()
            self._set_gas_port(
                self.sweep_recycle_mix.feed, F=2250, T=990, P=1.2e5, y=sweep_comp
            )
            self.sweep_blower.inlet.flow_mol.fix(2250)
        if fuel_cell_mode:
            pass
        else:
            recycle_comp = {
                "O2": 0.35,
                "H2O": (1 - 0.35) / (1 - 0.2074) * 0.0099,
                "CO2": (1 - 0.35) / (1 - 0.2074) * 0.0003,
                "N2": (1 - 0.35) / (1 - 0.2074) * 0.7732,
                "Ar": (1 - 0.35) / (1 - 0.2074) * 0.0092,
            }
            self._set_gas_port(
                self.sweep_recycle_mix.recycle,
                F=2750,
                T=1020,
                P=1.2e5,
                y=recycle_comp,
                fix=False,
            )

        self.sweep_blower.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.sweep01)

        self.feed_recycle_mix.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        self.sweep_recycle_mix.initialize(outlvl=outlvl, solver=solver, optarg=optarg)

        propagate_state(self.feed03)
        propagate_state(self.sweep03)
        self.sweep_heater.default_initializer(
            solver=solver, solver_options=optarg, output_level=outlvl
        ).initialize(model=self.sweep_heater)
        self.feed_heater.default_initializer(
            solver=solver, solver_options=optarg, output_level=outlvl
        ).initialize(model=self.feed_heater)
        propagate_state(self.feed04)
        propagate_state(self.sweep04)

        if fuel_cell_mode:
            self.soc_module.potential_cell.fix(0.902)
            self.soc_module.initialize(
                current_density_guess=0,  # 4000, Don't know why the initialization has so much trouble with the real value
                temperature_guess=980,
                outlvl=outlvl,
                solver=solver,
                optarg=optarg,
            )
            self.sweep_recycle_split.split_fraction[:, "recycle"].fix(0.50)
            self.feed_recycle_split.split_fraction[:, "recycle"].fix(0.01)
        else:
            self.soc_module.potential_cell.fix(1.3)
            self.soc_module.initialize(
                current_density_guess=0,
                temperature_guess=1020.15,
                outlvl=outlvl,
                solver=solver,
                optarg=optarg,
            )
            self.sweep_recycle_split.split_fraction[:, "recycle"].fix(0.50)
            self.feed_recycle_split.split_fraction[:, "recycle"].fix(0.5)

        propagate_state(self.ostrm01)
        self.sweep_recycle_split.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.ostrm02)
        propagate_state(self.ostrm03)

        propagate_state(self.hstrm01)
        self.feed_recycle_split.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm02)
        propagate_state(self.hstrm03)

        self.sweep_exchanger.default_initializer(
            solver=solver, solver_options=optarg, output_level=outlvl
        ).initialize(model=self.sweep_exchanger)

        propagate_state(self.ostrm04)

        self.makeup_mix.initialize(outlvl=outlvl, solver=solver, optarg=optarg)

        propagate_state(self.feed00)

        self.feed_medium_exchanger.default_initializer(
            solver=solver, solver_options=optarg, output_level=outlvl
        ).initialize(model=self.feed_medium_exchanger)

        propagate_state(self.feed01)

        self.feed_hot_exchanger.default_initializer(
            solver=solver, solver_options=optarg, output_level=outlvl
        ).initialize(model=self.feed_hot_exchanger)

        propagate_state(self.feed02)
        propagate_state(self.hstrmShortcut)

        self.condenser_flash.control_volume.properties_out[:].temperature.fix(
            273.15 + 50
        )
        self.condenser_flash.initialize(outlvl=outlvl, solver=solver, optarg=optarg)

        propagate_state(self.hstrm06)

        if fuel_cell_mode:
            self.condenser_split.split_fraction[:, "recycle"].fix(0.5)
            self.condenser_split.split_fraction[:, "out"].value = 0.5
        else:
            self.condenser_split.split_fraction[:, "recycle"].fix(0.0001)
            self.condenser_split.split_fraction[:, "out"].value = 0.9999

        self.condenser_split.initialize(outlvl=outlvl, solver=solver, optarg=optarg)

        propagate_state(self.vgr)

        self.makeup_mix.initialize(outlvl=outlvl, solver=solver, optarg=optarg)

        propagate_state(self.feed00)

        # Time for final solve
        x1 = self.feed_heater.control_volume.length_domain.last()
        self.feed_heater.control_volume.properties[:, x1].temperature.fix()
        self.feed_heater.electric_heat_duty.unfix()
        x1 = self.sweep_heater.control_volume.length_domain.last()
        self.sweep_heater.control_volume.properties[:, x1].temperature.fix()
        self.sweep_heater.electric_heat_duty.unfix()

        self.feed_recycle_mix.feed.unfix()
        self.feed_recycle_mix.recycle.unfix()
        self.sweep_recycle_mix.feed.unfix()
        self.sweep_recycle_mix.recycle.unfix()
        self.makeup_mix.recycle.unfix()

        safe_solve(self)

        self.feed_heater.control_volume.properties[:, :].temperature.unfix()
        self.feed_heater.electric_heat_duty.fix()
        self.sweep_heater.control_volume.properties[:, :].temperature.unfix()
        self.sweep_heater.electric_heat_duty.fix()

        for split in [
            self.feed_recycle_split,
            self.sweep_recycle_split,
            self.condenser_split,
        ]:
            split.split_fraction.unfix()
            split.recycle_ratio.fix()

        if save_to is not None:
            iutil.to_json(self, fname=save_to)
            init_log.info_low(f"Initialization saved to {save_to}")

    def _add_tags(self):
        t0 = self.time.first()
        tag_group = iutil.ModelTagGroup()
        self.tags_streams = tag_group
        stream_states = tables.stream_states_dict(
            tables.arcs_to_stream_dict(
                self,
                descend_into=False,
                additional={
                    "sweep00": self.sweep_blower.inlet,
                    "feed00": self.feed_medium_exchanger.tube_inlet,
                    "hstrm04": self.feed_hot_exchanger.shell_outlet,
                    "ostrm05": self.feed_medium_exchanger.shell_outlet,
                },
            ),
            time_point=t0,
        )
        for i, s in stream_states.items():  # create the tags for steam quantities
            tag_group[f"{i}_F"] = iutil.ModelTag(
                doc=f"{i}: mass flow",
                expr=s.flow_mass,
                format_string="{:.3f}",
                display_units=pyo.units.kg / pyo.units.s,
            )
            tag_group[f"{i}_Fmol"] = iutil.ModelTag(
                doc=f"{i}: mole flow",
                expr=s.flow_mol,
                format_string="{:.3f}",
                display_units=pyo.units.kmol / pyo.units.s,
            )
            tag_group[f"{i}_Fvol"] = iutil.ModelTag(
                doc=f"{i}: volumetric flow",
                expr=s.flow_vol,
                format_string="{:.3f}",
                display_units=pyo.units.m**3 / pyo.units.s,
            )
            tag_group[f"{i}_P"] = iutil.ModelTag(
                doc=f"{i}: pressure",
                expr=s.pressure,
                format_string="{:.3f}",
                display_units=pyo.units.bar,
            )
            tag_group[f"{i}_T"] = iutil.ModelTag(
                doc=f"{i}: temperature",
                expr=s.temperature,
                format_string="{:.2f}",
                display_units=pyo.units.K,
            )
            try:
                tag_group[f"{i}_vf"] = iutil.ModelTag(
                    doc=f"{i}: vapor fraction",
                    expr=100 * s.vapor_frac,
                    format_string="{:.2f}",
                    display_units="%",
                )
            except AttributeError:  # If there is no vapor fraction it's not steam
                tag_group[f"{i}_yH2O"] = iutil.ModelTag(
                    doc=f"{i}: mole percent H2O",
                    expr=100,
                    format_string="{:.3f}",
                    display_units="%",
                )
            try:  # gas (not steam) properties have mole fractions
                for c in s.mole_frac_comp:
                    tag_group[f"{i}_y{c}"] = iutil.ModelTag(
                        doc=f"{i}: mole percent {c}",
                        expr=s.mole_frac_comp[c] * 100,
                        format_string="{:.3f}",
                        display_units="%",
                    )
            except AttributeError:  # If there is no mole fraction it's steam
                tag_group[f"{i}_yH2O"] = iutil.ModelTag(
                    doc=f"{i}: mole percent H2O",
                    expr=100,
                    format_string="{:.3f}",
                    display_units="%",
                )

        tag_group = iutil.ModelTagGroup()
        self.tags_output = tag_group
        tag_group["cell_potential"] = iutil.ModelTag(
            doc="Cell potential",
            expr=self.soc_module.potential_cell[t0],
            format_string="{:.3f}",
            display_units=pyo.units.volts,
        )
        tag_group["soec_current"] = iutil.ModelTag(
            doc="SOEC electrical current",
            expr=self.soc_module.number_cells
            * sum(
                self.soc_module.solid_oxide_cell.current_density[t0, iz]
                * self.soc_module.solid_oxide_cell.fuel_electrode.xface_area[iz]
                for iz in self.soc_module.solid_oxide_cell.iznodes
            ),
            format_string="{:.3f}",
            display_units=pyo.units.MA,
        )
        tag_group["soec_power"] = iutil.ModelTag(
            doc="SOEC electric power",
            expr=self.soc_module.electrical_work[t0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["h2_mass_production"] = iutil.ModelTag(
            doc="H2 mass production rate",
            expr=self.h2_mass_production[t0],
            format_string="{:.3f}",
            display_units=pyo.units.kg / pyo.units.s,
        )
        tag_group["h2_mass_consumption"] = iutil.ModelTag(
            doc="H2 mass consumption rate-excludes H2 leaving through condenser splitter",
            expr=self.h2_mass_consumption[t0],
            format_string="{:.3f}",
            display_units=pyo.units.kg / pyo.units.s,
        )
        tag_group["feed_heater_power"] = iutil.ModelTag(
            doc="Feed heater power",
            expr=self.feed_heater.electric_heat_duty[t0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["sweep_heater_power"] = iutil.ModelTag(
            doc="Sweep heater power",
            expr=self.sweep_heater.electric_heat_duty[t0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["total_electric_power"] = iutil.ModelTag(
            doc="Total electric power for SOEC and auxiliaries",
            expr=self.total_electric_power[t0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["vent_gas_recycle_ratio"] = iutil.ModelTag(
            doc="Vent gas recycle ratio",
            expr=self.condenser_split.recycle_ratio[t0],
            format_string="{:.1f}",
            display_units=pyo.units.dimensionless,
        )
        tag_group = iutil.ModelTagGroup()
        self.tags_input = tag_group

    @staticmethod
    def _stream_col_gen(tag_group):
        for tag in tag_group.values():
            spltstr = tag.doc.split(":")
            stream = spltstr[0].strip()
            col = f"{spltstr[1].strip()} ({tag.get_unit_str()})"
            yield tag, stream, col

    @staticmethod
    def _stream_table(tag_group):
        rows = set()
        cols = set()
        tags = []
        for tag, stream, col in SoecStandaloneFlowsheetData._stream_col_gen(tag_group):
            rows.add(stream)
            cols.add(col)
            tags.append((tag, stream, col))
        df = pd.DataFrame(index=sorted(rows), columns=sorted(cols))
        for tag, stream, col in tags:
            df.at[stream, col] = tag.get_display_value()
        return df

    def streams_dataframe(self):
        return self._stream_table(self.tags_streams)

    def write_pfd(self, fname=None):
        """Add model results to the flowsheet template.  If fname is specified,
        this saves the resulting svg to a file.  If fname is not specified, it
        returns the svg string.
        Args:
            fname: Name of file to save svg.  If None, return the svg string
        Returns: (None or Str)
        """
        infilename = os.path.join(this_file_dir(), "soc_dynamic_template.svg")
        with open(infilename, "r") as f:
            s = svg_tag(svg=f, tag_group=self.tags_streams, outfile=None)
        s = svg_tag(svg=s, tag_group=self.tags_output, outfile=None)
        s = svg_tag(svg=s, tag_group=self.tags_input, outfile=fname)
        if fname is None:
            return s

    def add_controllers(self, variable_pairings):
        assert self.config.dynamic
        for mv, (
            controller_name,
            cv,
            controller_type,
            mv_bound_type,
            antiwindup_type,
        ) in variable_pairings.items():
            assert mv in self.manipulated_variables
            controller = PIDController(
                process_var=cv,
                manipulated_var=mv,
                controller_type=controller_type,
                mv_bound_type=mv_bound_type,
                antiwindup_type=antiwindup_type,
                calculate_initial_integral=False,
            )
            self.controller_set.add(controller)
            self.add_component(controller_name, controller)
            if controller_type == ControllerType.PI:
                controller.mv_integral_component[self.time.first()].value = 0

            self.manipulated_variables.remove(mv)
            self.manipulated_variables.add(controller.setpoint)
            self.manipulated_variables.add(controller.mv_ref)
            mv.unfix()

            for t in self.time:
                sf_cv = iscale.get_scaling_factor(cv[t], default=1, warning=True)
                iscale.set_scaling_factor(controller.setpoint[t], sf_cv)
                sf_mv = iscale.get_scaling_factor(mv[t], default=1, warning=True)
                iscale.set_scaling_factor(controller.mv_ref[t], sf_mv)
                iscale.constraint_scaling_transform(controller.mv_eqn[t], sf_mv)

    def _make_temperature_gradient_terms(self):
        soec = self.soc_module.solid_oxide_cell
        dz = soec.zfaces.at(2) - soec.zfaces.at(1)
        # Going to assume that the zfaces are evenly spaced
        for iz in soec.iznodes:
            assert abs(soec.zfaces.at(iz + 1) - soec.zfaces.at(iz) - dz) < 1e-8
        dz = dz * soec.length_z

        def finite_difference(expr, t, ix, iz):
            # Since this is mostly for reference, no need to worry about upwinding or whatever
            if iz == soec.iznodes.first():
                if ix is None:
                    return (
                        -1.5 * expr[t, iz] + 2 * expr[t, iz + 1] - 0.5 * expr[t, iz + 2]
                    ) / dz
                else:
                    return (
                        -1.5 * expr[t, ix, iz]
                        + 2 * expr[t, ix, iz + 1]
                        - 0.5 * expr[t, ix, iz + 2]
                    ) / dz
            elif iz == soec.iznodes.last():
                if ix is None:
                    return (
                        1.5 * expr[t, iz] - 2 * expr[t, iz - 1] + 0.5 * expr[t, iz - 2]
                    ) / dz
                else:
                    return (
                        1.5 * expr[t, ix, iz]
                        - 2 * expr[t, ix, iz - 1]
                        + 0.5 * expr[t, ix, iz - 2]
                    ) / dz
            else:
                if ix is None:
                    return (0.5 * expr[t, iz + 1] - 0.5 * expr[t, iz - 1]) / dz
                else:
                    return (0.5 * expr[t, ix, iz + 1] - 0.5 * expr[t, ix, iz - 1]) / dz

        soec.dtemperature_z_dz = pyo.Var(
            self.time, soec.iznodes, initialize=0, units=pyo.units.K / pyo.units.m
        )

        @soec.Constraint(self.time, soec.iznodes)
        def dtemperature_z_dz_eqn(b, t, iz):
            return b.dtemperature_z_dz[t, iz] == finite_difference(
                b.temperature_z, t, None, iz
            )

        soec.fuel_electrode.dtemperature_dz = pyo.Var(
            self.time,
            soec.fuel_electrode.ixnodes,
            soec.fuel_electrode.iznodes,
            initialize=0,
            units=pyo.units.K / pyo.units.m,
        )

        @soec.fuel_electrode.Constraint(
            self.time, soec.fuel_electrode.ixnodes, soec.fuel_electrode.iznodes
        )
        def dtemperature_dz_eqn(b, t, ix, iz):
            return b.dtemperature_dz[t, ix, iz] == finite_difference(
                b.temperature, t, ix, iz
            )

        if soec.fuel_electrode.config.dynamic:
            soec.fuel_electrode.d2temperature_dzdt = DerivativeVar(
                soec.fuel_electrode.dtemperature_dz, wrt=self.time, initialize=0
            )
        else:

            @soec.fuel_electrode.Expression(
                self.time, soec.fuel_electrode.ixnodes, soec.fuel_electrode.iznodes
            )
            def d2temperature_dzdt(b, t, ix, iz):
                return 0 * pyo.units.K / pyo.units.m / pyo.units.s

        soec.fuel_electrode.d2temperature_dzdt_dummy = pyo.Var(
            self.time,
            soec.fuel_electrode.ixnodes,
            soec.fuel_electrode.iznodes,
            initialize=0,
        )

        @soec.fuel_electrode.Constraint(
            self.time, soec.fuel_electrode.ixnodes, soec.fuel_electrode.iznodes
        )
        def d2temperature_dzdt_dummy_eqn(b, t, ix, iz):
            return (
                b.d2temperature_dzdt[t, ix, iz] == b.d2temperature_dzdt_dummy[t, ix, iz]
            )

        soec.interconnect.dtemperature_dz = pyo.Var(
            self.time,
            soec.interconnect.ixnodes,
            soec.interconnect.iznodes,
            initialize=0,
            units=pyo.units.K / pyo.units.m,
        )

        @soec.interconnect.Constraint(
            self.time, soec.interconnect.ixnodes, soec.interconnect.iznodes
        )
        def dtemperature_dz_eqn(b, t, ix, iz):
            return b.dtemperature_dz[t, ix, iz] == finite_difference(
                b.temperature, t, ix, iz
            )

        vars = [
            soec.dtemperature_z_dz,
            soec.fuel_electrode.dtemperature_dz,
            soec.interconnect.dtemperature_dz,
        ]
        cons = [
            soec.dtemperature_z_dz_eqn,
            soec.fuel_electrode.dtemperature_dz_eqn,
            soec.interconnect.dtemperature_dz_eqn,
        ]
        for var, con in zip(vars, cons):
            for idx, element in var.items():
                iscale.set_scaling_factor(element, 5e-3)
                iscale.constraint_scaling_transform(con[idx], 5e-3)

    def set_performance_bounds(self):
        set_indexed_variable_bounds(self.soc_module.potential_cell, [0.7, 1.4])
        set_indexed_variable_bounds(self.feed_heater.electric_heat_duty, (0, 2e6))
        set_indexed_variable_bounds(self.sweep_heater.electric_heat_duty, (0, 4e6))

        set_indexed_variable_bounds(
            self.soc_module.solid_oxide_cell.fuel_electrode.dtemperature_dz, (-750, 750)
        )

        for t in self.time:
            self.feed_recycle_split.split_fraction[t, "recycle"].bounds = (1e-4, 1)
            self.sweep_recycle_split.split_fraction[t, "recycle"].bounds = (1e-4, 1)
            self.condenser_split.split_fraction[t, "recycle"].bounds = (1e-4, 1)

    def make_performance_constraints(self):
        if len(self.time) > 1:
            raise NotImplementedError(
                "Performance constraints are implemented only for steady-state target problems."
            )
        t0 = self.time.first()

        @self.soc_module.solid_oxide_cell.Constraint(
            self.time, self.soc_module.solid_oxide_cell.iznodes
        )
        def temperature_upper_bound_eqn(b, t, iz):
            return b.fuel_electrode.temperature[t, 1, iz] <= 750 + 273.15

        scale_indexed_constraint(
            self.soc_module.solid_oxide_cell.temperature_upper_bound_eqn, 1e-2
        )

        delta_T_limit = 75

        @self.Constraint(self.time)
        def thermal_gradient_eqn_1(b, t):
            return (
                b.soc_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 1]
                - b.soc_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 10]
            ) <= delta_T_limit

        @self.Constraint(self.time)
        def thermal_gradient_eqn_2(b, t):
            return (
                b.soc_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 10]
                - b.soc_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 1]
            ) <= delta_T_limit

        @self.Constraint(self.time)
        def thermal_gradient_eqn_3(b, t):
            return (
                b.soc_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 1]
                - b.soc_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 10]
            ) >= -delta_T_limit

        @self.Constraint(self.time)
        def thermal_gradient_eqn_4(b, t):
            return (
                b.soc_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 10]
                - b.soc_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 1]
            ) >= -delta_T_limit

        iscale.constraint_scaling_transform(self.thermal_gradient_eqn_1[t0], 1e-2)
        iscale.constraint_scaling_transform(self.thermal_gradient_eqn_2[t0], 1e-2)
        iscale.constraint_scaling_transform(self.thermal_gradient_eqn_3[t0], 1e-2)
        iscale.constraint_scaling_transform(self.thermal_gradient_eqn_4[t0], 1e-2)

    def fix_initial_conditions(self, t=None):
        if t is None:
            t = self.time.first()
        soec = self.soc_module.solid_oxide_cell
        soec.mean_temperature_eqn[t, :].activate()
        soec.fuel_electrode.int_energy_density_solid[t, :, :].fix()
        if not self.config.thin_electrolyte_and_oxygen_electrode:
            raise NotImplementedError(
                "Fixing initial conditions for non-thin electrolyte and "
                "oxygen electrode has not been implemented."
            )
        if self.config.include_interconnect:
            soec.interconnect.int_energy_density_solid[t, :, :].fix()

        soec.fuel_electrode.d2temperature_dzdt_dummy[t, :, :].fix()
        for hx in [
            self.sweep_exchanger,
            self.feed_medium_exchanger,
            self.feed_hot_exchanger,
        ]:
            hx.temp_wall_center_eqn[t, :].deactivate()
            hx.heat_holdup[t, :].fix()

        for heater in [self.feed_heater, self.sweep_heater]:
            heater.temp_wall_center_eqn[t, :].deactivate()
            heater.heat_holdup[t, :].fix()

        for controller in self.controller_set:
            if controller.config.controller_type in [
                ControllerType.PI,
                ControllerType.PID,
            ]:
                controller.mv_integral_component[t].fix()
            if controller.config.controller_type in [
                ControllerType.PD,
                ControllerType.PID,
            ]:
                controller.derivative_term[t].fix(0)
