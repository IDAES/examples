import os
import pandas as pd
import numpy as np

import pyomo.environ as pyo
from pyomo.network import Arc, Port
from pyomo.common.fileutils import this_file_dir

import idaes
from idaes.core import FlowsheetBlockData, declare_process_block_class, UnitModelBlock
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.models.properties.modular_properties.base.generic_property import (
    GenericParameterBlock,
    GenericStateBlockData
)
import idaes.core.util.scaling as iscale
import idaes.core.util.exceptions as idaes_except
from idaes.models_extra.power_generation.properties.natural_gas_PR import get_prop, EosType
from idaes.models_extra.power_generation.unit_models.soc_submodels import SolidOxideModuleSimple
import idaes.models.unit_models as gum
from idaes.models.unit_models.heat_exchanger import (
    HeatExchangerFlowPattern,
    delta_temperature_lmtd_smooth_callback
)
import idaes.models_extra.power_generation.unit_models.helm as hum
from idaes.models.properties import iapws95
from idaes.core.util.initialization import propagate_state
from idaes.core.util.math import smooth_min, smooth_max
from idaes.core.util.model_diagnostics import DegeneracyHunter
from idaes.core.solvers import get_solver
import idaes.logger as idaeslog
import idaes.core.util as iutil
import idaes.core.util.tables as tables
from idaes.core.util.tags import svg_tag


def set_indexed_variable_bounds(var, bounds):
    for idx, subvar in var.items():
        subvar.bounds = bounds


