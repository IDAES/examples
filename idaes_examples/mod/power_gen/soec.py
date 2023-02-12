#################################################################################
# The Institute for the Design of Advanced Energy Systems Integrated Platform
# Framework (IDAES IP) was produced under the DOE Institute for the
# Design of Advanced Energy Systems (IDAES), and is copyright (c) 2018-2022
# by the software owners: The Regents of the University of California, through
# Lawrence Berkeley National Laboratory,  National Technology & Engineering
# Solutions of Sandia, LLC, Carnegie Mellon University, West Virginia University
# Research Corporation, et al.  All rights reserved.
#
# Please see the files COPYRIGHT.md and LICENSE.md for full copyright and
# license information.
#################################################################################
import os
import pandas as pd
from pathlib import Path
import numpy as np

import pyomo.environ as pyo
from pyomo.network import Arc, Port
from pyomo.common.fileutils import this_file_dir

import idaes
from idaes.core import FlowsheetBlockData, declare_process_block_class
from idaes.models.properties.modular_properties.base.generic_property import (
    GenericParameterBlock,
    GenericStateBlockData,
)
import idaes.core.util.scaling as iscale
from idaes.models_extra.power_generation.properties.natural_gas_PR import get_prop, EosType
import idaes.models_extra.power_generation.unit_models.soc_submodels as soc
import idaes.models.unit_models as gum
import idaes.models_extra.power_generation.unit_models.helm as hum
from idaes.models.properties import iapws95
from idaes.core.util.initialization import propagate_state
import idaes.logger as idaeslog
import idaes.core.util as iutil
from idaes.core.solvers import get_solver
import idaes.core.util.tables as tables
from idaes.core.util.tags import svg_tag
import idaes.core.base.costing_base as cost_base


@declare_process_block_class("SoecFlowsheet")
class SoecFlowsheetData(FlowsheetBlockData):
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
        self.h2_pure_prop_params = GenericParameterBlock(
            **get_prop({"H2"}, {"Vap"}, eos=EosType.PR),
            doc="Pure H2 gas property parameters",
        )
        generic_prop_packages = [
            self.o2_side_prop_params,
            self.h2_side_prop_params,
            self.h2_pure_prop_params,
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
                "mole_frac_phase_comp", s, index=comp
            )

        self.h2_side_prop_params.set_default_scaling("mole_frac_comp", 10)
        self.h2_pure_prop_params.set_default_scaling("mole_frac_phase_comp", 10)

        self.h2_pure_prop_params.set_default_scaling("mole_frac_comp", 1)
        self.h2_pure_prop_params.set_default_scaling("mole_frac_phase_comp", 1)

    def _define_cell_params(self):
        self.soec_module.number_cells.fix(1e6)#1.8*4.4e5)

        self.soec_module.solid_oxide_cell.fuel_channel.length_x.fix(0.002)
        self.soec_module.solid_oxide_cell.length_y.fix(0.2345)
        self.soec_module.solid_oxide_cell.length_z.fix(0.2345)
        self.soec_module.solid_oxide_cell.fuel_channel.heat_transfer_coefficient.fix(100)

        self.soec_module.solid_oxide_cell.oxygen_channel.length_x.fix(0.002)
        self.soec_module.solid_oxide_cell.oxygen_channel.heat_transfer_coefficient.fix(100)

        self.soec_module.solid_oxide_cell.fuel_electrode.length_x.fix(1e-3)
        self.soec_module.solid_oxide_cell.fuel_electrode.porosity.fix(0.326)
        self.soec_module.solid_oxide_cell.fuel_electrode.tortuosity.fix(3)  # Revisit
        self.soec_module.solid_oxide_cell.fuel_electrode.solid_heat_capacity.fix(595)
        self.soec_module.solid_oxide_cell.fuel_electrode.solid_density.fix(7740.0)
        self.soec_module.solid_oxide_cell.fuel_electrode.solid_thermal_conductivity.fix(6.23)
        self.soec_module.solid_oxide_cell.fuel_electrode.resistivity_log_preexponential_factor.fix(
            pyo.log(2.5e-5)
        )
        self.soec_module.solid_oxide_cell.fuel_electrode.resistivity_thermal_exponent_dividend.fix(0)

        self.soec_module.solid_oxide_cell.oxygen_electrode.length_x.fix(40e-6)
        self.soec_module.solid_oxide_cell.oxygen_electrode.porosity.fix(0.30717)
        self.soec_module.solid_oxide_cell.oxygen_electrode.tortuosity.fix(3.0)  # Revisit
        # Heat capacity and heat transfer coefficients of oxygen electrode aren't well known but probably don't matter
        # because the electrode is extremely thin
        self.soec_module.solid_oxide_cell.oxygen_electrode.solid_heat_capacity.fix(142.3)
        self.soec_module.solid_oxide_cell.oxygen_electrode.solid_density.fix(5300)
        self.soec_module.solid_oxide_cell.oxygen_electrode.solid_thermal_conductivity.fix(2.0)
        # Also unknown but probably insignificant
        self.soec_module.solid_oxide_cell.oxygen_electrode.resistivity_log_preexponential_factor.fix(
            pyo.log(7.8125e-05)
        )
        self.soec_module.solid_oxide_cell.oxygen_electrode.resistivity_thermal_exponent_dividend.fix(0)

        self.soec_module.solid_oxide_cell.electrolyte.length_x.fix(10.5e-6)
        self.soec_module.solid_oxide_cell.electrolyte.heat_capacity.fix(400)
        self.soec_module.solid_oxide_cell.electrolyte.density.fix(6000)
        self.soec_module.solid_oxide_cell.electrolyte.thermal_conductivity.fix(2.17)
        # Lumping all stack ohmic resistance into electrolyte because isolating it at contacts is hard
        self.soec_module.solid_oxide_cell.electrolyte.resistivity_log_preexponential_factor.fix(-9.001)
        self.soec_module.solid_oxide_cell.electrolyte.resistivity_thermal_exponent_dividend.fix(8988.134)

        self.soec_module.solid_oxide_cell.fuel_triple_phase_boundary.exchange_current_log_preexponential_factor.fix(
            22.5
        )
        self.soec_module.solid_oxide_cell.fuel_triple_phase_boundary.exchange_current_activation_energy.fix(110.802e3)
        self.soec_module.solid_oxide_cell.fuel_triple_phase_boundary.activation_potential_alpha1.fix(0.647816)
        self.soec_module.solid_oxide_cell.fuel_triple_phase_boundary.activation_potential_alpha2.fix(0.352184)

        self.soec_module.solid_oxide_cell.fuel_triple_phase_boundary.exchange_current_exponent_comp["H2"].fix(0.5)
        self.soec_module.solid_oxide_cell.fuel_triple_phase_boundary.exchange_current_exponent_comp["H2O"].fix(0.5)

        self.soec_module.solid_oxide_cell.oxygen_triple_phase_boundary.exchange_current_log_preexponential_factor.fix(
            25.5
        )
        self.soec_module.solid_oxide_cell.oxygen_triple_phase_boundary.exchange_current_activation_energy.fix(112.066e3)
        self.soec_module.solid_oxide_cell.oxygen_triple_phase_boundary.activation_potential_alpha1.fix(0.503)
        self.soec_module.solid_oxide_cell.oxygen_triple_phase_boundary.activation_potential_alpha2.fix(0.497)

        self.soec_module.solid_oxide_cell.oxygen_triple_phase_boundary.exchange_current_exponent_comp["O2"].fix(0.25)

    def _add_units(self):
        zfaces = np.linspace(0, 1, 11).tolist()
        xfaces_electrode = [0.0, 1.0]
        xfaces_electrolyte = [0.0, 1.0]

        air_sweep = True

        fuel_comps = ["H2", "H2O"]
        fuel_stoich_dict = {"H2": -0.5, "H2O": 0.5, "Vac": 0.5, "O^2-": -0.5, "e^-": 1}
        if air_sweep:
            oxygen_comps = ["Ar", "CO2", "H2O", "O2", "N2"]
            oxygen_stoich_dict = {
                "O2": -0.25,
                "Vac": -0.5,
                "O^2-": 0.5,
                "e^-": -1,
            }
        else:
            oxygen_comps = ["O2", "H2O"]
            oxygen_stoich_dict = {
                "O2": -0.25,
                "H2O": 0,
                "Vac": -0.5,
                "O^2-": 0.5,
                "e^-": -1,
            }

        self.soec_module = soc.SolidOxideModuleSimple(
            solid_oxide_cell_config={
                "has_holdup": False,
                "control_volume_zfaces": zfaces,
                "control_volume_xfaces_fuel_electrode": xfaces_electrode,
                "control_volume_xfaces_oxygen_electrode": xfaces_electrode,
                "control_volume_xfaces_electrolyte": xfaces_electrolyte,
                "fuel_component_list": fuel_comps,
                "fuel_triple_phase_boundary_stoich_dict": fuel_stoich_dict,
                "inert_fuel_species_triple_phase_boundary": [],
                "oxygen_component_list": oxygen_comps,
                "oxygen_triple_phase_boundary_stoich_dict": oxygen_stoich_dict,
                "inert_oxygen_species_triple_phase_boundary": ["N2", "Ar", "CO2", "H2O"],
                "include_temperature_x_thermo": True,
                "include_contact_resistance": False,
            },
            fuel_property_package=self.h2_side_prop_params,
            oxygen_property_package=self.o2_side_prop_params,
        )
        self.soec_module.number_cells.fix(60e6)

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

        self.sweep_compressor = gum.Compressor(
            doc="Sweep air compressor",
            property_package=self.o2_side_prop_params,
        )
        self.sweep_hx = gum.HeatExchanger(
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": self.o2_side_prop_params},
            tube={"property_package": self.o2_side_prop_params},
        )
        self.sweep_turbine = gum.Turbine(
            doc="Sweep air turbine",
            property_package=self.o2_side_prop_params,
        )
        self.feed_hx01 = gum.HeatExchanger(
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": self.h2_side_prop_params},
            tube={"property_package": self.steam_prop_params},
        )
        self.feed_translator = gum.Translator(
            inlet_property_package=self.steam_prop_params,
            outlet_property_package=self.h2_side_prop_params,
            outlet_state_defined=False,
        )
        self.feed_heater = gum.Heater(
            property_package=self.h2_side_prop_params
        )
        self.sweep_heater = gum.Heater(
            property_package=self.o2_side_prop_params
        )
        self.water_pump = hum.HelmIsentropicCompressor(
            property_package=self.steam_prop_params
        )
        self.water_split = hum.HelmSplitter(
            property_package=self.steam_prop_params,
            outlet_list=["outlet1", "outlet2"],
        )
        self.water_heater01 = gum.HeatExchanger(
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": self.h2_side_prop_params},
            tube={"property_package": self.steam_prop_params},
        )
        self.water_heater02 = gum.HeatExchanger(
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": self.o2_side_prop_params},
            tube={"property_package": self.steam_prop_params},
        )
        # Magic dryer, just magically drop water out of a port.
        @self.Expression(self.time, {"H2"})
        def waterless_h2_mole_frac_expr(b, t, i):
            return 1

        @self.Expression(self.time)
        def waterless_h2_flow_expr(b, t):
            return (
                b.water_heater01.shell.properties_out[t].flow_mol
                * b.water_heater01.shell.properties_out[t].mole_frac_comp["H2"]
            )

        self.h2_drop_water_port = Port(
            rule=lambda b: {
                "flow_mol": b.waterless_h2_flow_expr,
                "pressure": b.water_heater01._pressure_hot_side_outlet_ref,
                "temperature": b.water_heater01._temperature_hot_side_outlet_ref,
                "mole_frac_comp": b.waterless_h2_mole_frac_expr,
            }
        )
        self.h2_precooler = gum.Heater(
            property_package=self.h2_pure_prop_params
        )
        self.cmp01 = gum.Compressor(
            property_package=self.h2_pure_prop_params
        )
        self.ic01 = gum.Heater(property_package=self.h2_pure_prop_params)
        self.cmp02 = gum.Compressor(
            property_package=self.h2_pure_prop_params
        )
        self.ic02 = gum.Heater(property_package=self.h2_pure_prop_params)
        self.cmp03 = gum.Compressor(
            property_package=self.h2_pure_prop_params
        )
        self.ic03 = gum.Heater(property_package=self.h2_pure_prop_params)
        self.cmp04 = gum.Compressor(
            property_package=self.h2_pure_prop_params
        )
        self.makeup_mix = hum.HelmMixer(
            dynamic=False,
            property_package=self.steam_prop_params,
            momentum_mixing_type=gum.MomentumMixingType.none,
            inlet_list=["w1", "w2"],
        )

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
        self.sweep01 = Arc(
            doc="Sweep mixer to sweep heater",
            source=self.sweep_recycle_mix.outlet,
            destination=self.sweep_heater.inlet,
        )
        self.feed01 = Arc(
            doc="Feed mixer to feed heater",
            source=self.feed_recycle_mix.outlet,
            destination=self.feed_heater.inlet,
        )
        self.sweep01b = Arc(
            doc="Sweep heater to SOEC",
            source=self.sweep_heater.outlet,
            destination=self.soec_module.oxygen_inlet,
        )
        self.feed01b = Arc(
            doc="Feed heater to SOEC",
            source=self.feed_heater.outlet,
            destination=self.soec_module.fuel_inlet,
        )
        self.ostrm03 = Arc(
            doc="Sweep to sweep heat recovery hx",
            source=self.sweep_recycle_split.out,
            destination=self.sweep_hx.shell_inlet,
        )
        self.sweep03 = Arc(
            doc="Sweep compressor heat recovery hx",
            source=self.sweep_compressor.outlet,
            destination=self.sweep_hx.tube_inlet,
        )
        self.sweep02 = Arc(
            doc="Sweep recovery hx to sweep mixer",
            source=self.sweep_hx.tube_outlet,
            destination=self.sweep_recycle_mix.feed,
        )
        self.ostrm04 = Arc(
            doc="Sweep to sweep work recovery turbine",
            source=self.sweep_hx.shell_outlet,
            destination=self.sweep_turbine.inlet,
        )
        self.hstrm03 = Arc(
            doc="",
            source=self.feed_recycle_split.out,
            destination=self.feed_hx01.shell_inlet,
        )
        self.feed02 = Arc(
            doc="",
            source=self.feed_hx01.tube_outlet,
            destination=self.feed_translator.inlet,
        )
        self.feed02b = Arc(
            doc="",
            source=self.feed_translator.outlet,
            destination=self.feed_recycle_mix.feed,
        )
        self.ostrm05 = Arc(
            doc="Sweep turbine to feed hx 2",
            source=self.sweep_turbine.outlet,
            destination=self.water_heater02.shell_inlet,
        )
        self.water01 = Arc(
            doc="Water pump to water splitter",
            source=self.water_pump.outlet,
            destination=self.water_split.inlet,
        )
        self.water02 = Arc(
            doc="Water splitter water heater 1",
            source=self.water_split.outlet1,
            destination=self.water_heater01.tube_inlet,
        )
        self.water03 = Arc(
            doc="Water splitter to water heater 2",
            source=self.water_split.outlet2,
            destination=self.water_heater02.tube_inlet,
        )
        self.water04 = Arc(
            doc="Water from heater 1 to mix",
            source=self.water_heater01.tube_outlet,
            destination=self.makeup_mix.w1,
        )
        self.water05 = Arc(
            doc="Water from heater 2 to mix",
            source=self.water_heater02.tube_outlet,
            destination=self.makeup_mix.w2,
        )
        self.hstrm04 = Arc(
            doc="",
            source=self.feed_hx01.shell_outlet,
            destination=self.water_heater01.shell_inlet,
        )
        self.hstrm06 = Arc(
            doc="",
            source=self.h2_drop_water_port,
            destination=self.h2_precooler.inlet,
        )
        self.hstrm07 = Arc(
            doc="",
            source=self.h2_precooler.outlet,
            destination=self.cmp01.inlet,
        )
        self.hstrm08 = Arc(
            doc="",
            source=self.cmp01.outlet,
            destination=self.ic01.inlet,
        )
        self.hstrm09 = Arc(
            doc="",
            source=self.ic01.outlet,
            destination=self.cmp02.inlet,
        )
        self.hstrm10 = Arc(
            doc="",
            source=self.cmp02.outlet,
            destination=self.ic02.inlet,
        )
        self.hstrm11 = Arc(
            doc="",
            source=self.ic02.outlet,
            destination=self.cmp03.inlet,
        )
        self.hstrm12 = Arc(
            doc="",
            source=self.cmp03.outlet,
            destination=self.ic03.inlet,
        )
        self.hstrm13 = Arc(
            doc="",
            source=self.ic03.outlet,
            destination=self.cmp04.inlet,
        )
        pyo.TransformationFactory("network.expand_arcs").apply_to(self)

    def _add_constraints(self):
        cost_base.register_idaes_currency_units()
        self.water_price = pyo.Var(
            initialize=9.352e-4,
            units=pyo.units.USD_2018 / pyo.units.kg,
            doc="Price of water including treatment chemicals",
        )
        self.water_price.fix()
        self.hydrogen_product_rate = pyo.Var(
            self.config.time,
            initialize=5,
            units=pyo.units.kg / pyo.units.s,
            doc="Hyrogen mass product rate.",
        )

        @self.Constraint(self.config.time)
        def hydrogen_product_rate_eqn(b, t):
            return (
                b.hydrogen_product_rate[t]
                == b.cmp04.control_volume.properties_out[t].flow_mass
            )

        # Translator equations
        @self.makeup_mix.Constraint(self.config.time, doc="Mixed state pressure eqn.")
        def mixer1_pressure_eqn(b, t):
            return b.mixed_state[t].pressure == b.w1_state[t].pressure

        @self.feed_translator.Constraint(self.time)
        def temperature_eqn(b, t):
            return b.properties_out[t].temperature == b.properties_in[t].temperature

        @self.feed_translator.Constraint(self.time)
        def pressure_eqn(b, t):
            return b.properties_out[t].pressure == b.properties_in[t].pressure

        @self.feed_translator.Constraint(self.time)
        def flow_mol_eqn(b, t):
            return b.properties_out[t].flow_mol == b.properties_in[t].flow_mol

        @self.feed_translator.Constraint(self.time)
        def mole_frac_comp_eqn(b, t):
            return b.properties_out[t].mole_frac_comp["H2"] == 1e-19

        self.h2_mass_production = pyo.Var(
            self.time, initialize=2, units=pyo.units.kg / pyo.units.s
        )

        @self.Constraint(self.time)
        def h2_mass_production_eqn(b, t):
            return (
                b.h2_mass_production[t]
                == 0.002016
                * (pyo.units.kg / pyo.units.mol)
                * b.feed_recycle_split.out_state[t].flow_mol
                * b.feed_recycle_split.out_state[t].mole_frac_comp["H2"]
            )

        self.soec_single_pass_water_conversion = pyo.Var(self.time, initialize=0.7)

        @self.Constraint(self.time)
        def soec_single_pass_water_conversion_eqn(b, t):
            return b.soec_single_pass_water_conversion[t] == (
                (
                    b.soec_module.solid_oxide_cell.fuel_channel.flow_mol_comp_outlet[t, "H2"]
                    - b.soec_module.solid_oxide_cell.fuel_channel.flow_mol_comp_inlet[t, "H2"]
                )
                / b.soec_module.solid_oxide_cell.fuel_channel.flow_mol_comp_inlet[t, "H2O"]
            )

        self.soec_overall_water_conversion = pyo.Var(self.time, initialize=0.75)

        @self.Constraint(self.time)
        def soec_overall_water_conversion_eqn(b, t):
            return (
                b.soec_overall_water_conversion[t]
                == 1 - b.feed_recycle_split.inlet.mole_frac_comp[t, "H2O"]
            )

        self.soec_inverter_efficiency = pyo.Var(initialize=0.97)
        self.soec_inverter_efficiency.fix()

        @self.Expression(self.time)
        def soec_ac_power(b, t):
            return b.soec_module.electrical_work[t]/b.soec_inverter_efficiency

        @self.Expression(self.time)
        def soec_power_per_h2(b, t):
            return b.soec_ac_power[t] / b.h2_mass_production[t]

        @self.Expression(self.time)
        def total_compressor_power(b, t):
            return (
                b.cmp01.control_volume.work[t]
                + b.cmp02.control_volume.work[t]
                + b.cmp03.control_volume.work[t]
                + b.cmp04.control_volume.work[t]
            )

        @self.Expression(self.time)
        def total_electric_power(b, t):
            return (
                b.soec_ac_power[t]
                + b.sweep_turbine.control_volume.work[t]
                + b.sweep_compressor.control_volume.work[t]
                + b.sweep_heater.control_volume.heat[t]
                + b.feed_heater.control_volume.heat[t]
                + b.water_pump.control_volume.work[t]
                + b.total_compressor_power[t]
            )

        @self.Expression(self.time)
        def total_electric_power_per_h2(b, t):
            return b.total_electric_power[t] / b.h2_mass_production[t]

        @self.Expression(self.time)
        def makeup_water_flow(b, t):
            return self.water_pump.control_volume.properties_in[0].flow_mass

        @self.Expression(self.time)
        def variable_makeup_water_cost(b, t):
            return b.makeup_water_flow[t] * b.water_price

    def _scaling(self):
        def scale_indexed_constraint(con, sf):
            for idx, c in con.items():
                iscale.constraint_scaling_transform(c, sf)

        iscale.set_scaling_factor(self.waterless_h2_flow_expr[0.0], 1e-3)
        iscale.set_scaling_factor(self.waterless_h2_mole_frac_expr[0.0, "H2"], 1.0)

        iscale.set_scaling_factor(
            self.sweep_recycle_mix.feed_state[0.0].enth_mol_phase["Vap"], 1e-4
        )
        iscale.set_scaling_factor(
            self.sweep_recycle_mix.recycle_state[0.0].enth_mol_phase["Vap"], 1e-4
        )
        iscale.set_scaling_factor(
            self.sweep_recycle_mix.mixed_state[0.0].enth_mol_phase["Vap"], 1e-4
        )
        iscale.set_scaling_factor(
            self.feed_recycle_mix.feed_state[0.0].enth_mol_phase["Vap"], 1e-4
        )
        iscale.set_scaling_factor(
            self.feed_recycle_mix.recycle_state[0.0].enth_mol_phase["Vap"], 1e-4
        )
        iscale.set_scaling_factor(
            self.feed_recycle_mix.mixed_state[0.0].enth_mol_phase["Vap"], 1e-4
        )
        iscale.set_scaling_factor(
            self.sweep_compressor.control_volume.properties_in[0.0].enth_mol_phase[
                "Vap"
            ],
            1e-4,
        )
        iscale.set_scaling_factor(
            self.sweep_compressor.control_volume.properties_out[0.0].enth_mol_phase[
                "Vap"
            ],
            1e-4,
        )
        iscale.set_scaling_factor(self.sweep_compressor.control_volume.work, 1e-6)
        iscale.set_scaling_factor(
            self.sweep_compressor.properties_isentropic[0.0].enth_mol_phase["Vap"], 1e-4
        )
        iscale.set_scaling_factor(
            self.sweep_hx.shell.properties_in[0.0].enth_mol_phase["Vap"], 1e-4
        )
        iscale.set_scaling_factor(
            self.sweep_hx.shell.properties_out[0.0].enth_mol_phase["Vap"], 1e-4
        )
        iscale.set_scaling_factor(self.sweep_hx.shell.heat, 1e-6)
        iscale.set_scaling_factor(
            self.sweep_hx.tube.properties_in[0.0].enth_mol_phase["Vap"], 1e-4
        )
        iscale.set_scaling_factor(
            self.sweep_hx.tube.properties_out[0.0].enth_mol_phase["Vap"], 1e-4
        )
        iscale.set_scaling_factor(self.sweep_hx.tube.heat, 1e-6)
        iscale.set_scaling_factor(
            self.sweep_hx.overall_heat_transfer_coefficient[0.0], 1e-2
        )
        iscale.set_scaling_factor(self.sweep_hx.area, 1e-3)
        iscale.set_scaling_factor(self.feed_hx01.shell.heat, 1e-6)
        iscale.set_scaling_factor(self.feed_hx01.tube.heat, 1e-6)
        iscale.set_scaling_factor(
            self.feed_hx01.overall_heat_transfer_coefficient[0.0], 1e-2
        )
        iscale.set_scaling_factor(self.feed_hx01.area, 1e-3)
        iscale.set_scaling_factor(self.sweep_turbine.control_volume.work, 1e-6)
        iscale.set_scaling_factor(self.feed_heater.control_volume.heat, 1e-6)
        iscale.set_scaling_factor(self.sweep_heater.control_volume.heat, 1e-6)
        iscale.set_scaling_factor(self.water_heater01.shell.heat, 1e-6)
        iscale.set_scaling_factor(self.water_heater01.tube.heat, 1e-6)
        iscale.set_scaling_factor(
            self.water_heater01.overall_heat_transfer_coefficient[0.0], 1e-2
        )
        iscale.set_scaling_factor(self.water_heater01.area, 1e-3)
        iscale.set_scaling_factor(self.water_heater02.shell.heat, 1e-6)
        iscale.set_scaling_factor(self.water_heater02.tube.heat, 1e-6)
        iscale.set_scaling_factor(
            self.water_heater02.overall_heat_transfer_coefficient[0.0], 1e-2
        )
        iscale.set_scaling_factor(self.water_heater02.area, 1e-3)
        iscale.set_scaling_factor(self.water_pump.control_volume.work[0.0], 1e-4)
        iscale.set_scaling_factor(self.h2_precooler.control_volume.heat, 1e-5)
        iscale.set_scaling_factor(self.cmp01.control_volume.work, 1e-6)
        iscale.set_scaling_factor(self.ic01.control_volume.heat, 1e-5)
        iscale.set_scaling_factor(self.cmp02.control_volume.work, 1e-6)
        iscale.set_scaling_factor(self.ic02.control_volume.heat, 1e-5)
        iscale.set_scaling_factor(self.cmp03.control_volume.work, 1e-6)
        iscale.set_scaling_factor(self.ic03.control_volume.heat, 1e-5)
        iscale.set_scaling_factor(self.cmp04.control_volume.work, 1e-6)

        for t in self.time:
            iscale.constraint_scaling_transform(
                self.sweep_recycle_mix.pressure_equality_eqn[t], 1e-5
            )
            iscale.constraint_scaling_transform(
                self.feed_recycle_mix.pressure_equality_eqn[t], 1e-5
            )

            iscale.constraint_scaling_transform(
                self.feed_translator.temperature_eqn[t], 1e-2
            )
            iscale.constraint_scaling_transform(
                self.feed_translator.pressure_eqn[t], 1e-5
            )
            iscale.constraint_scaling_transform(
                self.feed_translator.flow_mol_eqn[t], 1e-3
            )
            iscale.constraint_scaling_transform(
                self.feed_translator.mole_frac_comp_eqn[t], 10
            )
            iscale.constraint_scaling_transform(
                self.feed_translator.mole_frac_comp_eqn[t], 10
            )

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
        self.feed_hx01.tube.properties_in[0].pressure.fix(6e5)
        self.feed_hx01.tube.properties_in[0].flow_mol.fix(3360)
        self.feed_hx01.tube.properties_in[0].enth_mol.fix(
            iapws95.htpx(T=520 * pyo.units.K, P=6e5 * pyo.units.Pa)
        )

        self.water_pump.control_volume.properties_in[0].pressure.fix(101000)
        self.water_pump.control_volume.properties_in[0].flow_mol.fix(3360)
        self.water_pump.control_volume.properties_in[0].enth_mol.fix(
            iapws95.htpx(T=288.15 * pyo.units.K, P=101000 * pyo.units.Pa)
        )

        self._set_gas_port(
            self.sweep_compressor.inlet, F=5000, T=288.15, P=101000, y=self.sweep_comp
        )
        self._set_gas_port(
            self.feed_recycle_mix.feed, F=3500, T=1023, P=6e5, y=self.feed_comp
        )
        self._set_gas_port(
            self.feed_recycle_mix.recycle,
            F=340,
            T=1023,
            P=6e5,
            y={"H2": 0.7, "H2O": 0.3},
            fix=False,
        )
        self._set_gas_port(
            self.sweep_recycle_mix.feed, F=5200, T=1023, P=6e5, y=self.sweep_comp
        )
        self._set_gas_port(
            self.sweep_recycle_mix.recycle,
            F=2250,
            T=1023,
            P=6e5,
            y=self.sweep_comp,
            fix=False,
        )

        # SOEC water utilization
        self.soec_single_pass_water_conversion.fix(0.7)
        # Recycle splits
        self.sweep_recycle_split.split_fraction[:, "out"].fix(0.90)
        self.feed_recycle_split.split_fraction[:, "out"].fix(0.95)
        self.sweep_compressor.efficiency_isentropic.fix(0.85)
        self.sweep_compressor.control_volume.properties_out[:].pressure.fix(6e5)
        self.sweep_hx.area.fix(4000)
        self.sweep_hx.overall_heat_transfer_coefficient.fix(100)
        self.sweep_turbine.efficiency_isentropic.fix(0.85)
        self.sweep_turbine.control_volume.properties_out[:].temperature.fix(600)
        self.feed_hx01.area.fix(4000)
        self.feed_hx01.overall_heat_transfer_coefficient.fix(100)
        self.feed_heater.control_volume.properties_out[:].temperature.fix(1000)
        self.sweep_heater.control_volume.properties_out[:].temperature.fix(1000)
        self.water_split.split_fraction[:, "outlet1"].fix(0.5)
        self.water_pump.control_volume.properties_out[:].pressure.fix(6e5)
        self.water_pump.efficiency_isentropic[:].fix(0.8)
        self.water_heater01.area.fix(6000)
        self.water_heater01.overall_heat_transfer_coefficient.fix(100)
        self.water_heater02.area.fix(6000)
        self.water_heater02.overall_heat_transfer_coefficient.fix(100)
        self.h2_precooler.control_volume.properties_out[:].temperature.fix(300)
        self.cmp01.ratioP.fix(1.94)
        self.cmp01.efficiency_isentropic.fix(0.85)
        self.ic01.control_volume.properties_out[:].temperature.fix(300)
        self.cmp02.ratioP.fix(1.94)
        self.cmp02.efficiency_isentropic.fix(0.85)
        self.ic02.control_volume.properties_out[:].temperature.fix(300)
        self.cmp03.ratioP.fix(1.94)
        self.cmp03.efficiency_isentropic.fix(0.85)
        self.ic03.control_volume.properties_out[:].temperature.fix(300)
        self.cmp04.ratioP.fix(1.94)
        self.cmp04.efficiency_isentropic.fix(0.85)

    def initialize(
        self,
        outlvl=idaeslog.NOTSET,
        solver=None,
        optarg=None,
        load_from="soec_init.json.gz",
        save_to="soec_init.json.gz",
    ):
        init_log = idaeslog.getInitLogger(self.name, outlvl, tag="flowsheet")
        solve_log = idaeslog.getSolveLogger(self.name, outlvl, tag="flowsheet")

        if load_from is not None:
            if os.path.exists(load_from):
                init_log.info(f"SOEC load initial from {load_from}")
                # here suffix=False avoids loading scaling factors
                iutil.from_json(
                    self, fname=load_from, wts=iutil.StoreSpec(suffix=False)
                )
                return

        init_log.info("SOEC Initialization Starting")
        solver_obj = get_solver(solver, optarg)

        self.sweep_compressor.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.sweep03)
        self.feed_recycle_mix.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        self.sweep_recycle_mix.initialize(outlvl=outlvl, solver=solver, optarg=optarg)

        propagate_state(self.feed01)
        propagate_state(self.sweep01)
        self.sweep_heater.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        self.feed_heater.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.feed01b)
        propagate_state(self.sweep01b)

        self.soec_module.potential_cell.fix(1.288)
        self.soec_module.initialize(
            outlvl=outlvl,
            solver=solver,
            optarg=optarg,
            current_density_guess=-10000,
            temperature_guess=1023.15,
        )
        self.soec_module.potential_cell.unfix()

        propagate_state(self.ostrm01)
        self.sweep_recycle_split.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm01)
        self.feed_recycle_split.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.ostrm03)
        self.sweep_hx.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.ostrm04)
        self.sweep_turbine.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm03)
        propagate_state(self.ostrm05)
        self.feed_hx01.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.feed02)
        self.feed_translator.initialize(outlvl=outlvl, solver=solver, optarg=optarg)

        self.water_pump.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.water01)
        self.water_split.initialize()
        propagate_state(self.water02)
        propagate_state(self.water03)
        propagate_state(self.hstrm04)
        self.water_heater01.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        self.water_heater02.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.water04)
        propagate_state(self.water05)
        self.makeup_mix.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm06)
        self.h2_precooler.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm07)
        self.cmp01.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm08)
        self.ic01.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm09)
        self.cmp02.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm10)
        self.ic02.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm11)
        self.cmp03.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm12)
        self.ic03.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.hstrm13)
        self.cmp04.initialize(outlvl=outlvl, solver=solver, optarg=optarg)

        # solve with hydrogen side recycle first
        self.feed01b_expanded.deactivate()
        self.sweep02_expanded.deactivate()
        self.feed02b_expanded.deactivate()
        self.sweep01b_expanded.deactivate()
        self.soec_module.solid_oxide_cell.fuel_inlet.fix()
        self.soec_module.solid_oxide_cell.oxygen_inlet.fix()
        res = solver_obj.solve(self, tee=True)
        propagate_state(self.feed01b, overwrite_fixed=True)
        propagate_state(self.sweep01b, overwrite_fixed=True)
        res = solver_obj.solve(self, tee=True)
        propagate_state(self.feed01b, overwrite_fixed=True)
        propagate_state(self.sweep01b, overwrite_fixed=True)
        res = solver_obj.solve(self, tee=True)

        # solve with sweep recycle connected
        self.sweep01b_expanded.activate()
        self.soec_module.solid_oxide_cell.oxygen_inlet.unfix()
        self.feed01b_expanded.activate()
        self.soec_module.solid_oxide_cell.fuel_inlet.unfix()
        # self.sweep_recycle_mix.feed.pressure.unfix()
        res = solver_obj.solve(self, tee=True)

        self.sweep_recycle_mix.feed.unfix()
        self.sweep02_expanded.activate()
        # self.feed_recycle_mix.feed.pressure.unfix()
        res = solver_obj.solve(self, tee=True)

        self.feed_recycle_mix.feed.unfix()
        self.feed02b_expanded.activate()
        res = solver_obj.solve(self, tee=True)

        init_log.info("SOEC initialization complete")
        if save_to is not None:
            iutil.to_json(self)
            if save_to is not None:
                iutil.to_json(self, fname=save_to)
                init_log.info(f"Initialization saved to {save_to}")

    def _add_tags(self):
        tag_group = iutil.ModelTagGroup()
        self.tags_streams = tag_group
        stream_states = tables.stream_states_dict(
            tables.arcs_to_stream_dict(
                self,
                descend_into=False,
                additional={  # streams that are half in HRSG, and may not have arcs
                    "sweep04": self.sweep_compressor.inlet,
                    "feed03": self.feed_hx01.tube_inlet,
                    "hstrm05": self.water_heater01.shell_outlet,
                    "ostrm06": self.water_heater02.shell_outlet,
                    "water00": self.water_pump.inlet,
                    "hstrm15": self.cmp04.outlet,
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
            except AttributeError:
                # If there is no vapor fraction it's not steam/water and all
                # else is 100% vapor
                tag_group[f"{i}_vf"] = iutil.ModelTag(
                    doc=f"{i}: vapor fraction",
                    expr=100,
                    format_string="{:.2f}",
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
        tag_group["soec_makeup_water"] = iutil.ModelTag(
            doc="SOEC Makeup Water",
            expr=self.makeup_water_flow[0],
            format_string="{:.3f}",
            display_units=pyo.units.kg / pyo.units.s,
        )
        tag_group["variable_makeup_water_cost"] = iutil.ModelTag(
            doc="SOEC Makeup Water",
            expr=self.variable_makeup_water_cost[0],
            format_string="{:.3f}",
            display_units=pyo.units.USD_2018 / pyo.units.hr,
        )
        tag_group["soec_current"] = iutil.ModelTag(
            doc="SOEC electrical current",
            expr=self.soec_module.number_cells
            * sum(
                self.soec_module.solid_oxide_cell.current_density[0, iz]
                * self.soec_module.solid_oxide_cell.fuel_electrode.xface_area[iz]
                for iz in self.soec_module.solid_oxide_cell.iznodes
            ),
            format_string="{:.3f}",
            display_units=pyo.units.MA,
        )
        tag_group["soec_current_density"] = iutil.ModelTag(
            doc="SOEC electrical current density",
            expr=sum(self.soec_module.solid_oxide_cell.current_density[0, iz]
                                         * self.soec_module.solid_oxide_cell.fuel_electrode.xface_area[iz]
                                         for iz in self.soec_module.solid_oxide_cell.iznodes)/sum(
                                         self.soec_module.solid_oxide_cell.fuel_electrode.xface_area[iz]
                                         for iz in self.soec_module.solid_oxide_cell.iznodes
                                         ),
            format_string="{:.1f}",
            display_units=pyo.units.A/pyo.units.m**2,
        )
        tag_group["soec_power"] = iutil.ModelTag(
            doc="SOEC electric power",
            expr=self.soec_ac_power[0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["sweep_compressor_power"] = iutil.ModelTag(
            doc="Sweep compressor power",
            expr=self.sweep_compressor.control_volume.work[0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["sweep_turbine_power"] = iutil.ModelTag(
            doc="Sweep turbine power",
            expr=self.sweep_turbine.control_volume.work[0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
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
        tag_group["bop_power"] = iutil.ModelTag(
            doc="Total electric power for SOEC and auxilaries",
            expr=self.total_electric_power[0] - self.soec_ac_power[0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["total_electric_power_per_h2"] = iutil.ModelTag(
            doc="Total electric power for SOEC and auxilaries per H2 produced",
            expr=self.total_electric_power_per_h2[0],
            format_string="{:.3f}",
            display_units=pyo.units.kWh / pyo.units.kg,
        )
        tag_group["pump_power"] = iutil.ModelTag(
            doc="Makeup water pump power",
            expr=self.water_pump.control_volume.work[0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["total_compressor_power"] = iutil.ModelTag(
            doc="Total H2 compressor power",
            expr=self.total_compressor_power[0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["Number_of_cells"] = iutil.ModelTag(
            doc="Number of cells",
            expr=self.soec_module.number_cells,
            format_string="{:.4e}",
            display_units="cells",
        )
        tag_group["estimated_number_of_cells"] = iutil.ModelTag(
            doc="Estimated number of cells",
            expr=self.soec_module.number_cells,
            format_string="{:.4e}",
            display_units="cells",
        )
        tag_group["current_density"] = iutil.ModelTag(
            doc="Average current density of SOEC",
            expr=self.soec_module.solid_oxide_cell.average_current_density[0],
            format_string="{:.0f}",
            display_units=pyo.units.A / pyo.units.m**2,
        )
        tag_group["water_utilization"] = iutil.ModelTag(
            doc="Single pass water conversion",
            expr=self.soec_single_pass_water_conversion[0] * 100,
            format_string="{:.1f}",
            display_units="%",
        )
        tag_group["water_utilization_overall"] = iutil.ModelTag(
            doc="Single pass water conversion",
            expr=self.soec_overall_water_conversion[0] * 100,
            format_string="{:.1f}",
            display_units="%",
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
        for tag, stream, col in SoecFlowsheetData._stream_col_gen(tag_group):
            rows.add(stream)
            cols.add(col)
            tags.append((tag, stream, col))
        df = pd.DataFrame(index=sorted(rows), columns=sorted(cols))
        for tag, stream, col in tags:
            df.at[stream, col] = tag.get_display_value()
        return df

    def streams_dataframe(self):
        return self._stream_table(self.tags_streams)

    pfd_file = "soec_template.svg"
    def write_pfd(self, fname=None):
        """Add model results to the flowsheet template.  If fname is specified,
        this saves the resulting svg to a file.  If fname is not specified, it
        returns the svg string.
        Args:
            fname: Name of file to save svg.  If None, return the svg string
        Returns: (None or Str)
        """
        input_file = Path.cwd() / self.pfd_file
        with open(input_file, "r") as f:
            s = svg_tag(svg=f, tag_group=self.tags_streams, outfile=None)
        s = svg_tag(svg=s, tag_group=self.tags_output, outfile=None)
        s = svg_tag(svg=s, tag_group=self.tags_input, outfile=fname)
        if fname is None:
            return s

if __name__ == "__main__":
    import os
    import math
    import numpy as np
    import pytest
    from IPython.core.display import SVG
    import pyomo.environ as pyo
    from idaes.core.solvers import use_idaes_solver_configuration_defaults
    import idaes
    import idaes.logger as idaeslog
    import idaes.core.util.scaling as iscale
    import idaes.core.util as iutil
    import idaes.core.util.exceptions as idaes_except
    import idaes.core.util.model_statistics as mstat
    from idaes.core.util.model_statistics import degrees_of_freedom as dof
    import soec_flowsheet_costing
    import soec

    use_idaes_solver_configuration_defaults()
    idaes.cfg.ipopt.options.nlp_scaling_method = "user-scaling"
    idaes.cfg.ipopt["options"]["linear_solver"] = "ma57"
    idaes.cfg.ipopt["options"]["max_iter"] = 300
    idaes.cfg.ipopt["options"]["halt_on_ampl_error"] = "no"

    m = pyo.ConcreteModel()
    m.fs = soec.SoecFlowsheet(dynamic=False)
    iscale.calculate_scaling_factors(m)

    m.fs.initialize(load_from=None, outlvl=idaeslog.INFO_HIGH)