@declare_process_block_class("SoecStandaloneFlowsheet")
class SoecStandaloneFlowsheetData(FlowsheetBlockData):
    sweep_comp = {
        "O2": 0.2074,
        "H2O": 0.0099,
        "CO2": 0.0003,
        "N2": 0.7732,
        "Ar": 0.0092,
    }
    feed_comp = {
        "H2": 1e-19,
        "H2O": 1.0,
    }

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

    def _add_properties(self):
        self.steam_prop_params = iapws95.Iapws95ParameterBlock()
        self.o2_side_prop_params = GenericParameterBlock(
            **get_prop(self.sweep_comp, {"Vap"}, eos=EosType.PR),
            doc="Air property parameters",
        )
        self.h2_side_prop_params = GenericParameterBlock(
            **get_prop(self.feed_comp, {"Vap"}, eos=EosType.PR),
            doc="H2O + H2 gas property parameters",
        )
        self.h2_condensing_prop_params = GenericParameterBlock(
            **get_prop(self.feed_comp, {"Liq", "Vap"}, eos=EosType.PR),
            doc="H2O + H2 gas property parameters",
        )
        self.h2_condensing_prop_params.H2.config.parameter_data["kappa1"] = 0.0
        self.h2_condensing_prop_params.H2O.config \
            .parameter_data["kappa1"] = -0.0665  # p. 312 of (Sandler, 2006)
        # Use PR-SV for water phase equilibrium
        sqrt = pyo.sqrt

        def omega_func(cobj):
            return (0.378893 + 1.4897153 * cobj.omega - 0.17131848 * cobj.omega ** 2
                    + 0.0196554 * cobj.omega ** 3)

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
            return 2 * (1 + kappa * (1 - sqrt(Tr))) * ((1 - sqrt(Tr)) * dkappa_dT
                                                       - kappa / (2 * sqrt(T * Tc)))

        def d2alpha_dT2_func(T, fw, cobj):
            Tc = cobj.temperature_crit
            Tr = T / Tc
            kappa1 = cobj.config.parameter_data["kappa1"]
            kappa = fw + kappa1 * (1 + sqrt(Tr)) * (0.7 - Tr)

            sqrt_alpha = 1 + kappa * (1 - sqrt(Tr))

            dsqrtalpha_dTr = -fw / (2 * sqrt(Tr)) - 1.7 * kappa1 + 2 * kappa1 * Tr
            d2sqrtalpha_dTr = 2 * kappa1 + fw / (4 * Tr ** 1.5)

            d2alpha_dTr2 = 2 * dsqrtalpha_dTr ** 2 + 2 * sqrt_alpha * d2sqrtalpha_dTr

            return d2alpha_dTr2 / Tc ** 2

        self.h2_condensing_prop_params.PR_func_fw = omega_func
        self.h2_condensing_prop_params.PR_func_alpha = alpha_func
        self.h2_condensing_prop_params.PR_func_dalpha_dT = dalpha_dT_func
        self.h2_condensing_prop_params.PR_func_d2alpha_dT2 = d2alpha_dT2_func

        self.h2_pure_prop_params = GenericParameterBlock(
            **get_prop({"H2"}, {"Vap"}, eos=EosType.PR),
            doc="Pure H2 gas property parameters",
        )
        generic_prop_packages = [self.o2_side_prop_params,
                                 self.h2_side_prop_params,
                                 self.h2_pure_prop_params,
                                 self.h2_condensing_prop_params]
        for pp in generic_prop_packages:
            pp.set_default_scaling("enth_mol_phase", 1e-3, index="Vap")
            pp.set_default_scaling("pressure", 1e-5)
            pp.set_default_scaling("temperature", 1e-2)
            pp.set_default_scaling("flow_mol", 1E-3)
        self.h2_condensing_prop_params.set_default_scaling("enth_mol_phase", 1e-3, index="Liq")
        _mf_scale = {
            "Ar": 100,
            "O2": 10,
            "N2": 10,
            "H2": 10,
            "H2O": 100,
            "CO2": 1000}
        for comp, s in _mf_scale.items():
            self.o2_side_prop_params.set_default_scaling(
                "mole_frac_comp", s, index=comp)
            self.o2_side_prop_params.set_default_scaling(
                "mole_frac_phase_comp", s, index=("Vap", comp)
            )
            self.o2_side_prop_params.set_default_scaling(
                "flow_mol_comp", s*1e-3, index=comp)
            self.o2_side_prop_params.set_default_scaling(
                "flow_mol_phase_comp", s*1e-3, index=("Vap", comp)
            )

        for par in [self.h2_side_prop_params,
                    self.h2_condensing_prop_params]:
            for comp in ["H2", "H2O"]:
                par.set_default_scaling("mole_frac_comp", 10, index=comp)
                par.set_default_scaling("flow_mol_comp", 1e-2, index=comp)
                par.set_default_scaling("mole_frac_phase_comp", 10, index=("Vap", comp))
                par.set_default_scaling("flow_mol_phase_comp", 1e-2, index=("Vap", comp))
            par.set_default_scaling("mole_frac_phase_comp", 1, index=("Liq", "H2O"))
            par.set_default_scaling("flow_mol_phase_comp", 1e-2, index=("Liq", "H2O"))



        self.h2_pure_prop_params.set_default_scaling("mole_frac_comp", 1, index="H2")
        self.h2_pure_prop_params.set_default_scaling("mole_frac_phase_comp", 1, index=("Vap", "H2"))

    def _define_cell_params(self):
        self.soec_module.number_cells.fix(1087915)
        soec = self.soec_module.solid_oxide_cell

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
        soec.fuel_electrode.resistivity_log_preexponential_factor\
            .fix(pyo.log(2.5e-5))
        soec.fuel_electrode.resistivity_thermal_exponent_dividend.fix(0)

        soec.oxygen_electrode.length_x.fix(40e-6)
        soec.oxygen_electrode.porosity.fix(0.30717)
        soec.oxygen_electrode.tortuosity.fix(3.0)
        soec.oxygen_electrode.solid_heat_capacity.fix(142.3)
        soec.oxygen_electrode.solid_density.fix(5300)
        soec.oxygen_electrode.solid_thermal_conductivity.fix(2.0)
        soec.oxygen_electrode.resistivity_log_preexponential_factor\
            .fix(pyo.log(7.8125e-05))
        soec.oxygen_electrode.resistivity_thermal_exponent_dividend.fix(0)

        soec.electrolyte.length_x.fix(10.5e-6)
        soec.electrolyte.heat_capacity.fix(400)
        soec.electrolyte.density.fix(6000)
        soec.electrolyte.thermal_conductivity.fix(2.17)
        soec.electrolyte.resistivity_log_preexponential_factor\
            .fix(-9)
        soec.electrolyte.resistivity_thermal_exponent_dividend.fix(8988)

        soec.fuel_triple_phase_boundary.exchange_current_log_preexponential_factor\
            .fix(22.5)
        soec.fuel_triple_phase_boundary.exchange_current_activation_energy.fix(110.8e3)
        soec.fuel_triple_phase_boundary.activation_potential_alpha1.fix(1 - 0.352184)
        soec.fuel_triple_phase_boundary.activation_potential_alpha2.fix(0.352184)

        soec.fuel_triple_phase_boundary.exchange_current_exponent_comp["H2"].fix(0.5)
        soec.fuel_triple_phase_boundary.exchange_current_exponent_comp["H2O"].fix(0.5)

        soec.oxygen_triple_phase_boundary.exchange_current_log_preexponential_factor\
            .fix(25.5)
        soec.oxygen_triple_phase_boundary.exchange_current_activation_energy.fix(112.1e3)
        soec.oxygen_triple_phase_boundary.activation_potential_alpha1.fix(1 - 0.497231)
        soec.oxygen_triple_phase_boundary.activation_potential_alpha2.fix(0.497231)

        soec.oxygen_triple_phase_boundary.exchange_current_exponent_comp["O2"].fix(0.25)

        # set_indexed_variable_bounds(cell.temperature_z, (923,1027))
        # set_indexed_variable_bounds(cell.fuel_chan.Dtemp,(-100,100))
        # set_indexed_variable_bounds(cell.oxygen_chan.Dtemp,(-100,100))

    def _add_units(self):
        # self.soec = SoecDesign(
        #     doc="Design point SOEC",
        #     default={
        #         "oxygen_side_package": self.o2_side_prop_params,
        #         "hydrogen_side_package": self.h2_side_prop_params,
        #         "reaction_eos": EosType.PR
        #     }
        # )
        zfaces = np.linspace(0, 1, 11).tolist()
        xfaces_electrode = [0.0, 1.0]
        xfaces_electrolyte = [0.0, 1.0]

        air_sweep = True
        # operating_pressure = 2e5

        fuel_comps = ["H2", "H2O"]
        fuel_stoich_dict = {"H2": -0.5, "H2O": 0.5, "Vac": 0.5, "O^2-": -0.5, "e^-": 1.0}
        fuel_inerts = []

        if air_sweep:
            oxygen_comps = ["Ar", "CO2", "H2O", "O2", "N2"]
            oxygen_stoich_dict = {"O2": -0.25, "Vac": -0.5, "O^2-": 0.5, "e^-": -1.0}
            oxygen_inerts = ["Ar", "CO2", "H2O", "N2"]
        else:
            oxygen_comps = ["O2", "H2O"]
            oxygen_stoich_dict = {"O2": -0.25, "Vac": -0.5, "O^2-": 0.5, "e^-": -1.0}
            oxygen_inerts = ["H2O"]

        self.number_cells = pyo.Var(initialize=60e6,
                                    units=pyo.units.dimensionless)

        self.soec_module = SolidOxideModuleSimple(
            solid_oxide_cell_config={
                "has_holdup": False,
                "control_volume_zfaces": zfaces,
                "control_volume_xfaces_fuel_electrode": xfaces_electrode,
                "control_volume_xfaces_oxygen_electrode": xfaces_electrode,
                "control_volume_xfaces_electrolyte": xfaces_electrolyte,
                "fuel_component_list": fuel_comps,
                "fuel_triple_phase_boundary_stoich_dict": fuel_stoich_dict,
                "inert_fuel_species_triple_phase_boundary": fuel_inerts,
                "oxygen_component_list": oxygen_comps,
                "oxygen_triple_phase_boundary_stoich_dict": oxygen_stoich_dict,
                "inert_oxygen_species_triple_phase_boundary": oxygen_inerts,
                "flow_pattern": HeatExchangerFlowPattern.countercurrent,
                "include_temperature_x_thermo": True,
                "include_contact_resistance": False,
            },
            fuel_property_package=self.h2_side_prop_params,
            oxygen_property_package=self.o2_side_prop_params,
        )

        self.sweep_recycle_split = gum.Separator(
            doc="Sweep recycle splitter",
            property_package=self.o2_side_prop_params,
            outlet_list=["out", "recycle"]
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
            momentum_mixing_type=gum.MomentumMixingType.none
        )

        @self.sweep_recycle_mix.Constraint(self.time)
        def pressure_equality_eqn(b, t):
            return b.mixed_state[t].pressure == b.feed_state[t].pressure

        self.feed_recycle_mix = gum.Mixer(
            doc="Feed recycle mixer",
            property_package=self.h2_side_prop_params,
            inlet_list=["feed", "recycle"],
            momentum_mixing_type=gum.MomentumMixingType.none
        )

        @self.feed_recycle_mix.Constraint(self.time)
        def pressure_equality_eqn(b, t):
            return b.mixed_state[t].pressure == b.feed_state[t].pressure

        self.sweep_blower = gum.Compressor(
            doc="Sweep blower",
            property_package=self.o2_side_prop_params
        )

        self.sweep_hot_exchanger = gum.HeatExchanger(
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": self.o2_side_prop_params},
            tube={"property_package": self.o2_side_prop_params},
            # delta_temperature_callback=delta_temperature_lmtd_smooth_callback
        )

        self.sweep_medium_exchanger = gum.HeatExchanger(
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": self.o2_side_prop_params},
            tube={"property_package": self.o2_side_prop_params},
            # delta_temperature_callback=delta_temperature_lmtd_smooth_callback
        )

        self.feed_hot_exchanger = gum.HeatExchanger(
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": self.h2_side_prop_params},
            tube={"property_package": self.steam_prop_params},
            # delta_temperature_callback=delta_temperature_lmtd_smooth_callback
        )

        self.feed_translator = gum.Translator(
            inlet_property_package=self.steam_prop_params,
            outlet_property_package=self.h2_side_prop_params,
            outlet_state_defined=True,
        )
        self.feed_heater = gum.Heater(property_package=self.h2_side_prop_params)
        self.sweep_heater = gum.Heater(property_package=self.o2_side_prop_params)

        self.product_flash01 = gum.Flash(property_package=self.h2_condensing_prop_params)
        # Use vapor-only property package for compressors to prevent spurious liquid terms from popping up
        self.cmp01 = gum.Compressor(property_package=self.h2_side_prop_params)
        # self.product_flash02 = gum.Flash(property_package=self.h2_condensing_prop_params)
        self.cmp02 = gum.Compressor(property_package=self.h2_side_prop_params)
        self.product_flash03 = gum.Flash(property_package=self.h2_condensing_prop_params)
        self.cmp03 = gum.Compressor(property_package=self.h2_side_prop_params)

        self.product_flash04 = gum.Flash(property_package=self.h2_condensing_prop_params)
        self.product_flash05 = gum.Flash(property_package=self.h2_condensing_prop_params)
        self.product_dryer = gum.Translator(
            inlet_property_package=self.h2_condensing_prop_params,
            outlet_property_package=self.h2_pure_prop_params,
            outlet_state_defined=True,
        )
        self.cmp04 = gum.Compressor(
            property_package=self.h2_pure_prop_params,
            thermodynamic_assumption=gum.pressure_changer.ThermodynamicAssumption.isothermal
        )
        self.cmp04.efficiency_isentropic = pyo.Var(self.time, initialize=1, units=pyo.units.dimensionless)

        self.water_preheater = gum.HeatExchanger(
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": self.h2_condensing_prop_params},
            tube={"property_package": self.steam_prop_params},
            # delta_temperature_callback=delta_temperature_lmtd_smooth_callback
        )
        # self.water_preheater = gum.Heater(
        #     default={"property_package":self.steam_prop_params}
        # )
        self.water_valve = hum.HelmValve(property_package=self.steam_prop_params, phase="Liq")
        self.water_valve.Cv.fix()
        self.water_valve.valve_opening.fix()
        self.water_valve.pressure_flow_equation.deactivate()
        self.water_split = hum.HelmSplitter(
                property_package=self.steam_prop_params,
                outlet_list=["outlet1", "outlet2", "outlet3", "outlet4",
                                "outlet5", "outlet6"],
        )
        self.water_evaporator01 = gum.HeatExchanger(
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": self.h2_condensing_prop_params},
            tube={"property_package": self.steam_prop_params},
            # delta_temperature_callback=delta_temperature_lmtd_smooth_callback
        )
        self.water_evaporator02 = gum.HeatExchanger(
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": self.h2_condensing_prop_params},
            tube={"property_package": self.steam_prop_params},
            # delta_temperature_callback=delta_temperature_lmtd_smooth_callback
        )
        self.water_evaporator03 = gum.HeatExchanger(
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": self.h2_condensing_prop_params},
            tube={"property_package": self.steam_prop_params},
            # delta_temperature_callback=delta_temperature_lmtd_smooth_callback
        )
        self.water_evaporator04 = gum.HeatExchanger(
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": self.h2_condensing_prop_params},
            tube={"property_package": self.steam_prop_params},
            # delta_temperature_callback=delta_temperature_lmtd_smooth_callback
        )
        self.water_evaporator05 = gum.HeatExchanger(
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": self.o2_side_prop_params},
            tube={"property_package": self.steam_prop_params},
            # delta_temperature_callback=delta_temperature_lmtd_smooth_callback
        )
        self.heat_pump_hot_terminus = gum.Heater(property_package=self.steam_prop_params)

        self.steam_mix = hum.HelmMixer(
            property_package=self.steam_prop_params,
            inlet_list=["inlet1", "inlet2", "inlet3", "inlet4",
                           "inlet5", "inlet6"],
            momentum_mixing_type=gum.MomentumMixingType.none
        )
        @self.steam_mix.Constraint(self.time)
        def pressure_equality_eqn(b,t):
            return b.mixed_state[t].pressure == b.inlet6.pressure[t]

        self.water_compressor = hum.HelmIsentropicCompressor(property_package=self.steam_prop_params)

        self.heat_pump = UnitModelBlock()
        self.heat_pump.heat_in = pyo.Var(self.time, initialize=0.5e6,
                                         units=pyo.units.W)
        self.heat_pump.heat_out = pyo.Var(self.time, initialize=-1e6,
                                          units=pyo.units.W)
        self.heat_pump.work_mechanical = pyo.Var(self.time, initialize=0.5e6,
                                                 units=pyo.units.W)
        self.heat_pump.coefficient_of_performance = pyo.Var(initialize=2,
                                                            units=pyo.units.dimensionless)

        @self.heat_pump.Constraint(self.time)
        def energy_balance_eqn(b, t):
            return b.heat_in[t] + b.heat_out[t] + b.work_mechanical[t] == 0

        @self.heat_pump.Constraint(self.time)
        def performance_eqn(b, t):
            return -b.heat_out[t] == (b.work_mechanical[t]
                                      * b.coefficient_of_performance)

        # Some outside source of water from which the heat pump can harvest heat
        self.heat_source = gum.Heater(property_package=self.steam_prop_params)

    def _add_arcs(self):
        self.ostrm01 = Arc(
            doc="SOEC sweep gas out to recycle splitter",
            source=self.soec_module.oxygen_outlet,
            destination=self.sweep_recycle_split.inlet,
        )
        self.hstrm01 = Arc(
            doc="SOEC hydrogen stream out to recycle splitter",
            source=self.soec_module.fuel_outlet,
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
        self.sweep04 = Arc(
            doc="Sweep mixer to sweep heater",
            source=self.sweep_recycle_mix.outlet,
            destination=self.sweep_heater.inlet,
        )
        self.feed03 = Arc(
            doc="Feed mixer to feed heater",
            source=self.feed_recycle_mix.outlet,
            destination=self.feed_heater.inlet,
        )
        self.sweep05 = Arc(
            doc="Sweep heater to SOEC",
            source=self.sweep_heater.outlet,
            destination=self.soec_module.oxygen_inlet,
        )
        self.feed04 = Arc(
            doc="Feed heater to SOEC",
            source=self.feed_heater.outlet,
            destination=self.soec_module.fuel_inlet,
        )
        self.ostrm03 = Arc(
            doc="Sweep to heat recovery hx",
            source=self.sweep_recycle_split.out,
            destination=self.sweep_hot_exchanger.shell_inlet,
        )
        # self.ostrm04 = Arc(
        #     doc="Sweep to medium temp heat recovery hx",
        #     source=self.sweep_hot_exchanger.shell_outlet,
        #     destination=self.feed_medium_exchanger.shell_inlet,
        # )
        self.ostrm04 = Arc(
            doc="Sweep to medium temp heat recovery hx",
            source=self.sweep_hot_exchanger.shell_outlet,
            destination=self.water_evaporator05.shell_inlet,
        )
        self.ostrm06 = Arc(
            doc="Evaporator to air preheater",
            source=self.water_evaporator05.shell_outlet,
            destination=self.sweep_medium_exchanger.shell_inlet,
        )

        self.sweep01 = Arc(
            doc="Sweep blower to heat recovery hx",
            source=self.sweep_blower.outlet,
            destination=self.sweep_medium_exchanger.tube_inlet,
        )
        self.sweep02 = Arc(
            doc="Sweep blower to heat recovery hx",
            source=self.sweep_medium_exchanger.tube_outlet,
            destination=self.sweep_hot_exchanger.tube_inlet,
        )
        self.sweep03 = Arc(
            doc="",
            source=self.sweep_hot_exchanger.tube_outlet,
            destination=self.sweep_recycle_mix.feed
        )
        self.hstrm03 = Arc(
            doc="",
            source=self.feed_recycle_split.out,
            destination=self.feed_hot_exchanger.shell_inlet,
        )
        self.hstrm04 = Arc(
            doc="",
            source=self.feed_hot_exchanger.shell_outlet,
            destination=self.water_evaporator01.shell_inlet,
        )
        self.hstrm05 = Arc(
            doc="",
            source=self.water_evaporator01.shell_outlet,
            destination=self.water_preheater.shell_inlet,
        )
        self.hstrm06 = Arc(
            doc="",
            source=self.water_preheater.shell_outlet,
            destination=self.product_flash01.inlet,
        )
        self.hstrm07 = Arc(
            doc="",
            source=self.product_flash01.vap_outlet,
            destination=self.cmp01.inlet,
        )
        self.hstrm08 = Arc(
            doc="",
            source=self.cmp01.outlet,
            destination=self.water_evaporator02.shell_inlet,
        )
        self.hstrm09 = Arc(
            doc="",
            source=self.water_evaporator02.shell_outlet,
            # destination=self.product_flash02.inlet,
            destination=self.cmp02.inlet,
        )
        # self.hstrm10 = Arc(
        #     doc="",
        #     source=self.product_flash02.vap_outlet,
        #     destination=self.cmp02.inlet,
        # )
        self.hstrm11 = Arc(
            doc="",
            source=self.cmp02.outlet,
            destination=self.water_evaporator03.shell_inlet,
        )
        self.hstrm12 = Arc(
            doc="",
            source=self.water_evaporator03.shell_outlet,
            destination=self.product_flash03.inlet,
            # destination=self.cmp03.inlet,
        )
        self.hstrm13 = Arc(
            doc="",
            source=self.product_flash03.vap_outlet,
            destination=self.cmp03.inlet,
        )
        self.hstrm14 = Arc(
            doc="",
            source=self.cmp03.outlet,
            destination=self.water_evaporator04.shell_inlet,
        )
        self.hstrm15 = Arc(
            doc="",
            source=self.water_evaporator04.shell_outlet,
            destination=self.product_flash04.inlet,
        )
        self.hstrm16 = Arc(
            doc="",
            source=self.product_flash04.vap_outlet,
            destination=self.product_flash05.inlet,
        )
        self.hstrm17 = Arc(
            doc="",
            source=self.product_flash05.vap_outlet,
            destination=self.product_dryer.inlet,
        )
        self.hstrm18 = Arc(
            doc="",
            source=self.product_dryer.outlet,
            destination=self.cmp04.inlet,
        )
        self.feed02a = Arc(
            doc="",
            source=self.feed_hot_exchanger.tube_outlet,
            destination=self.feed_translator.inlet,
        )
        self.feed02b = Arc(
            doc="",
            source=self.feed_translator.outlet,
            destination=self.feed_recycle_mix.feed,
        )
        self.water01 = Arc(
            doc="Water preheater to valve",
            source=self.water_preheater.tube_outlet,
            destination=self.water_valve.inlet,
        )
        self.water02 = Arc(
            doc="Water valve to water splitter",
            source=self.water_valve.outlet,
            destination=self.water_split.inlet,
        )
        for i, l in zip(range(1, 6), 'abcde'):
            src = getattr(self.water_split, f"outlet{i}")
            evap = getattr(self, f"water_evaporator0{i}")
            setattr(self, f"water03{l}",
                    Arc(source=src, destination=evap.tube_inlet))
        self.water03f = Arc(
            source=self.water_split.outlet6,
            destination=self.heat_pump_hot_terminus.inlet
        )
        for i, l in zip(range(1, 6), 'abcde'):
            evap = getattr(self, f"water_evaporator0{i}")
            dest = getattr(self.steam_mix, f"inlet{i}")
            setattr(self, f"water04{l}",
                    Arc(source=evap.tube_outlet, destination=dest))
        self.water04f = Arc(
            source=self.heat_pump_hot_terminus.outlet,
            destination=self.steam_mix.inlet6
        )
        self.water05 = Arc(
            source=self.steam_mix.outlet,
            destination=self.water_compressor.inlet
        )
        self.feed01 = Arc(
            source=self.water_compressor.outlet,
            destination=self.feed_hot_exchanger.tube_inlet
        )
        pyo.TransformationFactory("network.expand_arcs").apply_to(self)

    def _add_constraints(self):

        set_indexed_variable_bounds(self.water_split.split_fraction, (0, 1))

        # Translator equations
        def rule_flow_mol(blk, t):
            return blk.properties_in[t].flow_mol == blk.properties_out[t].flow_mol

        def rule_flow_mol_scale_down(blk, t):
            return (blk.properties_in[t].flow_mol
                    == self.number_cells * blk.properties_out[t].flow_mol)

        def rule_flow_mol_scale_up(blk, t):
            return (self.number_cells * blk.properties_in[t].flow_mol
                    == blk.properties_out[t].flow_mol)

        def rule_mole_frac(blk, t, j):
            return blk.properties_in[t].mole_frac_comp[j] == blk.properties_out[t].mole_frac_comp[j]

        def rule_temperature(blk, t):
            return blk.properties_in[t].temperature == blk.properties_out[t].temperature

        def rule_pressure(blk, t):
            return blk.properties_in[t].pressure == blk.properties_out[t].pressure


        self.product_dryer.temperature_eqn = pyo.Constraint(self.time,
                                                            rule=rule_temperature)
        self.product_dryer.pressure_eqn = pyo.Constraint(self.time,
                                                         rule=rule_pressure)

        @self.product_dryer.Constraint(self.time)
        def flow_mol_eqn(b, t):
            return b.properties_in[t].flow_mol_comp["H2"] == b.properties_out[t].flow_mol

        @self.product_dryer.Constraint(self.time)
        def mole_frac_comp_eqn(b, t):
            return 1 == b.properties_out[t].mole_frac_comp["H2"]

        self.feed_translator.temperature_eqn = pyo.Constraint(self.time,
                                                              rule=rule_temperature)
        self.feed_translator.pressure_eqn = pyo.Constraint(self.time,
                                                           rule=rule_pressure)

        self.feed_translator.flow_mol_eqn = pyo.Constraint(self.time,
                                                           rule=rule_flow_mol)

        @self.feed_translator.Constraint(self.time)
        def mole_frac_comp_H2_eqn(b, t):
            return b.properties_out[t].mole_frac_comp["H2"] == 1e-19

        @self.feed_translator.Constraint(self.time)
        def mole_frac_comp_H2O_eqn(b, t):
            return b.properties_out[t].mole_frac_comp["H2O"] == 1 - 1e-19

        self.h2_mass_production = pyo.Var(self.time, initialize=2,
                                          units=pyo.units.kg / pyo.units.s)

        @self.Constraint(self.time)
        def h2_mass_production_eqn(b, t):
            return (
                    b.h2_mass_production[t]
                    == 0.002016 * (pyo.units.kg / pyo.units.mol) *
                    b.feed_recycle_split.out_state[t].flow_mol *
                    b.feed_recycle_split.out_state[t].mole_frac_comp["H2"]
            )

        self.soec_single_pass_water_conversion = pyo.Var(self.time, initialize=0.7)

        @self.Constraint(self.time)
        def soec_single_pass_water_conversion_eqn(b, t):
            return b.soec_single_pass_water_conversion[t] == (
                    (b.soec_module.solid_oxide_cell.fuel_channel.flow_mol_comp_outlet[t, "H2"]
                     - b.soec_module.solid_oxide_cell.fuel_channel.flow_mol_comp_inlet[t, "H2"])
                    / b.soec_module.solid_oxide_cell.fuel_channel.flow_mol_comp_inlet[t, "H2O"])

        self.soec_overall_water_conversion = pyo.Var(self.time, initialize=0.75)

        @self.Constraint(self.time)
        def soec_overall_water_conversion_eqn(b, t):
            return (b.soec_overall_water_conversion[t] ==
                    1 - b.feed_recycle_split.inlet.mole_frac_comp[t, "H2O"])


        @self.Expression(self.time)
        def soec_power_per_h2(b, t):
            return b.soec_module.electrical_work[t] / b.h2_mass_production[t]

        def rule_sat_vapor(b, t):
            return (b.properties_out[t].enth_mol
                    == b.properties_out[t].enth_mol_sat_phase["Vap"] + 30)

        self.heat_pump_hot_terminus.control_volume.sat_vapor_eqn =  pyo.Constraint(self.time, rule=rule_sat_vapor)

        for hx in [self.water_evaporator01,
                   self.water_evaporator02,
                   self.water_evaporator03,
                   self.water_evaporator04,
                   self.water_evaporator05,
                   ]:
            hx.tube.sat_vapor_eqn = pyo.Constraint(self.time, rule=rule_sat_vapor)

        self.phase_change_eps = pyo.Param(default=0.1, mutable=True,
                                          units=pyo.units.K)

        def rule_dT_in(b, t):
            return (
                    b.delta_temperature_in[t]
                    == b.hot_side.properties_in[t].temperature
                    # - smooth_max(b.cold_side.properties_out[t].temperature,
                    #              b.cold_side.properties_out[t].temperature_sat,
                    #              eps = self.phase_change_eps)
                    - b.cold_side.properties_out[t].temperature_sat
            )

        def rule_dT_out(b, t):
            return (
                    b.delta_temperature_out[t]
                    == b.hot_side.properties_out[t].temperature
                    # - smooth_max(b.cold_side.properties_in[t].temperature,
                    #              b.cold_side.properties_in[t].temperature_sat,
                    #              eps = self.phase_change_eps)
                    - b.cold_side.properties_in[t].temperature_sat
            )

        # Evaporation via heat exchange with a hot gas
        for hx in [self.water_evaporator01, self.water_evaporator02, self.water_evaporator05]:
            hx.del_component("delta_temperature_in_equation")
            hx.del_component("delta_temperature_out_equation")
            hx.delta_temperature_in_equation = pyo.Constraint(self.time,
                                                              rule=rule_dT_in)
            hx.delta_temperature_out_equation = pyo.Constraint(self.time,
                                                               rule=rule_dT_out)
        # Evaporation via heat exchange with condensing water in H2 stream
        for hx in [self.water_evaporator03, self.water_evaporator04]:
            hx.del_component("delta_temperature_in_equation")
            hx.del_component("delta_temperature_out_equation")

            @hx.Constraint(self.time)
            def delta_temperature_in_equation(b, t):
                eps = self.phase_change_eps
                try:
                    tdew_in = hx.hot_side.properties_in[t].temperature_dew[("Liq", "Vap")]
                    # eps = hx.hot_side.properties_in[t].eps_2_Liq_Vap
                except KeyError:
                    tdew_in = hx.hot_side.properties_in[t].temperature_dew[("Vap", "Liq")]
                    # eps = hx.hot_side.properties_in[t].eps_2_Vap_Liq
                return (
                        b.delta_temperature_in[t]
                        == smooth_min(b.hot_side.properties_in[t].temperature,
                                      tdew_in, eps=eps)
                        # - smooth_max(b.cold_side.properties_out[t].temperature,
                        #              b.cold_side.properties_out[t].temperature_sat,
                        #              eps=eps)
                        - b.cold_side.properties_out[t].temperature
                )

            @hx.Constraint(self.time)
            def delta_temperature_out_equation(b, t):
                eps = self.phase_change_eps
                try:
                    tdew_out = hx.hot_side.properties_out[t].temperature_dew[("Liq", "Vap")]
                    # eps = hx.hot_side.properties_out[t].eps_2_Liq_Vap
                except KeyError:
                    tdew_out = hx.hot_side.properties_out[t].temperature_dew[("Vap", "Liq")]
                    # eps = hx.hot_side.properties_out[t].eps_2_Vap_Liq
                return (
                        b.delta_temperature_out[t]
                        == smooth_min(b.hot_side.properties_out[t].temperature,
                                      tdew_out, eps=eps)
                        # - smooth_max(b.cold_side.properties_in[t].temperature,
                        #              b.cold_side.properties_in[t].temperature_sat,
                        #              eps=eps)
                        - b.cold_side.properties_in[t].temperature_sat
                )

        self.water_preheater.del_component("delta_temperature_in_equation")
        self.water_preheater.del_component("delta_temperature_out_equation")

        @self.water_preheater.Constraint(self.time)
        def delta_temperature_in_equation(b, t):
                eps = self.phase_change_eps
                try:
                    tdew_in = b.hot_side.properties_in[t].temperature_dew[("Liq", "Vap")]
                except KeyError:
                    tdew_in = b.hot_side.properties_in[t].temperature_dew[("Vap", "Liq")]
                return (
                        b.delta_temperature_in[t]
                        == smooth_min(b.hot_side.properties_in[t].temperature,
                                      tdew_in, eps=eps)
                        - b.cold_side.properties_out[t].temperature
                )

        @self.water_preheater.Constraint(self.time)
        def delta_temperature_out_equation(b, t):
            eps = self.phase_change_eps
            try:
                tdew_out = b.hot_side.properties_out[t].temperature_dew[("Liq", "Vap")]
            except KeyError:
                tdew_out = b.hot_side.properties_out[t].temperature_dew[("Vap", "Liq")]
            return (
                    b.delta_temperature_out[t]
                    == smooth_min(b.hot_side.properties_out[t].temperature,
                                  tdew_out, eps=eps)
                    - b.cold_side.properties_in[t].temperature
            )

        @self.Constraint(self.time)
        def heat_pump_evaporator_eqn(b, t):
            return 0 == (b.heat_pump_hot_terminus.heat_duty[t]
                         + b.heat_pump.heat_out[t])

        self.cmp04.del_component(self.cmp04.work_mechanical)

        self.cmp04.work_mechanical = pyo.Var(self.time, units=pyo.units.W, initialize=1e6, bounds=(0, None))
        @self.cmp04.Constraint(self.time)
        def work_mechanical_eqn(b, t):
            return b.work_mechanical[t] == (b.outlet.flow_mol[t] *
                    (b.control_volume.properties_out[t].gibbs_mol - b.control_volume.properties_in[t].gibbs_mol)
                    / b.efficiency_isentropic[t])

        @self.cmp04.Expression(self.time)
        def heat_duty(b, t):
            return ((b.control_volume.properties_out[t].entr_mol
                     - b.control_volume.properties_in[t].entr_mol)
                    * b.outlet.temperature[t] * b.outlet.flow_mol[t]
                    - (1 - b.efficiency_isentropic[t]) * b.work_mechanical[t])

        @self.Constraint(self.time)
        def heat_pump_refrigeration_eqn(b, t):
            return 0 == (b.heat_pump.heat_in[t] + b.heat_source.heat_duty[t]
                         + b.product_flash05.heat_duty[t] + b.cmp04.heat_duty[t])

        @self.Expression(self.time)
        def total_compressor_power(b, t):
            return (
                    b.cmp01.work_mechanical[t] +
                    b.cmp02.work_mechanical[t] +
                    b.cmp03.work_mechanical[t] +
                    b.cmp04.work_mechanical[t]
            )

        @self.Expression(self.time)
        def total_electric_power(b, t):
            return (
                    b.soec_module.electrical_work[t] +
                    # b.sweep_turbine.control_volume.work[t] +
                    # b.sweep_compressor.control_volume.work[t] +
                    b.sweep_blower.control_volume.work[t] +
                    b.sweep_heater.control_volume.heat[t] +
                    b.feed_heater.control_volume.heat[t] +
                    # b.water_pump.control_volume.work[t] +
                    b.water_compressor.control_volume.work[t] +
                    b.heat_pump.work_mechanical[t] +
                    b.total_compressor_power[t]
            )

        @self.Expression(self.time)
        def total_electric_power_per_h2(b, t):
            return b.total_electric_power[t] / b.h2_mass_production[t]

        # self.assumed_cell_area = pyo.Var(initialize=0.0550, units=pyo.units.m**2)
        # self.assumed_current_density = pyo.Var(
        #     initialize=5000, units=pyo.units.ampere/pyo.units.m**2)
        # @self.Expression(self.time)
        # def estimated_number_of_cells(b, t):
        #     return b.soec.current[t]/b.assumed_current_density/b.assumed_cell_area

    def _scaling(self):
        ssf = iscale.set_scaling_factor
        cst = iscale.constraint_scaling_transform

        def scale_indexed_constraint(con, sf):
            for idx, c in con.items():
                iscale.constraint_scaling_transform(c, sf)

        # for pp in [self.h2_side_prop_params,self.o2_side_prop_params]:
        #     pp.set_default_scaling("mole_frac_comp", 10)
        #     pp.set_default_scaling("mole_frac_phase_comp", 10)
        #     pp.set_default_scaling("phase_frac", 1)
        #     pp.set_default_scaling("flow_mol", 1E-3)
        #     pp.set_default_scaling("flow_mol_comp", 1E-3)
        #     pp.set_default_scaling("flow_mol_phase_comp", 1E-3)
        #     pp.set_default_scaling("temperature", 1E-2)
        #     pp.set_default_scaling("pressure", 1E-5)
        #     pp.set_default_scaling(
        #         "enth_mol_phase", 1e-3, index="Vap")
        for blk in [self.sweep_recycle_mix.feed_state, self.sweep_recycle_mix.recycle_state,
                    self.sweep_recycle_mix.mixed_state, self.feed_recycle_mix.feed_state,
                    self.feed_recycle_mix.recycle_state, self.feed_recycle_mix.mixed_state,
                    self.sweep_blower.control_volume.properties_in, self.sweep_blower.control_volume.properties_out,
                    self.sweep_blower.properties_isentropic]:
            for t in self.time:
                for p in ["Vap"]:
                    iscale.set_scaling_factor(blk[t].enth_mol_phase[p], 1e-4)

        # iscale.set_scaling_factor(self.sweep_turbine.control_volume.work, 1e-6)
        for t in self.time:
            iscale.set_scaling_factor(self.sweep_blower.control_volume.work[t], 1e-6)
            iscale.set_scaling_factor(self.feed_heater.control_volume.heat[t], 1e-6)
            iscale.set_scaling_factor(self.sweep_heater.control_volume.heat[t], 1e-6)

        for heater in [self.heat_pump_hot_terminus]:
            ssf(heater.control_volume.heat, 1e-6)
            for t in self.time:
                for blk in [heater.control_volume.properties_in, heater.control_volume.properties_out]:
                    for p in ["Liq", "Vap"]:
                        ssf(blk[t].enth_mol_phase[p], 1e-4)
                        ssf(blk[t].enth_mol_phase[p], 1e-4)
                if hasattr(heater.control_volume, "sat_vapor_eqn"):
                    cst(heater.control_volume.sat_vapor_eqn[t], 1e-4)


        for hx in [self.feed_hot_exchanger,
                   # self.feed_medium_exchanger,
                   self.sweep_hot_exchanger,
                   self.sweep_medium_exchanger,
                   self.water_preheater,
                   self.water_evaporator01,
                   self.water_evaporator02,
                   self.water_evaporator03,
                   self.water_evaporator04,
                   self.water_evaporator05
                   ]:
            ssf(hx.overall_heat_transfer_coefficient, 1e-2)
            ssf(hx.area, 1e-3)
            for t in self.time:
                if hasattr(hx.tube, "sat_vapor_eqn"):
                    cst(hx.tube.sat_vapor_eqn[t], 1e-4)
                    ssf(hx.delta_temperature_in[t], 1e-2)
                    ssf(hx.delta_temperature_out[t], 1e-2)
                    cst(hx.delta_temperature_in_equation[t], 1e-2)
                    cst(hx.delta_temperature_in_equation[t], 1e-2)
                for side in [hx.shell, hx.tube]:
                    ssf(side.heat[t], 1e-6)
                    for blk in [side.properties_in, side.properties_out]:
                        for p in ["Liq", "Vap"]:
                            try:
                                ssf(blk[t].enth_mol_phase[p], 1e-4)
                            except KeyError:
                                # Some have only vapor phases
                                pass

        for cmp in [self.cmp01, self.cmp02, self.cmp03]:
            for t in self.time:
                ssf(cmp.control_volume.work[t], 1e-6)
                for blk in [cmp.control_volume.properties_in,
                            cmp.control_volume.properties_out,
                            cmp.properties_isentropic]:
                    for p in ["Vap"]:
                        ssf(blk[t].enth_mol_phase[p], 1e-4)
        for t in self.time:
            ssf(self.cmp04.control_volume.properties_in[t].enth_mol_phase["Vap"], 1e-4)
            ssf(self.cmp04.control_volume.properties_out[t].enth_mol_phase["Vap"], 1e-4)

        for cond in [self.product_flash01,
                     # self.product_flash02,
                     self.product_flash03,
                     self.product_flash04,
                     self.product_flash05]:
            for t in self.time:
                ssf(cond.control_volume.heat[t], 1e-6)
                for blk in [cond.control_volume.properties_in, cond.control_volume.properties_out]:
                    for p in ["Liq", "Vap"]:
                        ssf(blk[t].enth_mol_phase[p], 1e-4)

        for blk in [self.feed_translator,
                    self.product_dryer]:
            scale_indexed_constraint(blk.temperature_eqn, 1e-2)
            scale_indexed_constraint(blk.pressure_eqn, 1e-5)
            scale_indexed_constraint(blk.flow_mol_eqn, 1e-3)
        for blk in [self.product_dryer]:
            scale_indexed_constraint(blk.mole_frac_comp_eqn, 10)
            # Scale heat pump
        for t in self.time:
            ssf(self.heat_pump.heat_in[t], 1e-6)
            ssf(self.heat_pump.heat_out[t], 1e-6)
            ssf(self.heat_pump.work_mechanical[t], 1e-6)
            cst(self.heat_pump.energy_balance_eqn[t], 1e-6)
            cst(self.heat_pump.performance_eqn[t], 1e-6)
            cst(self.heat_pump_evaporator_eqn[t], 1e-6)
            cst(self.heat_pump_refrigeration_eqn[t], 1e-6)

            ssf(self.cmp04.work_mechanical[t], 1e-6)
            cst(self.cmp04.work_mechanical_eqn[t], 1e-6)

        for t in self.time:
            iscale.constraint_scaling_transform(
                self.sweep_recycle_mix.pressure_equality_eqn[t], 1e-5)
            iscale.constraint_scaling_transform(
                self.feed_recycle_mix.pressure_equality_eqn[t], 1e-5)
            iscale.constraint_scaling_transform(
                self.steam_mix.pressure_equality_eqn[t], 1e-5)

        ssf(self.soec_module.number_cells, 1e-6)

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
        self.feed_hot_exchanger.tube.properties_in[0].pressure.fix(1.2e5)
        self.feed_hot_exchanger.tube.properties_in[0].flow_mol.fix(3100)
        self.feed_hot_exchanger.tube.properties_in[0].enth_mol.fix(
            iapws95.htpx(T=489.18 * pyo.units.K, P=1.2e5 * pyo.units.Pa))

        self._set_gas_port(
            self.sweep_blower.inlet, F=5653, T=288.15, P=101000, y=self.sweep_comp)
        self._set_gas_port(
            self.feed_recycle_mix.feed, F=3100, T=837.80, P=1.2e5, y=self.feed_comp)
        self._set_gas_port(
            self.feed_recycle_mix.recycle, F=3100, T=962.17, P=1.2e5, y={"H2": 0.8, "H2O": 0.2}, fix=False)
        self._set_gas_port(
            self.sweep_recycle_mix.feed, F=5653, T=887.23, P=1.2e5, y=self.sweep_comp)
        recycle_comp = {
            "O2": 0.35,
            "H2O": (1 - 0.35) / (1 - 0.2074) * 0.0099,
            "CO2": (1 - 0.35) / (1 - 0.2074) * 0.0003,
            "N2": (1 - 0.35) / (1 - 0.2074) * 0.7732,
            "Ar": (1 - 0.35) / (1 - 0.2074) * 0.0092,
        }
        self._set_gas_port(
            self.sweep_recycle_mix.recycle, F=6893, T=983.84, P=1.2e5, y=recycle_comp, fix=False)

        self.soec_module.potential_cell.fix(1.334)
        # Recycle splits
        self.sweep_recycle_split.split_fraction[:, "out"].fix(0.50)
        self.feed_recycle_split.split_fraction[:, "out"].fix(0.50)
        self.sweep_blower.efficiency_isentropic.fix(0.8)
        self.sweep_blower.control_volume.properties_out[:].pressure.fix(1.2e5)
        self.sweep_hot_exchanger.overall_heat_transfer_coefficient.fix(100)
        self.sweep_hot_exchanger.area.fix(5522)
        self.sweep_medium_exchanger.overall_heat_transfer_coefficient.fix(100)
        self.sweep_medium_exchanger.area.fix(8511)
        self.feed_hot_exchanger.overall_heat_transfer_coefficient.fix(100)
        self.feed_hot_exchanger.area.fix(4640)
        self.feed_heater.control_volume.properties_out[:].temperature.fix(929.13)
        self.sweep_heater.control_volume.properties_out[:].temperature.fix(945.41)


        # self.h2_precooler.control_volume.properties_out[:].temperature.fix(300)
        self.cmp01.ratioP.fix(3)
        self.cmp01.efficiency_isentropic.fix(0.85)
        # self.ic01.control_volume.properties_out[:].temperature.fix(300)
        self.cmp02.ratioP.fix(2.5)
        self.cmp02.efficiency_isentropic.fix(0.85)
        # self.ic02.control_volume.properties_out[:].temperature.fix(300)
        self.cmp03.ratioP.fix(2.5)
        self.cmp03.efficiency_isentropic.fix(0.85)

        #self.cmp04.ratioP.fix(9.0)
        # self.cmp04.ratioP.fix(9.0**(1/12))
        self.cmp04.efficiency_isentropic.fix(0.8)
        # self.cmp04.cold_gas_temperature.fix(273.15+15)
        self.cmp04.outlet.pressure.fix(64.79e5)

        self.heat_pump.coefficient_of_performance.fix(3.5)

        self.water_preheater.tube_outlet.enth_mol.fix(
            iapws95.htpx(T=306.3 * pyo.units.K, P=1.2e5 * pyo.units.Pa)
        )
        self.water_preheater.overall_heat_transfer_coefficient.fix(200)

        self.water_evaporator01.overall_heat_transfer_coefficient.fix(100)
        self.water_evaporator05.overall_heat_transfer_coefficient.fix(100)
        self.water_evaporator01.shell_outlet.temperature.fix(349.84)
        self.water_evaporator05.shell_outlet.temperature.fix(349.84)

        self.water_evaporator02.shell_outlet.temperature.fix(349.84)
        self.water_evaporator03.shell_outlet.temperature.fix(349.84)
        self.water_evaporator04.shell_outlet.temperature.fix(349.84)
        self.water_evaporator02.overall_heat_transfer_coefficient.fix(100)
        self.water_evaporator03.overall_heat_transfer_coefficient.fix(200)
        self.water_evaporator04.overall_heat_transfer_coefficient.fix(200)

        self.water_preheater.area.fix(1746)
        self.water_evaporator01.area.fix(2018)
        self.water_evaporator02.area.fix(1632)
        self.water_evaporator03.area.fix(1513)
        self.water_evaporator04.area.fix(5245)
        self.water_evaporator05.area.fix(5267)

        # self.water_preheater.overall_heat_transfer_coefficient.fix(150)
        # self.water_preheater.area.fix(600)

        for t in self.time:
            self.product_flash05.control_volume.properties_out[t] \
                .temperature.fix(273.15 + 15)
        for i in range(1, 6):
            if i == 2: # or i == 3:
                continue
            flash = getattr(self, f"product_flash0{i}")
            flash.deltaP.fix(0)
            flash.heat_duty.fix(0)
        self.product_flash05.heat_duty.unfix()

        # water_inlet = self.water_valve.inlet
        water_inlet = self.water_preheater.tube_inlet

        water_inlet.pressure.fix(1.013e5)
        water_inlet.enth_mol.fix(
            iapws95.htpx(T=(273.15 + 15) * pyo.units.K, P=1.013e5 * pyo.units.Pa))
        water_inlet.flow_mol.fix(3100)

        self.water_valve.outlet.pressure.fix(0.4e5)

        self.water_compressor.control_volume.properties_out[:].pressure.fix(
            1.2e5)
        self.water_compressor.efficiency_isentropic[:].fix(0.75)
        self.heat_source.inlet.pressure.fix(1.013e5)
        self.heat_source.inlet.enth_mol.fix(
            iapws95.htpx(T=(273.15 + 15) * pyo.units.K, P=1.013e5 * pyo.units.Pa))
        for t in self.time:
            self.heat_source.inlet.flow_mol[t].value = 10000
        self.heat_source.outlet.enth_mol.fix(
            iapws95.htpx(T=(273.15 + 5) * pyo.units.K, P=1.013e5 * pyo.units.Pa))
        set_indexed_variable_bounds(self.heat_source.inlet.flow_mol[0], (0, None))

    def initialize_build(
            self,
            outlvl=idaeslog.NOTSET,
            solver="ipopt",
            optarg=None,
            load_from=None,
            save_to="soec_standalone_init.json.gz",
    ):

        if load_from is not None:
            if os.path.exists(load_from):
                # init_log.info_high(f"HRSG load initial from {load_from}")
                # here suffix=False avoids loading scaling factors
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

        self.feed_recycle_mix.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        self.sweep_recycle_mix.initialize(outlvl=outlvl, solver=solver, optarg=optarg)

        propagate_state(self.feed03)
        propagate_state(self.sweep04)
        self.sweep_heater.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        self.feed_heater.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.feed04)
        propagate_state(self.sweep05)

        self.soec_module.initialize(
            outlvl=outlvl,
            current_density_guess=-8000,
            temperature_guess=960,
        )

        propagate_state(self.ostrm01)
        self.sweep_recycle_split.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.ostrm02)
        propagate_state(self.ostrm03)

        propagate_state(self.hstrm01)
        self.feed_recycle_split.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm02)
        propagate_state(self.hstrm03)

        self.sweep_blower.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.sweep01)

        self.sweep_medium_exchanger.tube_outlet.temperature.fix(360.08)
        tube_flags = self.sweep_medium_exchanger.tube.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        safe_solve(self.sweep_medium_exchanger.tube)
        self.sweep_medium_exchanger.tube_outlet.temperature.unfix()
        self.sweep_medium_exchanger.tube.properties_in.release_state(tube_flags)

        propagate_state(self.sweep02)

        self.sweep_hot_exchanger.initialize(duty=(80555059, pyo.units.W))

        propagate_state(self.sweep03)
        propagate_state(self.ostrm04)

        self.feed_hot_exchanger.initialize(outlvl=outlvl, solver=solver, optarg=optarg,
                                           duty=(40310061, pyo.units.W))

        propagate_state(self.feed02a)
        self.feed_translator.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.feed02b)

        shell_flags = self.water_evaporator05.shell.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        safe_solve(self.water_evaporator05.shell)
        self.water_evaporator05.shell.properties_in.release_state(shell_flags)

        propagate_state(self.ostrm06)
        self.sweep_medium_exchanger.initialize(outlvl=outlvl, solver=solver, optarg=optarg,
                                               duty=(8917353, pyo.units.W))
        propagate_state(self.sweep02)

        propagate_state(self.hstrm04)

        self.water_preheater.tube_outlet.enth_mol.fix(
            iapws95.htpx(T=306.30 * pyo.units.K, P=1.2e5 * pyo.units.Pa)
        )
        self.water_evaporator01.shell_outlet.temperature.fix(349.84)
        self.water_evaporator02.shell_outlet.temperature.fix(349.84)
        self.water_evaporator03.shell_outlet.temperature.fix(349.84)
        self.water_evaporator04.shell_outlet.temperature.fix(349.84)
        self.water_evaporator05.shell_outlet.temperature.fix(349.84)

        for hx in [self.water_evaporator01, self.water_evaporator02,
                   self.water_evaporator03, self.water_evaporator04,
                   self.water_evaporator05, self.water_preheater]:
            hx.heat_transfer_equation.deactivate()

        shell_flags = self.water_evaporator01.shell.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        safe_solve(self.water_evaporator01.shell)
        self.water_evaporator01.shell.properties_in.release_state(shell_flags)
        propagate_state(self.hstrm05)

        tube_flags = self.water_preheater.tube.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        safe_solve(self.water_preheater.tube)
        shell_flags = self.water_preheater.shell.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        safe_solve(self.water_preheater)
        self.water_preheater.tube.properties_in.release_state(tube_flags)
        self.water_preheater.shell.properties_in.release_state(shell_flags)
        # self.water_preheater.outlet.enth_mol.unfix()
        propagate_state(self.water01)

        propagate_state(self.hstrm06)
        self.product_flash01.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm07)
        self.cmp01.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm08)

        shell_flags = self.water_evaporator02.shell.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        safe_solve(self.water_evaporator02.shell)
        self.water_evaporator02.shell.properties_in.release_state(shell_flags)

        propagate_state(self.hstrm09)
        # self.product_flash02.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        # propagate_state(self.hstrm10)
        self.cmp02.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm11)

        shell_flags = self.water_evaporator03.shell.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        safe_solve(self.water_evaporator03.shell)
        self.water_evaporator03.shell.properties_in.release_state(shell_flags)

        propagate_state(self.hstrm12)
        self.product_flash03.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm13)
        self.cmp03.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm14)

        shell_flags = self.water_evaporator04.shell.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        safe_solve(self.water_evaporator04.shell)
        self.water_evaporator04.shell.properties_in.release_state(shell_flags)

        propagate_state(self.hstrm15)
        self.product_flash04.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm16)
        self.product_flash05.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm17)
        self.product_dryer.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm18)
        self.cmp04.initialize(outlvl=outlvl, solver=solver, optarg=optarg)

        self.water_valve.inlet.fix()
        safe_solve(self.water_valve)
        self.water_valve.inlet.unfix()
        propagate_state(self.water02)
        self.water_split.split_fraction[:, "outlet1"].fix(0.0890)
        self.water_split.split_fraction[:, "outlet2"].fix(0.1035)
        self.water_split.split_fraction[:, "outlet3"].fix(0.0871)
        self.water_split.split_fraction[:, "outlet4"].fix(0.2735)
        self.water_split.split_fraction[:, "outlet5"].fix(0.2971)

        self.water_split.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        self.water_split.split_fraction.unfix()

        for i, l in zip(range(1, 6), 'abcde'):
            arc_in = getattr(self, f"water03{l}")
            propagate_state(arc_in)

            evap = getattr(self, f"water_evaporator0{i}")
            tube_flags = evap.tube.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
            # import pdb; pdb.set_trace()
            safe_solve(evap.tube)
            evap.tube.properties_in.release_state(tube_flags)

            arc_out = getattr(self, f"water04{l}")
            propagate_state(arc_out)

        propagate_state(self.water03f)
        self.heat_pump_hot_terminus.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        self.heat_pump_hot_terminus.inlet.fix()
        safe_solve(self.heat_pump_hot_terminus)
        self.heat_pump_hot_terminus.inlet.unfix()
        propagate_state(self.water04f)

        self.steam_mix.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.water05)
        self.water_compressor.initialize(outlvl=outlvl, solver=solver, optarg=optarg)

        self.feed_recycle_mix.feed.unfix()
        self.feed_recycle_mix.recycle.unfix()
        self.sweep_recycle_mix.feed.unfix()
        self.sweep_recycle_mix.recycle.unfix()

        self.heat_source.inlet.flow_mol.fix(10)
        self.heat_source.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        safe_solve(self.heat_source)
        self.heat_source.inlet.flow_mol.unfix()

        for hx in [self.water_evaporator01, self.water_evaporator02,
                   self.water_evaporator03, self.water_evaporator04,
                   self.water_evaporator05, ]:
            hx.heat_transfer_equation.activate()
            hx.shell_outlet.temperature.unfix()
        self.water_preheater.heat_transfer_equation.activate()
        self.water_preheater.tube_outlet.enth_mol.unfix()

        self.feed01_expanded.deactivate()
        safe_solve(self)

        self.feed_hot_exchanger.tube_inlet.unfix()
        self.feed01_expanded.activate()
        safe_solve(self)

        if save_to is not None:
            iutil.to_json(self, fname=save_to)


    def _add_tags(self):
        tag_group = iutil.ModelTagGroup()
        self.tags_streams = tag_group
        stream_states = tables.stream_states_dict(
            tables.arcs_to_stream_dict(
                self,
                descend_into=False,
                additional={  # streams that are half in HRSG, and may not have arcs
                    "sweep00": self.sweep_blower.inlet,
                    #     "feed04": self.feed_hx02.tube_inlet,
                    #     "hstrm05": self.water_economizer_product.shell_outlet,
                    "ostrm07": self.sweep_medium_exchanger.shell_outlet,
                    "water00": self.water_preheater.tube_inlet,
                    #     "water04": self.water_superheater_product.tube_outlet,
                    #     "water05": self.water_superheater_sweep.tube_outlet,
                    "hstrm19": self.cmp04.outlet,
                },
            )
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
                display_units=pyo.units.m ** 3 / pyo.units.s,
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
            expr=self.soec_module.potential_cell[0],
            format_string="{:.3f}",
            display_units=pyo.units.volts,
        )
        tag_group["soec_current"] = iutil.ModelTag(
            doc="SOEC electrical current",
            expr=self.soec_module.number_cells * sum(self.soec_module.solid_oxide_cell.current_density[0, iz]
                                         * self.soec_module.solid_oxide_cell.fuel_electrode.xface_area[iz]
                                         for iz in self.soec_module.solid_oxide_cell.iznodes),
            format_string="{:.3f}",
            display_units=pyo.units.MA,
        )
        tag_group["soec_power"] = iutil.ModelTag(
            doc="SOEC electric power",
            expr=self.soec_module.electrical_work[0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["sweep_blower_power"] = iutil.ModelTag(
            doc="Sweep blower power",
            expr=self.sweep_blower.control_volume.work[0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["heat_pump_water_draw"] = iutil.ModelTag(
            doc="Heat pump water draw",
            expr=self.heat_source.inlet.flow_mol[0] * 0.01802 * pyo.units.kg/pyo.units.mol,
            format_string="{:.3f}",
            display_units=pyo.units.kg / pyo.units.s,
        )
        tag_group["h2_mass_production"] = iutil.ModelTag(
            doc="H2 mass production rate",
            expr=self.h2_mass_production[0],
            format_string="{:.3f}",
            display_units=pyo.units.kg / pyo.units.s,
        )
        tag_group["soec_power_per_h2"] = iutil.ModelTag(
            doc="H2 mass production rate",
            expr=self.soec_power_per_h2[0],
            format_string="{:.3f}",
            display_units=pyo.units.MJ / pyo.units.kg,
        )
        tag_group["feed_heater_power"] = iutil.ModelTag(
            doc="Feed heater power",
            expr=self.feed_heater.control_volume.heat[0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["sweep_heater_power"] = iutil.ModelTag(
            doc="Sweep heater power",
            expr=self.sweep_heater.control_volume.heat[0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["total_electric_power"] = iutil.ModelTag(
            doc="Total electric power for SOEC and auxilaries",
            expr=self.total_electric_power[0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["total_electric_power_per_h2"] = iutil.ModelTag(
            doc="Total electric power for SOEC and auxilaries per H2 produced",
            expr=self.total_electric_power_per_h2[0],
            format_string="{:.3f}",
            display_units=pyo.units.MJ / pyo.units.kg,
        )
        tag_group["heat_pump_power"] = iutil.ModelTag(
            doc="Heat pump power",
            expr=self.heat_pump.work_mechanical[0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["total_compressor_power"] = iutil.ModelTag(
            doc="Total H2 compressor power",
            expr=self.total_compressor_power[0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["number_of_cells"] = iutil.ModelTag(
            doc="Number of cells",
            expr=self.soec_module.number_cells,
            format_string="{:.4e}",
            display_units="cells",
        )

        tag_group = iutil.ModelTagGroup()
        self.tags_input = tag_group
        tag_group["water_utilization"] = iutil.ModelTag(
            doc="Single pass water conversion",
            expr=self.soec_single_pass_water_conversion[0] * 100,
            format_string="{:.1f}",
            display_units="%",
        )

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
        infilename = os.path.join(this_file_dir(), "soec_standalone_template.svg")
        with open(infilename, "r") as f:
            s = svg_tag(svg=f, tag_group=self.tags_streams, outfile=None)
        s = svg_tag(svg=s, tag_group=self.tags_output, outfile=None)
        s = svg_tag(svg=s, tag_group=self.tags_input, outfile=fname)
        if fname is None:
            return s

    def _make_temperature_gradient_terms(self):
        soec = self.soec_module.solid_oxide_cell
        dz = soec.zfaces[2] - soec.zfaces[1]
        # Going to assume that the zfaces are evenly spaced
        for iz in soec.iznodes:
            assert abs(soec.zfaces[iz + 1] - soec.zfaces[iz] - dz) < 1e-8
        dz = dz * soec.length_z
        def finite_difference(expr, t, ix, iz):
            # Since this is mostly for reference, no need to worry about upwinding or whatever
            if iz == soec.iznodes.first():
                if ix is None:
                    return (-1.5 * expr[t, iz] + 2 * expr[t, iz + 1] - 0.5 * expr[t, iz + 2]) / dz
                else:
                    return (-1.5 * expr[t, ix, iz] + 2 * expr[t, ix, iz + 1] - 0.5 * expr[t, ix, iz + 2]) / dz
            elif iz == soec.iznodes.last():
                if ix is None:
                    return (1.5 * expr[t, iz] - 2 * expr[t, iz - 1] + 0.5 * expr[t, iz - 2]) / dz
                else:
                    return (1.5 * expr[t, ix, iz] - 2 * expr[t, ix, iz - 1] + 0.5 * expr[t, ix, iz - 2]) / dz
            else:
                if ix is None:
                    return (0.5 * expr[t, iz + 1] - 0.5 * expr[t, iz - 1]) / dz
                else:
                    return (0.5 * expr[t, ix, iz + 1] - 0.5 * expr[t, ix, iz - 1]) / dz

        soec.dtemperature_z_dz = pyo.Var(self.time, soec.iznodes, initialize=0, units=pyo.units.K / pyo.units.m)

        @soec.Constraint(self.time, soec.iznodes)
        def dtemperature_z_dz_eqn(b, t, iz):
            return b.dtemperature_z_dz[t, iz] == finite_difference(b.temperature_z, t, None, iz)

        soec.fuel_electrode.dtemperature_dz = pyo.Var(
            self.time,
            soec.fuel_electrode.ixnodes,
            soec.fuel_electrode.iznodes,
            initialize=0,
            units=pyo.units.K / pyo.units.m
        )

        @soec.fuel_electrode.Constraint(self.time, soec.fuel_electrode.ixnodes, soec.fuel_electrode.iznodes)
        def dtemperature_dz_eqn(b, t, ix, iz):
            return b.dtemperature_dz[t, ix, iz] == finite_difference(b.temperature, t, ix, iz)

        vars = [
            soec.dtemperature_z_dz,
            soec.fuel_electrode.dtemperature_dz,
        ]
        cons = [
            soec.dtemperature_z_dz_eqn,
            soec.fuel_electrode.dtemperature_dz_eqn,
        ]
        for var, con in zip(vars, cons):
            for idx, element in var.items():
                iscale.set_scaling_factor(element, 5e-3)
                iscale.constraint_scaling_transform(con[idx], 5e-3)

    def make_performance_constraints(self):
        for hx in [self.water_evaporator01, self.water_evaporator02]:
            try:
                tdew = hx.shell.properties_out[0].temperature_dew["Liq", "Vap"]
            except KeyError:
                tdew = hx.shell.properties_out[0].temperature_dew["Vap", "Liq"]

            @hx.shell.Constraint(self.time)
            def no_condensation_eqn(b, t):
                return b.properties_out[0].temperature >= tdew

            iscale.constraint_scaling_transform(hx.shell.no_condensation_eqn[0], 1e-2)

        for hx in [self.water_evaporator03, self.water_evaporator04, self.water_preheater]:
            for t in self.time:
                try:
                    eps = hx.hot_side.properties_in[t].eps_2_Liq_Vap
                except (KeyError, idaes_except.PropertyNotSupportedError):
                    eps = hx.hot_side.properties_in[t].eps_2_Vap_Liq
                eps.set_value(1e-3)

        delta_T_limit = 75

        # @self.Constraint(self.time)
        # def thermal_gradient_eqn_1(b, t):
        #     return (b.soec_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 1]
        #             - b.soec_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 10]) <= delta_T_limit
        #
        # @self.Constraint(self.time)
        # def thermal_gradient_eqn_2(b, t):
        #     return (b.soec_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 10]
        #             - b.soec_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 1]) <= delta_T_limit
        #
        # @self.Constraint(self.time)
        # def thermal_gradient_eqn_3(b, t):
        #     return (b.soec_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 1]
        #             - b.soec_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 10]) >= -delta_T_limit
        #
        # @self.Constraint(self.time)
        # def thermal_gradient_eqn_4(b, t):
        #     return (b.soec_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 10]
        #             - b.soec_module.solid_oxide_cell.fuel_electrode.temperature[t, 1, 1]) >= -delta_T_limit

        @self.Constraint(self.time)
        def thermal_gradient_eqn_1(b, t):
            return (b.soec_module.fuel_outlet.temperature[t] - b.soec_module.fuel_inlet.temperature[t]) <= delta_T_limit

        @self.Constraint(self.time)
        def thermal_gradient_eqn_2(b, t):
            return (b.soec_module.fuel_outlet.temperature[t] - b.soec_module.fuel_inlet.temperature[t]) >= -delta_T_limit

        @self.Constraint(self.time)
        def thermal_gradient_eqn_3(b, t):
            return (b.soec_module.oxygen_outlet.temperature[t] - b.soec_module.oxygen_inlet.temperature[t]) <= delta_T_limit

        @self.Constraint(self.time)
        def thermal_gradient_eqn_4(b, t):
            return (b.soec_module.oxygen_outlet.temperature[t] - b.soec_module.oxygen_inlet.temperature[t]) >= -delta_T_limit

        @self.Constraint(self.time)
        def thermal_gradient_eqn_5(b, t):
            return (b.soec_module.fuel_outlet.temperature[t] - b.soec_module.oxygen_inlet.temperature[t]) <= delta_T_limit

        @self.Constraint(self.time)
        def thermal_gradient_eqn_6(b, t):
            return (b.soec_module.fuel_outlet.temperature[t] - b.soec_module.oxygen_inlet.temperature[t]) >= -delta_T_limit

        @self.Constraint(self.time)
        def thermal_gradient_eqn_7(b, t):
            return (b.soec_module.oxygen_outlet.temperature[t] - b.soec_module.fuel_inlet.temperature[t]) <= delta_T_limit

        @self.Constraint(self.time)
        def thermal_gradient_eqn_8(b, t):
            return (b.soec_module.oxygen_outlet.temperature[t] - b.soec_module.fuel_inlet.temperature[t]) >= -delta_T_limit


        for con in [
            self.thermal_gradient_eqn_1,
            self.thermal_gradient_eqn_2,
            self.thermal_gradient_eqn_3,
            self.thermal_gradient_eqn_4,
            self.thermal_gradient_eqn_5,
            self.thermal_gradient_eqn_6,
            self.thermal_gradient_eqn_7,
            self.thermal_gradient_eqn_8

        ]:
            iscale.constraint_scaling_transform(con[0], 1e-2)

        @self.Constraint(self.time)
        def average_current_density_constraint(b, t):
            return self.soec_module.solid_oxide_cell.average_current_density[0] / 1000 >= -8

        @self.Constraint(self.time)
        def sweep_min_concentration_eqn(b, t):
            return b.sweep_recycle_split.inlet.mole_frac_comp[t, "O2"] >= 0.25

        @self.Constraint(self.time)
        def sweep_max_concentration_eqn(b, t):
            return b.sweep_recycle_split.inlet.mole_frac_comp[t, "O2"] <= 0.35

        @self.Constraint(self.time)
        def min_h2_feed_eqn(b, t):
            return b.feed_recycle_mix.outlet.mole_frac_comp[t, "H2"] >= 0.05

        @self.Constraint(self.time)
        def water_utilization(b, t):
            return (b.water_demand[t] - b.water_recycle[t]) <= 10475 * pyo.units.mol / pyo.units.s

        iscale.constraint_scaling_transform(self.water_utilization[0], 1e-4)

if __name__ == "__main__":
    import os
    from scipy.linalg import svd
    from IPython.core.display import SVG
    import pyomo.environ as pyo
    import idaes
    import idaes.logger as idaeslog
    from idaes.core.util.model_statistics import degrees_of_freedom as dof
    import idaes.core.util.exceptions as idaes_except
    from idaes.core.solvers import use_idaes_solver_configuration_defaults
    import idaes.core.util.scaling as iscale
    import soec_standalone_flowsheet
    from soec_flowsheet_costing import (
        get_solo_soec_capital_costing,
        initialize_flowsheet_costing,
        scale_flowsheet_costing,
        get_soec_OM_costing,
        display_soec_costing
    )
    import idaes.core.util.model_statistics as mstat
    from idaes.models.properties import iapws95
    from pyomo.util.check_units import assert_units_consistent
    import idaes.core.util as iutil

    import numpy as np
    import pandas as pd

    from pyomo.core.expr.current import identify_variables
    from pyomo.common.collections import ComponentSet


    def find_active_constraints_containing_variable(var, blk):
        con_set = ComponentSet()
        CUID = pyo.ComponentUID(var)
        for c in blk.component_data_objects(ctype=pyo.Constraint, active=True, descend_into=True):
            for v in identify_variables(c.body):
                if CUID.matches(v):
                    con_set.add(c)
        return con_set


    use_idaes_solver_configuration_defaults()
    idaes.cfg.ipopt.options.nlp_scaling_method = "user-scaling"
    idaes.cfg.ipopt.options.OF_ma57_automatic_scaling = "yes"
    idaes.cfg.ipopt["options"]["linear_solver"] = "ma57"
    idaes.cfg.ipopt["options"]["max_iter"] = 300
    idaes.cfg.ipopt["options"]["halt_on_ampl_error"] = "no"

    m = pyo.ConcreteModel()
    m.fs = soec_standalone_flowsheet.SoecStandaloneFlowsheet(dynamic=False)
    iscale.calculate_scaling_factors(m)

    m.fs.initialize_build(outlvl=idaeslog.INFO_LOW)  # , load_from="soec_standalone_init.json.gz")

    print(dof(m))
    get_solo_soec_capital_costing(m.fs, CE_index_year="2018")
    get_soec_OM_costing(m.fs)
    print(dof(m))
    iscale.calculate_scaling_factors(m)

    solver = pyo.SolverFactory("ipopt")

    initialize_flowsheet_costing(m.fs)
    scale_flowsheet_costing(m.fs)

    m.fs.tags_output["annual_water_cost"] = iutil.ModelTag(
        doc="Annual water cost",
        expr=m.fs.costing.annual_water_cost,
        format_string="{:.2f}",
    )

    solver.solve(m, tee=True, options={"tol": 1e-6, "max_iter": 300, "halt_on_ampl_error": "no"})


    def set_indexed_variable_bounds(var, bounds):
        for idx, subvar in var.items():
            subvar.bounds = bounds


    if True:
        m.fs.obj = pyo.Objective(
            expr=(
                    m.fs.costing.annual_electricity_cost
                    + m.fs.costing.annual_water_cost
                    + m.fs.costing.total_annualized_cost
                    + m.fs.costing.annual_fixed_operations_and_maintenance_cost
                    + m.fs.costing.annual_air_cost
            )
        )

        for hx in [m.fs.feed_hot_exchanger, m.fs.sweep_hot_exchanger, m.fs.sweep_medium_exchanger,
                   m.fs.water_evaporator01, m.fs.water_evaporator02, m.fs.water_evaporator03,
                   m.fs.water_evaporator04, m.fs.water_evaporator05, m.fs.water_preheater]:
            set_indexed_variable_bounds(hx.delta_temperature_in, (0, None))
            set_indexed_variable_bounds(hx.delta_temperature_out, (0, None))
            hx.area.bounds = (400, None)
            hx.area.unfix()

        for cmp in [m.fs.sweep_blower, m.fs.cmp01, m.fs.cmp02, m.fs.cmp03, m.fs.cmp04]:
            set_indexed_variable_bounds(cmp.work_mechanical, (0, None))
        set_indexed_variable_bounds(m.fs.water_compressor.control_volume.work, (0, None))

        m.fs.h2_mass_production.fix(2)
        m.fs.water_preheater.tube_inlet.flow_mol.unfix()
        m.fs.soec_single_pass_water_conversion.unfix()
        m.fs.feed_recycle_split.split_fraction.unfix()
        m.fs.sweep_recycle_split.split_fraction.unfix()
        m.fs.sweep_blower.inlet.flow_mol.unfix()
        # m.fs.sweep_blower.control_volume.properties_out[:].pressure.unfix()
        m.fs.feed_heater.outlet.temperature.unfix()
        m.fs.sweep_heater.outlet.temperature.unfix()

        m.fs.soec_module.potential_cell.unfix()
        m.fs.soec_module.number_cells.unfix()
        m.fs.costing.electricity_price.fix(71.7)

        set_indexed_variable_bounds(m.fs.soec_module.solid_oxide_cell.potential, (1.1, 1.6))
        set_indexed_variable_bounds(m.fs.water_split.split_fraction, (0.03, 0.98))
        set_indexed_variable_bounds(m.fs.feed_heater.heat_duty, (0, None))
        set_indexed_variable_bounds(m.fs.sweep_heater.heat_duty, (0, None))
        set_indexed_variable_bounds(m.fs.heat_pump_hot_terminus.heat_duty, (0, None))
        set_indexed_variable_bounds(m.fs.sweep_blower.inlet.flow_mol, (1000, None))
        m.fs.feed_recycle_split.split_fraction[0, "recycle"].bounds = (0.03, 0.5)
        m.fs.sweep_recycle_split.split_fraction[0, "recycle"].bounds = (0.03, 0.5)
        set_indexed_variable_bounds(m.fs.soec_overall_water_conversion, (0.4, 0.8))
        set_indexed_variable_bounds(m.fs.soec_module.solid_oxide_cell.temperature_z, (550 + 273.15, 750 + 273.15))
        set_indexed_variable_bounds(m.fs.soec_module.solid_oxide_cell.fuel_channel.temperature_inlet,
                                    (600 + 273.15, 750 + 273.15))
        set_indexed_variable_bounds(m.fs.soec_module.solid_oxide_cell.oxygen_channel.temperature_inlet,
                                    (600 + 273.15, 750 + 273.15))
        set_indexed_variable_bounds(m.fs.soec_module.solid_oxide_cell.current_density, (-10400, 5200))
        set_indexed_variable_bounds(m.fs.heat_source.inlet.flow_mol[0], (1, None))

        m.fs.feed_heater.costing.max_heat_duty.set_value(8e6)
        m.fs.sweep_heater.costing.max_heat_duty.set_value(8e6)
        m.fs.heat_pump.costing.max_heat_duty.fix(2e7)
        m.fs.max_raw_water_withdrawal.fix(3000)

        for cmp in [m.fs.cmp01, m.fs.cmp02, m.fs.cmp03, m.fs.cmp04]:
            cmp.ratioP.unfix()
            set_indexed_variable_bounds(cmp.ratioP, (1, 3))
            set_indexed_variable_bounds(cmp.outlet.temperature, (273.15, 250 + 273.15))

        m.fs._make_temperature_gradient_terms()
        set_indexed_variable_bounds(m.fs.soec_module.solid_oxide_cell.fuel_electrode.dtemperature_dz, (-750, 750))
        m.fs.make_performance_constraints()
    #     @m.fs.Constraint(m.fs.time)
    #     def equal_pressures_eqn(b,t):
    #        return b.soec_module.fuel_inlet.pressure[t] == b.soec_module.oxygen_inlet.pressure[t]

    #     iscale.constraint_scaling_transform(m.fs.equal_pressures_eqn[0],1e-5)

    # set_indexed_variable_bounds(m.fs.soec_module.solid_oxide_cell.current_density, (-8000,8000))
    # m.fs.average_current_density_constraint.deactivate()
    m.fs.h2_mass_production.fix(5)
    jac_unscaled, jac_scaled, nlp = iscale.constraint_autoscale_large_jac(m)
    solver.solve(m, tee=True, options={"tol": 3e-8, "max_iter": 500, "halt_on_ampl_error": "yes"})

def check_scaling(blk):
    jac, nlp = iscale.get_jacobian(blk, scaled=True)
    # djac = jac.todense()
    # print("Extreme Jacobian entries:")
    # for i in iscale.extreme_jacobian_entries(jac=jac, nlp=nlp, large=1E3, small=0):
    #     print(f"    {i[0]:.2e}, [{i[1]}, {i[2]}]")
    print("Badly scaled variables:")
    for i in iscale.extreme_jacobian_columns(
            jac=jac, nlp=nlp, large=1E3, small=5E-3):
        print(f"    {i[0]:.2e}, [{i[1]}]")
    print("\n\n" + "Badly scaled constraints:")
    for i in iscale.extreme_jacobian_rows(
            jac=jac, nlp=nlp, large=1E3, small=5E-3):
        print(f"    {i[0]:.2e}, [{i[1]}]")
    print(f"Jacobian Condition Number: {iscale.jacobian_cond(jac=jac):.2e}")

    if not hasattr(blk, "obj"):
        blk.obj = pyo.Objective(expr=0)
    dh = DegeneracyHunter(blk, solver=pyo.SolverFactory('cbc'))
    dh.check_rank_equality_constraints(dense=True)
    variables = nlp.get_pyomo_variables()
    constraints = nlp.get_pyomo_equality_constraints()
    # ds = dh.find_candidate_equations()
    for i in np.where(abs(dh.v[:, -1]) > 0.1)[0]:
        print(str(i) + ": " + variables[i].name)
    for i in np.where(abs(dh.u[:, -1]) > 0.1)[0]:
        print(str(i) + ": " + constraints[i].name)

    return (variables, constraints, jac, dh)
