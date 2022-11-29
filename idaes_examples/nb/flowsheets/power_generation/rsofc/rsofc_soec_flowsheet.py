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

"""
Flowsheet of the soec mode of the reversible sofc.
Air is used as sweep gas.
Use the optimize_model method to run the flowsheet at different H2 prod. rates.

"""

__author__ = "Chinedu Okoli"

# Import python modules
import os
import csv
import numpy as np
import pandas as pd

# Import pyomo modules
import pyomo.environ as pyo
from pyomo.util.calc_var_value import calculate_variable_from_constraint
from pyomo.network import Arc, Port
from pyomo.common.fileutils import this_file_dir

# Import modules from core
from idaes.core import FlowsheetBlock
import idaes.core.util as iutil
import idaes.core.util.tables as tables
import idaes.core.util.scaling as iscale
import idaes.core.util.initialization as iinit
from idaes.core.util import model_serializer as ms
import idaes.core.plugins
from idaes.core.solvers import use_idaes_solver_configuration_defaults

# Import unit models
from idaes.models_extra.power_generation.unit_models.helm import (
    HelmSplitter,
    HelmIsentropicCompressor,
)
import idaes.models.unit_models as gum  # generic unit models
from cpu import CPU
from idaes.models.unit_models.heat_exchanger import delta_temperature_underwood_callback
from idaes.models.unit_models.pressure_changer import ThermodynamicAssumption
from idaes.models.unit_models.separator import SplittingType
import idaes.models_extra.power_generation.unit_models.soc_submodels as soc

# Import properties
from idaes.models.properties.modular_properties.base.generic_property import (
    GenericParameterBlock,
)
from idaes.models.properties.modular_properties.base.generic_reaction import (
    GenericReactionParameterBlock,
)

from idaes.models_extra.power_generation.properties.natural_gas_PR import (
    get_prop,
    get_rxn,
    EosType,
)
from idaes.models.properties import iapws95


# Import costing
import rsofc_costing as rsofc_cost
from idaes.models_extra.power_generation.costing.power_plant_capcost import (
    QGESSCosting,
)

# Import logger
import idaes.logger as idaeslog


def _set_port(port, F, T, P, comp, fix=True):
    if fix:
        port.flow_mol.fix(F)
        port.temperature.fix(T)
        port.pressure.fix(P)
        for k, v in comp.items():
            port.mole_frac_comp[:, k].fix(v)
    else:
        port.flow_mol[:].value = F
        port.temperature[:].value = T
        port.pressure[:] = P
        for k, v in comp.items():
            port.mole_frac_comp[:, k].value = v


def add_flowsheet(m=None, name="SOEC Module"):
    if not hasattr(m, "soec_fs"):
        m.soec_fs = FlowsheetBlock(dynamic=False)
        m.soec_fs.costing = QGESSCosting()
    return m


def add_properties(fs):
    fuel_comp = {  # components present
        "CH4",
        "C2H6",
        "C3H8",
        "C4H10",
        "O2",
        "H2O",
        "CO2",
        "N2",
        "Ar",
    }
    air_comp = {  # components present
        "O2",
        "H2O",
        "CO2",
        "N2",
        "Ar",
    }
    fs.fg_prop = GenericParameterBlock(
        **get_prop(components=fuel_comp, phases=["Vap"], eos=EosType.IDEAL)
    )
    fs.fg_prop.set_default_scaling("mole_frac_comp", 1e2)
    fs.fg_prop.set_default_scaling("mole_frac_phase_comp", 1e2)
    rxns = {  # reactions and key components for conversion
        "ch4_cmb": "CH4",
        "c2h6_cmb": "C2H6",
        "c3h8_cmb": "C3H8",
        "c4h10_cmb": "C4H10",
    }
    fs.rxns = rxns
    fs.fg_combust = GenericReactionParameterBlock(**get_rxn(fs.fg_prop, rxns))
    fs.water_prop = iapws95.Iapws95ParameterBlock()
    fs.h2_prop = GenericParameterBlock(
        **get_prop(components={"H2", "H2O"}, phases=["Vap"], eos=EosType.IDEAL)
    )
    fs.o2_prop = GenericParameterBlock(
        **get_prop(components={"O2", "H2O"}, phases=["Vap"], eos=EosType.IDEAL)
    )
    fs.air_prop = GenericParameterBlock(
        **get_prop(components=air_comp, phases=["Vap"], eos=EosType.IDEAL)
    )
    fs.air_prop.set_default_scaling("mole_frac_comp", 1e2)
    fs.air_prop.set_default_scaling("mole_frac_phase_comp", 1e2)
    fs.h2_compress_prop = GenericParameterBlock(
        **get_prop(components={"H2"}, phases=["Vap"], eos=EosType.PR)
    )
    fs.h2_compress_prop.set_default_scaling("mole_frac_comp", 1e2)
    fs.h2_compress_prop.set_default_scaling("mole_frac_phase_comp", 1e2)

    fs.CO2_H2O_VLE = GenericParameterBlock(
        **get_prop(components=air_comp, phases=["Vap", "Liq"],)
    )
    fs.CO2_H2O_VLE.set_default_scaling("mole_frac_comp", 1e2)
    fs.CO2_H2O_VLE.set_default_scaling("mole_frac_phase_comp", 1e2)


def add_asu(fs):
    ###########################################################################
    #  Build unit operations
    ###########################################################################
    fs.air_compressor_s1 = gum.PressureChanger(
        compressor=True,
        property_package=fs.air_prop,
        thermodynamic_assumption=ThermodynamicAssumption.isentropic,
    )

    fs.intercooler_s1 = gum.Heater(
        property_package=fs.air_prop, has_pressure_change=True
    )

    fs.air_compressor_s2 = gum.PressureChanger(
        compressor=True,
        property_package=fs.air_prop,
        thermodynamic_assumption=ThermodynamicAssumption.isentropic,
    )

    fs.intercooler_s2 = gum.Heater(
        property_package=fs.air_prop, has_pressure_change=True
    )

    fs.ASU = gum.Separator(
        outlet_list=["N2_outlet", "O2_outlet"],
        split_basis=SplittingType.componentFlow,
        property_package=fs.air_prop,
    )

    ###########################################################################
    #  Specify performance variables of unit operations
    ###########################################################################
    # air compressors and intercoolers
    fs.air_compressor_s1.outlet.pressure.fix(111422)  # Pa (34 psia)
    fs.air_compressor_s1.efficiency_isentropic.fix(0.84)
    fs.intercooler_s1.outlet.temperature.fix(310.93)  # K (100 F)
    fs.intercooler_s1.deltaP.fix(-3447)  # Pa (-0.5 psi)
    fs.air_compressor_s2.outlet.pressure.fix(130686)  # Pa (79 psia)
    fs.air_compressor_s2.efficiency_isentropic.fix(0.84)
    fs.intercooler_s2.outlet.temperature.fix(310.93)  # K (100 F)
    fs.intercooler_s2.deltaP.fix(-3447)  # Pa (-0.5 psi)

    # air seperation unit
    fs.ASU.split_fraction[0, "O2_outlet", "CO2"].fix(1e-10)
    fs.ASU.split_fraction[0, "O2_outlet", "H2O"].fix(1e-10)
    fs.ASU.split_fraction[0, "O2_outlet", "N2"].fix(0.0005)
    fs.ASU.split_fraction[0, "O2_outlet", "O2"].fix(0.9691)
    fs.ASU.split_fraction[0, "O2_outlet", "Ar"].fix(0.0673)

    ###########################################################################
    #  Add stream connections
    ###########################################################################
    # Arcs for ASU, oxycombustor and CPU
    fs.STAGE_1_OUT = Arc(
        source=fs.air_compressor_s1.outlet, destination=fs.intercooler_s1.inlet
    )

    fs.IC_1_OUT = Arc(
        source=fs.intercooler_s1.outlet, destination=fs.air_compressor_s2.inlet
    )

    fs.STAGE_2_OUT = Arc(
        source=fs.air_compressor_s2.outlet, destination=fs.intercooler_s2.inlet
    )

    fs.ba01 = Arc(source=fs.intercooler_s2.outlet, destination=fs.ASU.inlet)


def add_preheater(fs):
    ###########################################################################
    #  Build unit operations
    ###########################################################################
    fs.oxygen_preheater = gum.HeatExchanger(
        delta_temperature_callback=delta_temperature_underwood_callback,
        hot_side_name="shell",
        cold_side_name="tube",
        shell={"property_package": fs.air_prop},
        tube={"property_package": fs.air_prop},
    )
    fs.ng_preheater = gum.HeatExchanger(
        delta_temperature_callback=delta_temperature_underwood_callback,
        hot_side_name="shell",
        cold_side_name="tube",
        shell={"property_package": fs.air_prop},
        tube={"property_package": fs.fg_prop},
    )
    fs.preheat_split = gum.Separator(
        property_package=fs.air_prop, outlet_list=["oxygen", "ng"],
    )

    ###########################################################################
    #  Specify performance variables of unit operations
    ###########################################################################
    fs.oxygen_preheater.overall_heat_transfer_coefficient.fix(100)
    fs.oxygen_preheater.delta_temperature_in.fix(10)  # fix DT for pinch side

    fs.ng_preheater.overall_heat_transfer_coefficient.fix(100)
    fs.ng_preheater.delta_temperature_in.fix(10)  # fix DT for pinch side

    fs.preheat_split.split_fraction[:, "oxygen"].fix(0.7)

    ###########################################################################
    #  Add stream connections
    ###########################################################################
    fs.o04 = Arc(source=fs.preheat_split.ng, destination=fs.ng_preheater.shell_inlet)
    fs.o05 = Arc(
        source=fs.preheat_split.oxygen, destination=fs.oxygen_preheater.shell_inlet
    )
    fs.ba02 = Arc(source=fs.ASU.O2_outlet, destination=fs.oxygen_preheater.tube_inlet)


def add_combustor(fs):
    ###########################################################################
    #  Build unit operations
    ###########################################################################
    fs.pre_oxycombustor_translator = gum.Translator(
        outlet_state_defined=True,
        inlet_property_package=fs.air_prop,
        outlet_property_package=fs.fg_prop,
    )
    fs.cmb_mix = gum.Mixer(
        property_package=fs.fg_prop,
        inlet_list=["ng", "air"],
        momentum_mixing_type=gum.MomentumMixingType.none,
    )
    fs.cmb = gum.StoichiometricReactor(
        property_package=fs.fg_prop,
        reaction_package=fs.fg_combust,
        has_pressure_change=False,
        has_heat_of_reaction=True,
        has_heat_transfer=True,  # Use to add Q to water/steam in tubes
    )
    fs.post_oxycombustor_translator = gum.Translator(
        outlet_state_defined=True,
        inlet_property_package=fs.fg_prop,
        outlet_property_package=fs.air_prop,
    )

    ###########################################################################
    #  Specify performance variables of unit operations
    ###########################################################################
    # Additional constraints to specify the pre combustor translator block
    @fs.pre_oxycombustor_translator.Constraint(fs.time)
    def pre_oxycombustor_translator_F(b, t):
        return b.inlet.flow_mol[t] == b.outlet.flow_mol[t]

    @fs.pre_oxycombustor_translator.Constraint(fs.time)
    def pre_oxycombustor_translator_T(b, t):
        return b.inlet.temperature[t] == b.outlet.temperature[t]

    @fs.pre_oxycombustor_translator.Constraint(fs.time)
    def pre_oxycombustor_translator_P(b, t):
        return b.inlet.pressure[t] == b.outlet.pressure[t]

    @fs.pre_oxycombustor_translator.Constraint(fs.time, fs.air_prop.component_list)
    def pre_oxycombustor_translator_x(b, t, j):
        return b.inlet.mole_frac_comp[t, j] == b.outlet.mole_frac_comp[t, j]

    for j in fs.fg_prop.component_list:
        if j not in fs.air_prop.component_list:
            fs.pre_oxycombustor_translator.outlet.mole_frac_comp[0, j].fix(1e-10)

    # Additional constraints to specify the mixer
    @fs.cmb_mix.Constraint(fs.time)
    def pressure_eqn(b, t):
        return b.mixed_state[t].pressure == b.ng_state[t].pressure

    # Additional constraints to specify the combustor reactions
    @fs.cmb.Constraint(fs.time, fs.rxns.keys())
    def reaction_extent(b, t, r):
        k = fs.rxns[r]
        prp = b.control_volume.properties_in[t]
        stc = -fs.fg_combust.rate_reaction_stoichiometry[r, "Vap", k]
        extent = b.rate_reaction_extent[t, r]
        return extent * stc == prp.flow_mol * prp.mole_frac_comp[k]

    # Additional constraints to specify the post combustor  translator block
    @fs.post_oxycombustor_translator.Constraint(fs.time)
    def post_oxycombustor_translator_F(b, t):
        return b.inlet.flow_mol[t] == b.outlet.flow_mol[t]

    @fs.post_oxycombustor_translator.Constraint(fs.time)
    def post_oxycombustor_translator_T(b, t):
        return b.inlet.temperature[t] == b.outlet.temperature[t]

    @fs.post_oxycombustor_translator.Constraint(fs.time)
    def post_oxycombustor_translator_P(b, t):
        return b.inlet.pressure[t] == b.outlet.pressure[t]

    @fs.post_oxycombustor_translator.Constraint(fs.time, fs.air_prop.component_list)
    def post_oxycombustor_translator_x(b, t, j):
        return b.inlet.mole_frac_comp[t, j] == b.outlet.mole_frac_comp[t, j]

    ###########################################################################
    #  Add stream connections
    ###########################################################################
    fs.cmb_mix_in = Arc(
        source=fs.oxygen_preheater.tube_outlet,
        destination=fs.pre_oxycombustor_translator.inlet,
    )
    fs.ba03 = Arc(
        source=fs.pre_oxycombustor_translator.outlet, destination=fs.cmb_mix.air
    )
    fs.bng01 = Arc(source=fs.ng_preheater.tube_outlet, destination=fs.cmb_mix.ng)
    fs.bng02 = Arc(source=fs.cmb_mix.outlet, destination=fs.cmb.inlet)
    fs.cmb_out = Arc(
        source=fs.cmb.outlet, destination=fs.post_oxycombustor_translator.inlet
    )
    fs.fg01 = Arc(
        source=fs.post_oxycombustor_translator.outlet,
        destination=fs.air_preheater_2.shell_inlet,
    )


def add_aux_boiler_steam(fs):
    ###########################################################################
    #  Build unit operations
    ###########################################################################
    fs.bhx2 = gum.Heater(  # in-bed heat exchanger to the oxycombustor
        has_pressure_change=False, property_package=fs.water_prop
    )
    fs.main_steam_split = HelmSplitter(
        property_package=fs.water_prop, outlet_list=["h_side", "o_side"]
    )
    fs.aux_boiler_feed_pump = HelmIsentropicCompressor(property_package=fs.water_prop)
    fs.bhx1 = gum.HeatExchanger(
        delta_temperature_callback=delta_temperature_underwood_callback,
        hot_side_name="shell",
        cold_side_name="tube",
        shell={"property_package": fs.h2_prop},
        tube={"property_package": fs.water_prop},
    )

    ###########################################################################
    #  Specify performance variables of unit operations
    ###########################################################################
    h_bhx2 = pyo.value(
        iapws95.htpx(1023.15 * pyo.units.K, 1.1e5 * pyo.units.Pa)
    )  # enthalpy outlet
    fs.bhx2.outlet.enth_mol.fix(
        h_bhx2
    )  # K (100 F) # unfix after initalize and spec Q from cmb

    fs.bhx1.overall_heat_transfer_coefficient.fix(100)
    fs.bhx1.delta_temperature_out.fix(10)  # fix DT for pinch side

    fs.aux_boiler_feed_pump.outlet.pressure.fix(1.1e5)
    fs.aux_boiler_feed_pump.efficiency_isentropic.fix(0.8)

    fs.main_steam_split.split_fraction[:, "h_side"].fix(0.9999)

    ###########################################################################
    #  Add stream connections
    ###########################################################################
    fs.s01 = Arc(source=fs.aux_boiler_feed_pump.outlet, destination=fs.bhx1.tube_inlet)
    fs.s02 = Arc(source=fs.bhx1.tube_outlet, destination=fs.bhx2.inlet)
    fs.s03 = Arc(source=fs.bhx2.outlet, destination=fs.main_steam_split.inlet)


def add_soec_air_side_units(fs):
    ###########################################################################
    #  Build unit operations
    ###########################################################################
    fs.air_blower = gum.PressureChanger(
        compressor=True,
        property_package=fs.air_prop,
        thermodynamic_assumption=ThermodynamicAssumption.isentropic,
    )
    fs.air_preheater_1 = gum.HeatExchanger(
        delta_temperature_callback=delta_temperature_underwood_callback,
        hot_side_name="shell",
        cold_side_name="tube",
        shell={"property_package": fs.air_prop},
        tube={"property_package": fs.air_prop},
    )
    fs.air_preheater_2 = gum.HeatExchanger(
        delta_temperature_callback=delta_temperature_underwood_callback,
        hot_side_name="shell",
        cold_side_name="tube",
        shell={"property_package": fs.air_prop},
        tube={"property_package": fs.air_prop},
    )
    ###########################################################################
    #  Specify performance variables of unit operations
    ###########################################################################
    fs.air_blower.outlet.pressure.fix(1.1e5)  # Pa (15.3 psi)
    fs.air_blower.efficiency_isentropic.fix(0.8)

    fs.air_preheater_1.overall_heat_transfer_coefficient.fix(100)
    fs.air_preheater_1.delta_temperature_in.fix(50)  # fix DT for pinch side

    fs.air_preheater_2.tube_outlet.temperature[0].fix(1023.15)  # Known value
    fs.air_preheater_2.overall_heat_transfer_coefficient.fix(100)

    ###########################################################################
    #  Add stream connections
    ###########################################################################
    fs.a01 = Arc(source=fs.air_blower.outlet, destination=fs.air_preheater_1.tube_inlet)
    fs.a02 = Arc(
        source=fs.air_preheater_1.tube_outlet, destination=fs.air_preheater_2.tube_inlet
    )


def add_soec_unit(fs):
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

    fs.soec_stack = soc.SolidOxideModuleSimple(
        solid_oxide_cell_config={
            "has_holdup": True,
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
        fuel_property_package=fs.h2_prop,
        oxygen_property_package=fs.air_prop,
    )
    fs.soec_stack.number_cells.fix(3.22e6)

    fs.spltf1 = gum.Separator(
        property_package=fs.h2_prop, outlet_list=["out", "recycle"],
    )
    fs.splta1 = gum.Separator(
        property_package=fs.air_prop, outlet_list=["out", "recycle"],
    )

    ###########################################################################
    #  Specify performance variables of unit operations
    ###########################################################################
    # soec performance variables
    _define_cell_params(fs)

    # performance variables for other units
    fs.spltf1.split_fraction[:, "out"].fix(0.98)
    fs.splta1.split_fraction[:, "out"].fix(0.9999)

    ###########################################################################
    #  Add stream connections
    ###########################################################################
    fs.o01 = Arc(
        doc="SOEC sweep gas out to recycle splitter",
        source=fs.soec_stack.oxygen_outlet,
        destination=fs.splta1.inlet,
    )
    fs.h01 = Arc(
        doc="SOEC hydrogen stream out to recycle splitter",
        source=fs.soec_stack.fuel_outlet,
        destination=fs.spltf1.inlet,
    )


def _define_cell_params(self):
    self.soec_stack.number_cells.fix(3.22e6)

    solid_oxide_cell = self.soec_stack.solid_oxide_cell  # abbreviation to shorten name
    solid_oxide_cell.fuel_channel.length_x.fix(0.002)
    solid_oxide_cell.length_y.fix(0.2345)
    solid_oxide_cell.length_z.fix(0.2345)
    solid_oxide_cell.fuel_channel.heat_transfer_coefficient.fix(100)

    solid_oxide_cell.oxygen_channel.length_x.fix(0.002)
    solid_oxide_cell.oxygen_channel.heat_transfer_coefficient.fix(100)

    solid_oxide_cell.fuel_electrode.length_x.fix(1e-3)
    solid_oxide_cell.fuel_electrode.porosity.fix(0.326)
    solid_oxide_cell.fuel_electrode.tortuosity.fix(3)  # Revisit
    solid_oxide_cell.fuel_electrode.solid_heat_capacity.fix(595)
    solid_oxide_cell.fuel_electrode.solid_density.fix(7740.0)
    solid_oxide_cell.fuel_electrode.solid_thermal_conductivity.fix(6.23)
    solid_oxide_cell.fuel_electrode.resistivity_log_preexponential_factor.fix(
        pyo.log(2.5e-5)
    )
    solid_oxide_cell.fuel_electrode.resistivity_thermal_exponent_dividend.fix(0)

    solid_oxide_cell.oxygen_electrode.length_x.fix(40e-6)
    solid_oxide_cell.oxygen_electrode.porosity.fix(0.30717)
    solid_oxide_cell.oxygen_electrode.tortuosity.fix(3.0)  # Revisit
    # Heat capacity and heat transfer coefficients of oxygen electrode aren't well
    # known but probably don't matter because the electrode is extremely thin
    solid_oxide_cell.oxygen_electrode.solid_heat_capacity.fix(142.3)
    solid_oxide_cell.oxygen_electrode.solid_density.fix(3030)
    solid_oxide_cell.oxygen_electrode.solid_thermal_conductivity.fix(5.84)
    # Also unknown but probably insignificant
    solid_oxide_cell.oxygen_electrode.resistivity_log_preexponential_factor.fix(
        pyo.log(7.8125e-05)
    )
    solid_oxide_cell.oxygen_electrode.resistivity_thermal_exponent_dividend.fix(0)

    solid_oxide_cell.electrolyte.length_x.fix(10.5e-6)
    solid_oxide_cell.electrolyte.heat_capacity.fix(400)
    solid_oxide_cell.electrolyte.density.fix(6000)
    solid_oxide_cell.electrolyte.thermal_conductivity.fix(2.17)
    solid_oxide_cell.electrolyte.resistivity_log_preexponential_factor.fix(-9.001)
    solid_oxide_cell.electrolyte.resistivity_thermal_exponent_dividend.fix(8988.134)
    solid_oxide_cell.fuel_triple_phase_boundary.exchange_current_log_preexponential_factor.fix(
        22.5
    )
    solid_oxide_cell.fuel_triple_phase_boundary.exchange_current_activation_energy.fix(
        110.802e3
    )
    solid_oxide_cell.fuel_triple_phase_boundary.activation_potential_alpha1.fix(
        0.647816
    )
    solid_oxide_cell.fuel_triple_phase_boundary.activation_potential_alpha2.fix(
        0.352184
    )

    solid_oxide_cell.fuel_triple_phase_boundary.exchange_current_exponent_comp[
        "H2"
    ].fix(1)
    solid_oxide_cell.fuel_triple_phase_boundary.exchange_current_exponent_comp[
        "H2O"
    ].fix(1)

    solid_oxide_cell.oxygen_triple_phase_boundary.exchange_current_log_preexponential_factor.fix(
        25.5
    )
    solid_oxide_cell.oxygen_triple_phase_boundary.exchange_current_activation_energy.fix(
        112.066e3
    )
    solid_oxide_cell.oxygen_triple_phase_boundary.activation_potential_alpha1.fix(0.503)
    solid_oxide_cell.oxygen_triple_phase_boundary.activation_potential_alpha2.fix(0.497)

    solid_oxide_cell.oxygen_triple_phase_boundary.exchange_current_exponent_comp[
        "O2"
    ].fix(0.5)


def add_soec_inlet_mix(fs):
    ###########################################################################
    #  Build unit operations
    ###########################################################################
    fs.mxf1 = gum.Mixer(
        property_package=fs.h2_prop,
        inlet_list=["water", "recycle"],
        momentum_mixing_type=gum.MomentumMixingType.none,
    )
    fs.mxa1 = gum.Mixer(
        property_package=fs.air_prop,
        inlet_list=["air", "recycle"],
        momentum_mixing_type=gum.MomentumMixingType.none,
    )
    fs.fuel_recycle_heater = gum.Heater(  # recycle heater for temperature control purposes
        has_pressure_change=False, property_package=fs.h2_prop
    )

    ###########################################################################
    #  Specify performance variables of unit operations
    ###########################################################################
    fs.fuel_recycle_heater.outlet.temperature.fix(1023.15)  # K

    @fs.mxf1.Constraint(fs.time)
    def fmxpress_eqn(b, t):
        return b.mixed_state[t].pressure == b.water_state[t].pressure

    @fs.mxa1.Constraint(fs.time)
    def amxpress_eqn(b, t):
        return b.mixed_state[t].pressure == b.air_state[t].pressure

    ###########################################################################
    #  Add stream connections
    ###########################################################################
    # Add ports to connect pure steam to steam + h2
    fs.main_steam_split._temperature_h_side_ref = pyo.Reference(
        fs.main_steam_split.h_side_state[:].temperature
    )

    @fs.main_steam_split.Expression(
        fs.time, fs.soec_stack.config.solid_oxide_cell_config.fuel_component_list
    )
    def h_side_mole_frac_expr(b, t, i):
        if i == "H2O":
            return 1
        else:
            return 0

    fs.main_steam_split.h_side_adapt = Port(
        rule=lambda b: {
            "flow_mol": fs.main_steam_split._flow_mol_h_side_ref,
            "pressure": fs.main_steam_split._pressure_h_side_ref,
            "temperature": fs.main_steam_split._temperature_h_side_ref,
            "mole_frac_comp": fs.main_steam_split.h_side_mole_frac_expr,
        }
    )

    fs.s04 = Arc(source=fs.main_steam_split.h_side_adapt, destination=fs.mxf1.water,)
    ###########################################################################

    ###########################################################################
    fs.hr01 = Arc(  # h2 rich air from soec recycle stream
        source=fs.spltf1.recycle, destination=fs.fuel_recycle_heater.inlet,
    )
    fs.hr02 = Arc(  # h2 rich air from soec recycle stream
        source=fs.fuel_recycle_heater.outlet, destination=fs.mxf1.recycle,
    )
    fs.a03 = Arc(source=fs.air_preheater_2.tube_outlet, destination=fs.mxa1.air)
    fs.s05 = Arc(
        doc="Feed heater to SOEC",
        source=fs.mxf1.outlet,
        destination=fs.soec_stack.fuel_inlet,
    )
    fs.s06 = Arc(
        doc="Sweep heater to SOEC",
        source=fs.mxa1.outlet,
        destination=fs.soec_stack.oxygen_inlet,
    )


def add_h2_compressor(fs):
    ###########################################################################
    #  Build unit operations
    ###########################################################################
    fs.hcmp_ic01 = gum.Heater(property_package=fs.h2_compress_prop)
    fs.hcmp01 = gum.Compressor(
        property_package=fs.h2_compress_prop,
        thermodynamic_assumption=ThermodynamicAssumption.isentropic,
    )
    fs.hcmp_ic02 = gum.Heater(property_package=fs.h2_compress_prop)
    fs.hcmp02 = gum.Compressor(
        property_package=fs.h2_compress_prop,
        thermodynamic_assumption=ThermodynamicAssumption.isentropic,
    )
    fs.hcmp_ic03 = gum.Heater(property_package=fs.h2_compress_prop)
    fs.hcmp03 = gum.Compressor(
        property_package=fs.h2_compress_prop,
        thermodynamic_assumption=ThermodynamicAssumption.isentropic,
    )
    fs.hcmp_ic04 = gum.Heater(property_package=fs.h2_compress_prop)
    fs.hcmp04 = gum.Compressor(
        property_package=fs.h2_compress_prop,
        thermodynamic_assumption=ThermodynamicAssumption.isentropic,
    )

    ###########################################################################
    #  Specify performance variables of unit operations
    ###########################################################################
    @fs.bhx1.Expression(fs.time, {"H2"})
    def waterless_mole_frac_expr(b, t, i):
        return 1

    @fs.bhx1.Expression(fs.time)
    def waterless_flow_expr(b, t):
        return (
            fs.bhx1._flow_mol_hot_side_outlet_ref[t]
            * fs.bhx1._mole_frac_comp_hot_side_outlet_ref[t, "H2"]
        )

    fs.bhx1.shell_outlet_drop_water = Port(
        rule=lambda b: {
            "flow_mol": fs.bhx1.waterless_flow_expr,
            "pressure": fs.bhx1._pressure_hot_side_outlet_ref,
            "temperature": fs.bhx1._temperature_hot_side_outlet_ref,
            "mole_frac_comp": fs.bhx1.waterless_mole_frac_expr,
        }
    )

    compressor_ratio = 2.828
    fs.hcmp_ic01.outlet.temperature.fix(298.15)
    fs.hcmp01.ratioP.fix(compressor_ratio)
    fs.hcmp01.efficiency_isentropic.fix(0.85)

    fs.hcmp_ic02.outlet.temperature.fix(303.15)
    fs.hcmp02.ratioP.fix(compressor_ratio)
    fs.hcmp02.efficiency_isentropic.fix(0.85)

    fs.hcmp_ic03.outlet.temperature.fix(303.15)
    fs.hcmp03.ratioP.fix(compressor_ratio)
    fs.hcmp03.efficiency_isentropic.fix(0.85)

    fs.hcmp_ic04.outlet.temperature.fix(303.15)
    fs.hcmp04.outlet.pressure.fix(64.79e5)
    fs.hcmp04.efficiency_isentropic.fix(0.85)

    ###########################################################################
    #  Add stream connections
    ###########################################################################
    fs.h03 = Arc(source=fs.bhx1.shell_outlet_drop_water, destination=fs.hcmp_ic01.inlet)
    fs.h04 = Arc(source=fs.hcmp_ic01.outlet, destination=fs.hcmp01.inlet)
    fs.h05 = Arc(source=fs.hcmp01.outlet, destination=fs.hcmp_ic02.inlet)
    fs.h06 = Arc(source=fs.hcmp_ic02.outlet, destination=fs.hcmp02.inlet)
    fs.h07 = Arc(source=fs.hcmp02.outlet, destination=fs.hcmp_ic03.inlet)
    fs.h08 = Arc(source=fs.hcmp_ic03.outlet, destination=fs.hcmp03.inlet)
    fs.h09 = Arc(source=fs.hcmp03.outlet, destination=fs.hcmp_ic04.inlet)
    fs.h10 = Arc(source=fs.hcmp_ic04.outlet, destination=fs.hcmp04.inlet)


def add_hrsg_and_cpu(fs):
    ###########################################################################
    #  Build unit operations
    ###########################################################################
    fs.HRSG_2 = gum.Heater(has_pressure_change=False, property_package=fs.air_prop)
    fs.HRSG_3 = gum.Heater(has_pressure_change=False, property_package=fs.air_prop)
    fs.HRSG_1 = gum.Heater(has_pressure_change=False, property_package=fs.air_prop)

    fs.condenser = gum.Heater(has_pressure_change=False, property_package=fs.air_prop)

    fs.CPU_translator = gum.Translator(
        outlet_state_defined=True,
        inlet_property_package=fs.air_prop,
        outlet_property_package=fs.CO2_H2O_VLE,
    )

    fs.flash = gum.Flash(
        has_heat_transfer=True,
        has_pressure_change=True,
        property_package=fs.CO2_H2O_VLE,
    )
    fs.CPU = CPU()

    ###########################################################################
    #  Specify performance variables of unit operations
    ###########################################################################
    fs.HRSG_2.outlet.temperature.fix(405)  # K

    fs.HRSG_3.outlet.temperature.fix(405)  # K

    fs.HRSG_1.outlet.temperature.fix(405)  # K

    fs.condenser.outlet.temperature.fix(310.9)  # K (100 F)

    fs.flash.heat_duty.fix(0)  # Adiabatic flash
    fs.flash.control_volume.properties_out[0].pressure.fix(101325)  # Pa

    # CPU translator constraints
    @fs.CPU_translator.Constraint(fs.time)
    def CPU_translator_F(b, t):
        return b.inlet.flow_mol[t] == b.outlet.flow_mol[t]

    @fs.CPU_translator.Constraint(fs.time)
    def CPU_translator_T(b, t):
        return b.inlet.temperature[t] == b.outlet.temperature[t]

    @fs.CPU_translator.Constraint(fs.time)
    def CPU_translator_P(b, t):
        return b.inlet.pressure[t] == b.outlet.pressure[t]

    @fs.CPU_translator.Constraint(fs.time, fs.CO2_H2O_VLE.component_list)
    def CPU_translator_x(b, t, j):
        return b.inlet.mole_frac_comp[t, j] == b.outlet.mole_frac_comp[t, j]

    for t in fs.time:
        for j in fs.air_prop.component_list:
            if j not in fs.CO2_H2O_VLE.component_list:
                fs.CPU_translator.outlet.mole_frac_comp[t, j].fix(1e-10)

    ###########################################################################
    #  Add stream connections
    ###########################################################################
    fs.o06 = Arc(source=fs.oxygen_preheater.shell_outlet, destination=fs.HRSG_2.inlet)
    fs.o07 = Arc(source=fs.ng_preheater.shell_outlet, destination=fs.HRSG_3.inlet)
    fs.fg02 = Arc(source=fs.air_preheater_2.shell_outlet, destination=fs.HRSG_1.inlet)
    fs.fg03 = Arc(source=fs.HRSG_1.outlet, destination=fs.condenser.inlet)
    fs.CPU_translator_in = Arc(
        source=fs.condenser.outlet, destination=fs.CPU_translator.inlet
    )
    fs.fg04 = Arc(source=fs.CPU_translator.outlet, destination=fs.flash.inlet)

    @fs.Constraint(fs.time)
    def CPU_inlet_F(fs, t):
        return 1e-3 * fs.CPU.inlet.flow_mol[t] == 1e-3 * fs.flash.vap_outlet.flow_mol[t]

    @fs.Constraint(fs.time)
    def CPU_inlet_T(fs, t):
        return (
            1e-3 * fs.CPU.inlet.temperature[t]
            == 1e-3 * fs.flash.vap_outlet.temperature[t]
        )

    @fs.Constraint(fs.time)
    def CPU_inlet_P(fs, t):
        return 1e-3 * fs.CPU.inlet.pressure[t] == 1e-3 * fs.flash.vap_outlet.pressure[t]

    @fs.Constraint(fs.time, fs.CO2_H2O_VLE.component_list)
    def CPU_inlet_x(fs, t, j):
        return (
            1e2 * fs.CPU.inlet.mole_frac_comp[t, j]
            == 1e2 * fs.flash.vap_outlet.mole_frac_comp[t, j]
        )


def add_more_hx_connections(fs):
    fs.h02 = Arc(source=fs.spltf1.out, destination=fs.bhx1.shell_inlet)
    fs.o02 = Arc(source=fs.splta1.out, destination=fs.air_preheater_1.shell_inlet)
    fs.o03 = Arc(
        source=fs.air_preheater_1.shell_outlet, destination=fs.preheat_split.inlet
    )


def add_design_constraints(fs):
    fs.cmb_temperature = pyo.Var(fs.time, initialize=1500, units=pyo.units.K)

    @fs.Constraint(fs.time)
    def cmb_temperature_eqn(b, t):
        return fs.cmb.outlet.temperature[t] == fs.cmb_temperature[t]

    fs.soec_steam_temperature = pyo.Var(fs.time, initialize=1023.15, units=pyo.units.K)

    @fs.Constraint(fs.time)
    def soec_steam_temperature_eqn(b, t):
        return (
            fs.bhx2.control_volume.properties_out[t].temperature
            == fs.soec_steam_temperature[t]
        )

    fs.excess_oxygen = pyo.Var(fs.time, initialize=1.09, units=pyo.units.dimensionless)
    fs.excess_oxygen.fix(1.09)

    @fs.Constraint(fs.time)
    def air_to_combustor(b, t):
        F_CH4 = (
            fs.ng_preheater.tube_inlet.flow_mol[t]
            * fs.ng_preheater.tube_inlet.mole_frac_comp[(t, "CH4")]
        )
        F_C2H6 = (
            fs.ng_preheater.tube_inlet.flow_mol[t]
            * fs.ng_preheater.tube_inlet.mole_frac_comp[(t, "C2H6")]
        )
        F_C3H8 = (
            fs.ng_preheater.tube_inlet.flow_mol[t]
            * fs.ng_preheater.tube_inlet.mole_frac_comp[(t, "C3H8")]
        )
        F_C4H10 = (
            fs.ng_preheater.tube_inlet.flow_mol[t]
            * fs.ng_preheater.tube_inlet.mole_frac_comp[(t, "C4H10")]
        )
        O2_required = 2 * F_CH4 + 3.5 * F_C2H6 + 5 * F_C3H8 + 6.5 * F_C4H10

        O2_fed = (
            fs.air_compressor_s1.inlet.flow_mol[t]
            * fs.air_compressor_s1.inlet.mole_frac_comp[(t, "O2")]
        )
        return 1e-1 * O2_fed == 1e-1 * fs.excess_oxygen[0] * O2_required

    # Constraint for Q from cmb to in-bed heat exchanger (produces steam)
    @fs.Constraint(fs.time)
    def combustor_heat(b, t):
        return fs.cmb.heat_duty[t] == -1 * (
            fs.bhx2.heat_duty[t] + fs.fuel_recycle_heater.heat_duty[t]
        )


def add_result_constraints(fs):
    @fs.Expression(fs.time)
    def module_electrical_work(b, t):
        return (
            b.soec_stack.number_cells * b.soec_stack.solid_oxide_cell.electrical_work[t]
        )

    fs.soec_power_DC = pyo.Var(
        fs.time, units=pyo.units.MW, doc="Direct current for the soec stack"
    )

    @fs.Constraint(fs.time)
    def soec_power_DC_constraint(b, t):
        return b.soec_power_DC[t] == pyo.units.convert(
            b.module_electrical_work[t], pyo.units.MW
        )

    # stack AC power
    fs.soec_power_AC = pyo.Var(
        fs.time,
        units=pyo.units.MW,
        doc="Alternating current from grid " "for the soec stack",
    )
    fs.inverter_efficiency = pyo.Param(initialize=0.97, mutable=True)

    @fs.Constraint(fs.time)
    def soec_power_AC_constraint(b, t):
        return b.soec_power_AC[t] * b.inverter_efficiency == b.soec_power_DC[t]

    @fs.Expression(fs.time)
    def hydrogen_product_rate_expr(b, t):
        return (
            b.bhx1.shell_outlet.flow_mol[t]
            * b.bhx1.shell_outlet.mole_frac_comp[t, "H2"]
        )

    fs.soec_single_pass_water_conversion = pyo.Var(fs.time, initialize=0.7)

    @fs.Constraint(fs.time)
    def soec_single_pass_water_conversion_eqn(b, t):
        return b.soec_single_pass_water_conversion[t] == (
            (
                b.soec_stack.solid_oxide_cell.fuel_channel.flow_mol_comp_outlet[t, "H2"]
                - b.soec_stack.solid_oxide_cell.fuel_channel.flow_mol_comp_inlet[
                    t, "H2"
                ]
            )
            / b.soec_stack.solid_oxide_cell.fuel_channel.flow_mol_comp_inlet[t, "H2O"]
        )

    fs.soec_overall_water_conversion = pyo.Var(fs.time, initialize=0.75)

    @fs.Constraint(fs.time)
    def soec_overall_water_conversion_eqn(b, t):
        return (
            b.soec_overall_water_conversion[t]
            == 1 - b.spltf1.inlet.mole_frac_comp[t, "H2O"]
        )

    fs.hydrogen_product_rate = pyo.Var(fs.time, units=pyo.units.mol / pyo.units.s)

    @fs.Constraint(fs.time)
    def hydrogen_product_rate_constraint(b, t):
        return b.hydrogen_product_rate[t] == b.hydrogen_product_rate_expr[t]

    @fs.Expression(fs.time)
    def h2_product_rate_mass(b, t):  # kg/s
        return fs.hydrogen_product_rate[t] * 0.002 * pyo.units.kg / pyo.units.mol

    @fs.Expression(fs.time)
    def soec_power_AC_per_h2(b, t):
        return (
            b.soec_power_AC[t]
            / b.hydrogen_product_rate_expr[t]
            / (0.002 * pyo.units.kg / pyo.units.mol)
        )

    @fs.Expression(fs.time)
    def h2_compressor_power_expr(b, t):
        return (
            fs.hcmp01.control_volume.work[t]
            + fs.hcmp02.control_volume.work[t]
            + fs.hcmp03.control_volume.work[t]
            + fs.hcmp04.control_volume.work[t]
        )

    fs.h2_compressor_power = pyo.Var(fs.time, units=pyo.units.MW)

    @fs.Constraint(fs.time)
    def h2_compressor_power_constraint(b, t):
        return b.h2_compressor_power[t] == pyo.units.convert(
            b.h2_compressor_power_expr[t], pyo.units.MW
        )

    # total heat supplied to HRSG
    fs.HRSG_heat_duty = pyo.Var(fs.time, initialize=300, units=pyo.units.MW)

    @fs.Constraint(fs.time)
    def HRSG_heat_duty_constraint(fs, t):
        return -1 * fs.HRSG_heat_duty[t] == pyo.units.convert(
            fs.HRSG_2.heat_duty[t], pyo.units.MW
        ) + pyo.units.convert(fs.HRSG_3.heat_duty[t], pyo.units.MW) + pyo.units.convert(
            fs.HRSG_1.heat_duty[t], pyo.units.MW
        )

    # steam required for ASU
    fs.ASU_HP_steam_heat = pyo.Var(fs.time, initialize=4, units=pyo.units.MW)

    @fs.Constraint(fs.time)
    def ASU_HP_steam_constraint(fs, t):
        return (
            fs.ASU_HP_steam_heat[t]
            == 0.005381 * pyo.units.MJ / pyo.units.mol * fs.ASU.O2_outlet.flow_mol[t]
        )

    # HRSG heat applied toward steam cycle
    fs.steam_cycle_heat = pyo.Var(fs.time, initialize=300, units=pyo.units.MW)

    @fs.Constraint(fs.time)
    def steam_cycle_heat_constraint(fs, t):
        return fs.steam_cycle_heat[t] == fs.HRSG_heat_duty[t] - fs.ASU_HP_steam_heat[t]

    # power generated by steam cycle
    fs.steam_cycle_efficiency = pyo.Param(initialize=0.381, mutable=True)
    fs.steam_cycle_power = pyo.Var(fs.time, initialize=100, units=pyo.units.MW)
    fs.steam_cycle_loss = pyo.Var(fs.time, initialize=200, units=pyo.units.MW)

    @fs.Constraint(fs.time)
    def steam_cycle_power_constraint(fs, t):
        return (
            fs.steam_cycle_power[t]
            == fs.steam_cycle_heat[t] * fs.steam_cycle_efficiency
        )

    @fs.Constraint(fs.time)
    def steam_cycle_loss_constraint(fs, t):
        return fs.steam_cycle_loss[t] == fs.steam_cycle_heat[t] * (
            1 - fs.steam_cycle_efficiency
        )

    # boiler feedwater pump load - steam cycle not modeled, scaled from BB
    fs.feedwater_pump_work = pyo.Var(fs.time, initialize=2, units=pyo.units.MW)

    @fs.Constraint(fs.time)
    def feedwater_pump_work_constraint(fs, t):
        ref_steam_cycle_power = 262.8 * pyo.units.MW
        ref_pump_work = 4.83 * pyo.units.MW
        return (
            fs.feedwater_pump_work[t] * ref_steam_cycle_power
            == ref_pump_work * fs.steam_cycle_power[t]
        )

    # condensate pump load - steam cycle not modeled, scaled from BB
    fs.condensate_pump_work = pyo.Var(fs.time, initialize=0.1, units=pyo.units.MW)

    @fs.Constraint(fs.time)
    def condensate_pump_work_constraint(fs, t):
        ref_steam_cycle_power = 262.8 * pyo.units.MW
        ref_pump_work = 0.15 * pyo.units.MW
        return (
            fs.condensate_pump_work[t] * ref_steam_cycle_power
            == ref_pump_work * fs.steam_cycle_power[t]
        )

    # steam turbine auxiliary load - steam cycle not modeled, scaled from BB
    fs.steam_turbine_auxiliary = pyo.Var(fs.time, initialize=0.1, units=pyo.units.MW)

    @fs.Constraint(fs.time)
    def steam_turbine_auxiliary_constraint(fs, t):
        ref_steam_cycle_power = 262.8 * pyo.units.MW
        ref_turbine_aux = 0.2 * pyo.units.MW
        return (
            fs.steam_turbine_auxiliary[t] * ref_steam_cycle_power
            == ref_turbine_aux * fs.steam_cycle_power[t]
        )

    # miscellaneous BOP - scaled from BB based on NG mass flow
    fs.misc_BOP_load = pyo.Var(fs.time, initialize=0.5, units=pyo.units.MW)

    @fs.Constraint(fs.time)
    def misc_BOP_load_constraint(fs, t):
        NG_flow = pyo.units.convert(
            fs.ng_preheater.tube.properties_in[t].flow_mass, pyo.units.lb / pyo.units.hr
        )
        ref_NG_flow = 148095 * pyo.units.lb / pyo.units.hr
        ref_load = 0.396 * pyo.units.MW
        return fs.misc_BOP_load[t] == ref_load * NG_flow / ref_NG_flow

    # calculate cooling water flowrate
    fs.cooling_water_duty = pyo.Var(fs.time, initialize=450, units=pyo.units.MW)
    fs.cooling_water_flowrate = pyo.Var(
        fs.time, initialize=3000, units=pyo.units.lb / pyo.units.s
    )

    @fs.Constraint(fs.time)
    def cooling_water_duty_constraint(fs, t):
        return fs.cooling_water_duty[t] == fs.steam_cycle_loss[t] + fs.CPU.heat_duty[
            t
        ] / 1e6 * pyo.units.MW + 7.327 * pyo.units.MW + pyo.units.convert(  # 25 MMbtu/hr of additional heat
            -1 * fs.intercooler_s1.heat_duty[t]
            + -1 * fs.intercooler_s2.heat_duty[t]
            + -1 * fs.hcmp_ic01.heat_duty[t]
            + -1 * fs.hcmp_ic02.heat_duty[t]
            + -1 * fs.hcmp_ic03.heat_duty[t]
            + -1 * fs.hcmp_ic04.heat_duty[t],
            pyo.units.MW,
        ) + pyo.units.convert(
            -1 * fs.condenser.heat_duty[t], pyo.units.MW
        )

    @fs.Constraint(fs.time)
    def cooling_water_flowrate_constraint(fs, t):
        heat_capacity = 75.38 * pyo.units.J / pyo.units.mol / pyo.units.K
        delta_T = 36 * pyo.units.K
        molar_mass = 18 * pyo.units.g / pyo.units.mol
        return fs.cooling_water_flowrate[t] == pyo.units.convert(
            fs.cooling_water_duty[t] * molar_mass / heat_capacity / delta_T,
            pyo.units.lb / pyo.units.s,
        )

    # circulating pump work - not modeled, scaled from NGFC pathways study
    fs.circulating_pump_work = pyo.Var(fs.time, initialize=1, units=pyo.units.MW)

    @fs.Constraint(fs.time)
    def circulating_pump_work_constraint(fs, t):
        ref_flowrate = 18602.6 * pyo.units.lb / pyo.units.s
        ref_load = 2.778 * pyo.units.MW
        return (
            fs.circulating_pump_work[t] * ref_flowrate
            == ref_load * fs.cooling_water_flowrate[t]
        )

    # cooling tower fan load - not modeled, scaled from NGFC pathways study
    fs.cooling_tower_load = pyo.Var(fs.time, initialize=1, units=pyo.units.MW)

    @fs.Constraint(fs.time)
    def cooling_tower_load_constraint(fs, t):
        ref_flowrate = 18602.6 * pyo.units.lb / pyo.units.s
        ref_load = 1.4372 * pyo.units.MW
        return (
            fs.cooling_tower_load[t] * ref_flowrate
            == ref_load * fs.cooling_water_flowrate[t]
        )

    # auxiliary load of the plant
    fs.auxiliary_load = pyo.Var(fs.time, initialize=60, units=pyo.units.MW)

    @fs.Constraint(fs.time)
    def auxiliary_load_constraint(fs, t):
        return fs.auxiliary_load[t] == fs.CPU.work[t] / 1e6 + fs.feedwater_pump_work[
            t
        ] + fs.condensate_pump_work[t] + fs.steam_turbine_auxiliary[
            t
        ] + fs.misc_BOP_load[
            t
        ] + fs.circulating_pump_work[
            t
        ] + fs.cooling_tower_load[
            t
        ] + pyo.units.convert(
            (
                fs.air_blower.work_mechanical[t] / 0.95
                + fs.aux_boiler_feed_pump.work_mechanical[t] / 0.95
                + fs.air_compressor_s1.work_mechanical[t] / 0.96
                + fs.air_compressor_s2.work_mechanical[t] / 0.96
                + fs.hcmp01.work_mechanical[t] / 0.96
                + fs.hcmp02.work_mechanical[t] / 0.96
                + fs.hcmp03.work_mechanical[t] / 0.96
                + fs.hcmp04.work_mechanical[t] / 0.96
            ),
            pyo.units.MW,
        )

    fs.transformer_losses = pyo.Var(fs.time, initialize=2, units=pyo.units.MW)

    @fs.Constraint(fs.time)
    def transformer_losses_constraint(fs, t):
        HV_aux = (
            pyo.units.convert(
                fs.air_compressor_s1.work_mechanical[t] / 0.96
                + fs.air_compressor_s2.work_mechanical[t] / 0.96
                + fs.air_compressor_s2.work_mechanical[t] / 0.96
                + fs.hcmp01.work_mechanical[t] / 0.96
                + fs.hcmp02.work_mechanical[t] / 0.96
                + fs.hcmp03.work_mechanical[t] / 0.96
                + fs.hcmp04.work_mechanical[t] / 0.96,
                pyo.units.MW,
            )
            + fs.CPU.work[t] / 1e6
        )
        MV_aux = fs.auxiliary_load[t] - HV_aux
        LV_aux = MV_aux * 0.15

        HV_gen_loss = (
            (fs.steam_cycle_power[t] - fs.auxiliary_load[t]) + HV_aux
        ) * 0.003
        HV_loss = HV_aux * 0.003
        MV_loss = MV_aux * 0.005
        LV_loss = LV_aux * 0.005

        return fs.transformer_losses[t] == HV_gen_loss + HV_loss + MV_loss + LV_loss

    # net plant power
    fs.net_power = pyo.Var(fs.time, initialize=660, units=pyo.units.MW)

    @fs.Constraint(fs.time)
    def net_power_constraint(fs, t):
        return (
            -1 * fs.net_power[t]
            == fs.steam_cycle_power[t]
            - fs.soec_power_AC[t]
            - fs.auxiliary_load[t]
            - fs.transformer_losses[t]
        )

    # HHV efficiency
    fs.HHV_efficiency = pyo.Var(fs.time, initialize=0.6)

    @fs.Constraint(fs.time)
    def efficiency_rule(fs, t):
        NG_HHV = 908839.23 * pyo.units.J / pyo.units.mol
        H2_HHV = (
            141.7e6 * pyo.units.J / pyo.units.kg
        )  # Ref: https://www.engineeringtoolbox.com/fuels-higher-calorific-values-d_169.html
        return fs.HHV_efficiency[t] == (
            fs.net_power[t]
            + pyo.units.convert((H2_HHV * fs.h2_product_rate_mass[t]), pyo.units.MW)
        ) / pyo.units.convert(
            (NG_HHV * fs.ng_preheater.tube.properties_in[t].flow_mol), pyo.units.MW
        )

    # CO2 captured in kg/hr
    fs.CO2_captured = pyo.Var(
        fs.time, initialize=300, units=pyo.units.kg / pyo.units.hr
    )

    @fs.Constraint(fs.time)
    def CO2_captured_constraint(fs, t):
        mass_flow = (
            fs.CPU.pureco2.flow_mol[t]
            * fs.CPU.pureco2.mole_frac_comp[t, "CO2"]
            * 0.04401
            * pyo.units.kg
            / pyo.units.mol
        )
        return fs.CO2_captured[t] == pyo.units.convert(
            mass_flow, pyo.units.kg / pyo.units.hr
        )

    # CO2 emissions in kg/hr
    fs.CO2_emissions = pyo.Var(
        fs.time, initialize=300, units=pyo.units.kg / pyo.units.hr
    )

    @fs.Constraint(fs.time)
    def CO2_emission_constraint(fs, t):
        mass_flow = (
            fs.CPU.vent.flow_mol[t]
            * fs.CPU.vent.mole_frac_comp[t, "CO2"]
            * 0.04401
            * pyo.units.kg
            / pyo.units.mol
        )
        return fs.CO2_emissions[t] == pyo.units.convert(
            -1 * mass_flow, pyo.units.kg / pyo.units.hr
        )

    @fs.Expression(fs.time)
    def CO2_capture_efficiency_expr(fs, t):
        return (
            fs.CPU.pureco2.flow_mol[t] * fs.CPU.pureco2.mole_frac_comp[t, "CO2"]
        ) / (fs.CPU.inlet.flow_mol[t] * fs.CPU.inlet.mole_frac_comp[t, "CO2"])

    fs.CO2_capture_efficiency = pyo.Var(
        fs.time, initialize=90, units=pyo.units.dimensionless
    )

    @fs.Constraint(fs.time)
    def CO2_capture_efficiency_constraint(fs, t):
        return fs.CO2_capture_efficiency[t] == fs.CO2_capture_efficiency_expr[t]

    @fs.Expression(fs.time)
    def net_power_per_mass_h2(b, t):
        return fs.net_power[t] / fs.h2_product_rate_mass[t]


def initialize_results(fs):
    """

    Parameters
    ----------
    fs : flowsheet object.

    Returns
    -------
    variables : list of initialized result variables.

    """

    variables = [
        fs.hydrogen_product_rate,
        fs.h2_compressor_power,
        fs.soec_power_DC,
        fs.soec_power_AC,
        fs.HRSG_heat_duty,
        fs.ASU_HP_steam_heat,
        fs.steam_cycle_heat,
        fs.steam_cycle_power,
        fs.steam_cycle_loss,
        fs.feedwater_pump_work,
        fs.condensate_pump_work,
        fs.steam_turbine_auxiliary,
        fs.misc_BOP_load,
        fs.cooling_water_duty,
        fs.cooling_water_flowrate,
        fs.circulating_pump_work,
        fs.cooling_tower_load,
        fs.auxiliary_load,
        fs.transformer_losses,
        fs.net_power,
        fs.HHV_efficiency,
        fs.CO2_captured,
        fs.CO2_emissions,
        fs.CO2_capture_efficiency,
    ]

    constraints = [
        fs.hydrogen_product_rate_constraint,
        fs.h2_compressor_power_constraint,
        fs.soec_power_DC_constraint,
        fs.soec_power_AC_constraint,
        fs.HRSG_heat_duty_constraint,
        fs.ASU_HP_steam_constraint,
        fs.steam_cycle_heat_constraint,
        fs.steam_cycle_power_constraint,
        fs.steam_cycle_loss_constraint,
        fs.feedwater_pump_work_constraint,
        fs.condensate_pump_work_constraint,
        fs.steam_turbine_auxiliary_constraint,
        fs.misc_BOP_load_constraint,
        fs.cooling_water_duty_constraint,
        fs.cooling_water_flowrate_constraint,
        fs.circulating_pump_work_constraint,
        fs.cooling_tower_load_constraint,
        fs.auxiliary_load_constraint,
        fs.transformer_losses_constraint,
        fs.net_power_constraint,
        fs.efficiency_rule,
        fs.CO2_captured_constraint,
        fs.CO2_emission_constraint,
        fs.CO2_capture_efficiency_constraint,
    ]

    for v, c in zip(variables, constraints):
        for t in fs.time:
            calculate_variable_from_constraint(v[t], c[t])

    return variables


def set_guess(fs):
    # Set guess for tear streams/ports (preheat_split.inlet, soec inlet)
    comp_guess = {  # air_prop is used as assumption as all fuel is combusted
        "O2": 0.2074,
        "H2O": 0.0099,
        "CO2": 0.0003,
        "N2": 0.7732,
        "Ar": 0.0092,
    }

    _set_port(
        fs.preheat_split.inlet, F=7765, T=700, P=1.04e5, comp=comp_guess, fix=True
    )

    # Set guess for temp, pressure and mole frac conditions to initalize soec
    fs.soec_stack.fuel_inlet.flow_mol[0].fix(5600)
    fs.soec_stack.fuel_inlet.temperature[0].fix(1023.15)
    fs.soec_stack.fuel_inlet.pressure[0].fix(1.01325e5)
    fs.soec_stack.fuel_inlet.mole_frac_comp[0, "H2O"].fix(0.90)
    fs.soec_stack.fuel_inlet.mole_frac_comp[0, "H2"].fix(0.10)

    fs.soec_stack.oxygen_inlet.flow_mol[0].fix(5600)
    fs.soec_stack.oxygen_inlet.temperature[0].fix(1023.15)
    fs.soec_stack.oxygen_inlet.pressure[0].fix(1.01325e5)
    fs.soec_stack.oxygen_inlet.mole_frac_comp[0, "O2"].fix(0.2074)
    fs.soec_stack.oxygen_inlet.mole_frac_comp[0, "H2O"].fix(0.0099)
    fs.soec_stack.oxygen_inlet.mole_frac_comp[0, "N2"].fix(0.7732)
    fs.soec_stack.oxygen_inlet.mole_frac_comp[0, "Ar"].fix(0.0092)
    fs.soec_stack.oxygen_inlet.mole_frac_comp[0, "CO2"].fix(0.0003)


def set_inputs(fs):
    # Set combustor outlet temperature and soec steam temperature
    fs.cmb_temperature.fix(1500)
    fs.soec_steam_temperature.fix(1023.15)

    # Set feed conditions of input fuel and utilities
    # Note that flowrate vars for mxa1.air, air_compressor_s1.inlet,
    # aux_boiler_feed_pump.inlet, and fs.ng_preheater.tube_inlet are dof or
    # design specs that will be unfixed at final solve
    air_comp = {
        "O2": 0.2074,
        "H2O": 0.0099,
        "CO2": 0.0003,
        "N2": 0.77320,
        "Ar": 0.0092,
    }
    ng_comp = {
        "CH4": 0.931,
        "C2H6": 0.0320,
        "C3H8": 0.007,
        "C4H10": 0.004,
        "O2": 0,
        "H2O": 0,
        "CO2": 0.01,
        "N2": 0.0160,
        "Ar": 0,
    }
    _set_port(
        fs.air_compressor_s1.inlet,
        F=12000,
        T=288.15,
        P=1.01325e5,
        comp=air_comp,
        fix=True,
    )
    _set_port(
        fs.ng_preheater.tube_inlet, F=1000, T=330, P=1.04e5, comp=ng_comp, fix=True
    )
    _set_port(
        fs.air_blower.inlet, F=5600, T=288.15, P=1.01325e5, comp=air_comp, fix=True
    )
    _set_port(
        fs.mxa1.recycle,
        F=1e-3,  # Flow set to tiny val
        T=1023.15,
        P=1.04e5,
        comp={"O2": 0.2074, "H2O": 0.0099, "CO2": 0.0003, "N2": 0.7732, "Ar": 0.0092},
        fix=True,
    )

    fs.aux_boiler_feed_pump.inlet.flow_mol.fix(5600)
    fs.aux_boiler_feed_pump.inlet.enth_mol.fix(
        iapws95.htpx(T=288.75 * pyo.units.K, P=101325 * pyo.units.Pa)
    )
    fs.aux_boiler_feed_pump.inlet.pressure.fix(101325)


def initialize_plant(fs, solver):
    # Initialize soec_stack to H2/O2 flow path (tear-stream path)
    fs.soec_stack.solid_oxide_cell.potential.fix(
        1.285
    )  # Roughly at the thermoneutral point
    fs.soec_stack.initialize(
        current_density_guess=-5000, temperature_guess=1023.15,  # mA/cm2
    )
    iinit.propagate_state(fs.h01)
    iinit.propagate_state(fs.o01)
    fs.spltf1.initialize()
    iinit.propagate_state(fs.h02)
    iinit.propagate_state(fs.hr01)
    fs.fuel_recycle_heater.initialize()
    iinit.propagate_state(fs.hr02)
    fs.splta1.initialize()
    iinit.propagate_state(fs.o02)

    # Initialize preheater splitter path (tear-stream path)
    fs.preheat_split.initialize()
    iinit.propagate_state(fs.o04)
    iinit.propagate_state(fs.o05)

    # Initialize air/ng feed to combustor path
    fs.air_compressor_s1.initialize()
    iinit.propagate_state(fs.STAGE_1_OUT)
    fs.intercooler_s1.initialize()
    iinit.propagate_state(fs.IC_1_OUT)
    fs.air_compressor_s2.initialize()
    iinit.propagate_state(fs.STAGE_2_OUT)
    fs.intercooler_s2.initialize()
    iinit.propagate_state(fs.ba01)
    fs.ASU.initialize()
    iinit.propagate_state(fs.ba02)
    fs.oxygen_preheater.initialize()
    iinit.propagate_state(fs.cmb_mix_in)
    fs.pre_oxycombustor_translator.initialize()
    iinit.propagate_state(fs.ba03)
    fs.ng_preheater.initialize()
    iinit.propagate_state(fs.bng01)
    fs.cmb_mix.initialize()
    iinit.propagate_state(fs.bng02)
    fs.cmb.initialize()
    iinit.propagate_state(fs.cmb_out)
    fs.post_oxycombustor_translator.initialize()
    iinit.propagate_state(fs.fg01)

    # Initialize water feed to soec steam input path
    fs.aux_boiler_feed_pump.initialize()
    iinit.propagate_state(fs.s01)
    fs.bhx1.initialize()
    iinit.propagate_state(fs.s02)
    fs.bhx2.initialize()
    iinit.propagate_state(fs.s03)
    fs.main_steam_split.initialize()
    fs.mxf1.initialize()
    iinit.propagate_state(fs.s05)

    # Initialize air to soec sweep air input path
    fs.air_blower.initialize()
    iinit.propagate_state(fs.a01)
    fs.air_preheater_1.initialize()
    iinit.propagate_state(fs.a02)
    fs.air_preheater_2.initialize()
    iinit.propagate_state(fs.a03)
    fs.mxa1.initialize()
    iinit.propagate_state(fs.s06)
    iinit.propagate_state(fs.o03)

    # Unfix tear/guess streams
    fs.preheat_split.inlet.unfix()

    # Unfix some dof
    fs.bhx2.outlet.enth_mol.unfix()  # related to soec_steam_temperature eqn
    fs.air_compressor_s1.inlet.flow_mol.unfix()  # related to ng to air flow constraint
    fs.ng_preheater.tube_inlet.flow_mol.unfix()  # related to fixing cmb temperature

    fs.soec_stack.fuel_inlet.unfix()
    fs.soec_stack.oxygen_inlet.unfix()

    # Vary air_blower.inlet such that O2 mole frac <= 0.35
    fs.air_blower.inlet.flow_mol.unfix()
    fs.soec_stack.oxygen_outlet.mole_frac_comp[0, "O2"].fix(0.35)

    solver.solve(
        fs,
        tee=True,
        options={
            "max_iter": 50,
            "tol": 1e-7,
            "bound_push": 1e-12,
            "linear_solver": "ma57",
            "nlp_scaling_method": "user-scaling",
        },
        symbolic_solver_labels=True,
    )


def initialize_bop(fs, solver):
    iinit.propagate_state(fs.h03)
    fs.hcmp_ic01.initialize()
    iinit.propagate_state(fs.h04)
    fs.hcmp01.initialize()
    iinit.propagate_state(fs.h05)
    fs.hcmp_ic02.initialize()
    iinit.propagate_state(fs.h06)
    fs.hcmp02.initialize()
    iinit.propagate_state(fs.h07)
    fs.hcmp_ic03.initialize()
    iinit.propagate_state(fs.h08)
    fs.hcmp03.initialize()
    iinit.propagate_state(fs.h09)
    fs.hcmp_ic04.initialize()
    iinit.propagate_state(fs.h10)
    fs.hcmp04.initialize()

    iinit.propagate_state(fs.o06)
    fs.HRSG_2.initialize()
    iinit.propagate_state(fs.o07)
    fs.HRSG_3.initialize()
    iinit.propagate_state(fs.fg02)
    fs.HRSG_1.initialize()

    iinit.propagate_state(fs.fg03)
    fs.condenser.initialize()
    fs.condenser.outlet.display()

    iinit.propagate_state(fs.CPU_translator_in)
    fs.CPU_translator.initialize()
    iinit.propagate_state(fs.fg04)
    fs.flash.initialize()

    # Initialize CPU inlet
    calculate_variable_from_constraint(fs.CPU.inlet.flow_mol[0], fs.CPU_inlet_F[0])
    calculate_variable_from_constraint(fs.CPU.inlet.pressure[0], fs.CPU_inlet_P[0])
    calculate_variable_from_constraint(fs.CPU.inlet.temperature[0], fs.CPU_inlet_T[0])
    fs.CPU.initialize()

    solver.solve(
        fs,
        tee=True,
        options={
            "max_iter": 200,
            "tol": 1e-7,
            "bound_push": 1e-12,
            "linear_solver": "ma27",
            "nlp_scaling_method": "user-scaling",
        },
        symbolic_solver_labels=True,
    )


def add_scaling(fs):
    for t, c in fs.oxygen_preheater.heat_transfer_equation.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)
    for t, c in fs.ng_preheater.heat_transfer_equation.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)
    for t, c in fs.bhx1.heat_transfer_equation.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)
    for t, c in fs.air_preheater_1.heat_transfer_equation.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)
    for t, c in fs.air_preheater_2.heat_transfer_equation.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)

    for t, c in fs.mxf1.enthalpy_mixing_equations.items():
        iscale.constraint_scaling_transform(c, 1e-6, overwrite=True)
    for t, c in fs.mxa1.enthalpy_mixing_equations.items():
        iscale.constraint_scaling_transform(c, 1e-6, overwrite=True)
    for t, c in fs.oxygen_preheater.unit_heat_balance.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)
    for t, c in fs.ng_preheater.unit_heat_balance.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)
    for t, c in fs.bhx1.unit_heat_balance.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)
    for t, c in fs.air_preheater_1.unit_heat_balance.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)
    for t, c in fs.air_preheater_2.unit_heat_balance.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)

    for t, c in fs.fuel_recycle_heater.control_volume.enthalpy_balances.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)

    for t, c in fs.mxf1.fmxpress_eqn.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)
    for t, c in fs.mxa1.amxpress_eqn.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)
    for t, c in fs.cmb_mix.pressure_eqn.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)

    for t, c in fs.cmb_mix.enthalpy_mixing_equations.items():
        iscale.constraint_scaling_transform(c, 1e-6, overwrite=True)
    for t, c in fs.cmb.control_volume.enthalpy_balances.items():
        iscale.constraint_scaling_transform(c, 1e-6, overwrite=True)
    for t, c in fs.cmb.control_volume.properties_in[t].total_flow_balance.items():
        iscale.constraint_scaling_transform(c, 1e-1, overwrite=True)
    for t, c in fs.cmb.control_volume.properties_in[0].component_flow_balances.items():
        iscale.constraint_scaling_transform(c, 1e3, overwrite=True)
    for (t, j), c in fs.cmb.control_volume.material_balances.items():
        iscale.constraint_scaling_transform(c, 1e-1, overwrite=True)
    for (
        (t, p, j,),
        c,
    ) in fs.cmb.control_volume.rate_reaction_stoichiometry_constraint.items():
        iscale.constraint_scaling_transform(c, 1e-1, overwrite=True)

    for t, c in fs.pre_oxycombustor_translator.pre_oxycombustor_translator_F.items():
        iscale.constraint_scaling_transform(c, 1e-1, overwrite=True)
    for t, c in fs.pre_oxycombustor_translator.pre_oxycombustor_translator_P.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)

    for t, c in fs.post_oxycombustor_translator.post_oxycombustor_translator_F.items():
        iscale.constraint_scaling_transform(c, 1e-1, overwrite=True)
    for t, c in fs.post_oxycombustor_translator.post_oxycombustor_translator_P.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)

    for t, c in fs.aux_boiler_feed_pump.eq_work.items():
        iscale.constraint_scaling_transform(c, 1e-10, overwrite=True)
    for (t, r), v in fs.cmb.control_volume.rate_reaction_extent.items():
        iscale.set_scaling_factor(fs.cmb.control_volume.rate_reaction_extent, 1e-1)
    for (t, p, j), v in fs.cmb.control_volume.rate_reaction_generation.items():
        iscale.set_scaling_factor(fs.cmb.control_volume.rate_reaction_generation, 1e-1)


def add_scaling_bop(fs):
    iscale.set_scaling_factor(fs.HRSG_2.control_volume.heat, 1e-5)
    iscale.set_scaling_factor(fs.HRSG_3.control_volume.heat, 1e-5)
    iscale.set_scaling_factor(fs.HRSG_1.control_volume.heat, 1e-5)
    iscale.set_scaling_factor(fs.condenser.control_volume.heat, 1e-4)
    iscale.set_scaling_factor(fs.flash.control_volume.heat, 1e-4)

    for t, c in fs.hcmp03.isentropic_pressure.items():
        iscale.constraint_scaling_transform(c, 1e-6, overwrite=True)

    for t, c in fs.CPU_translator.CPU_translator_F.items():
        iscale.constraint_scaling_transform(c, 1e-3, overwrite=True)
    for t, c in fs.CPU_translator.CPU_translator_P.items():
        iscale.constraint_scaling_transform(c, 1e-3, overwrite=True)
    for (p, q, j), c in fs.CPU_translator.properties_out[
        t
    ].equilibrium_constraint.items():
        iscale.constraint_scaling_transform(c, 1e-3, overwrite=True)

    for t, c in fs.condenser.control_volume.enthalpy_balances.items():
        iscale.constraint_scaling_transform(c, 1e-3, overwrite=True)

    for t, c in fs.HRSG_1.control_volume.enthalpy_balances.items():
        iscale.constraint_scaling_transform(c, 1e-3, overwrite=True)

    for t, c in fs.CPU.pureco2_pressure_eq.items():
        iscale.constraint_scaling_transform(c, 1e-5, overwrite=True)
    for t, c in fs.CPU.water_pressure_eq.items():
        iscale.constraint_scaling_transform(c, 1e-3, overwrite=True)
    for t, c in fs.CPU.vent_pressure_eq.items():
        iscale.constraint_scaling_transform(c, 1e-3, overwrite=True)


def set_missing_scaling_and_bounds(fs):
    # loop through all Expressions for more compact script
    # find any objects missing scaling factors and add scaling factors of 1
    for expr in fs.component_data_objects(pyo.Expression, descend_into=True):
        if iscale.get_scaling_factor(expr) is None:
            iscale.set_scaling_factor(expr, 1)

    # loop through all Vars for more compact script
    # find any objects missing scaling factors and add scaling factors of 1
    for var in fs.component_data_objects(pyo.Var, descend_into=True):
        if iscale.get_scaling_factor(var) is None:
            iscale.set_scaling_factor(var, 1, overwrite=True)

    # catch some mole fraction variables that slipped through
    iscale.set_scaling_factor(fs.CPU_translator.properties_out[0.0].mole_frac_comp, 1e2)
    iscale.set_scaling_factor(fs.flash.control_volume.properties_in[0.0].mole_frac_comp, 1e2)
    iscale.set_scaling_factor(fs.flash.control_volume.properties_out[0.0].mole_frac_comp, 1e2)

    # correct lower bounds on mole fractions that default to 1e-20
    for var in fs.component_data_objects(pyo.Var, descend_into=True):
        if '.mole_frac_comp' in var.name and var.lb == 1e-20:
            var.setlb(0)
            if var.value == 0:
                var.set_value(1e-10, skip_validation=True)


def get_solver():
    use_idaes_solver_configuration_defaults()
    idaes.cfg.ipopt["options"]["nlp_scaling_method"] = "user-scaling"
    idaes.cfg.ipopt["options"]["tol"] = 1e-7
    # due to a lot of component mole fractions being on their lower bound of 0
    # bound push result in much longer solve times, so set it low.
    idaes.cfg.ipopt["options"]["bound_push"] = 1e-12
    idaes.cfg.ipopt["options"]["linear_solver"] = "ma27"
    idaes.cfg.ipopt["options"]["max_iter"] = 200
    idaes.cfg.ipopt["options"]["ma27_pivtol"] = 1e-3

    return pyo.SolverFactory("ipopt")


def tags_inputs_opt_vars(fs):
    tags = iutil.ModelTagGroup()

    # Optimization variables
    tags["soec_outlet_o2_frac"] = iutil.ModelTag(
        expr=fs.soec_stack.oxygen_outlet.mole_frac_comp[0, "O2"],
        format_string="{:.3f}",
        display_units=None,
        doc="O2 side outlet O2 mole fraction",
    )
    tags["air_blower_flow"] = iutil.ModelTag(
        expr=fs.air_blower.inlet.flow_mol[0],
        format_string="{:.3f}",
        display_units=None,
        doc="Air blower flow (provides air to soec air side)",
    )
    tags["combustor_temperature"] = iutil.ModelTag(
        expr=fs.cmb.outlet.temperature[0],
        format_string="{:.3f}",
        display_units=pyo.units.K,
        doc="Combustor temperature",
    )
    tags["preheat_fg_split_to_oxygen"] = iutil.ModelTag(
        expr=fs.preheat_split.split_fraction[0, "oxygen"],
        format_string="{:.3f}",
        display_units=None,
        doc="Split frac. of soec air to air preheater, rest goes to NG heater",
    )
    tags["soec_h2_split_to_product"] = iutil.ModelTag(
        expr=fs.spltf1.split_fraction[0, "out"],
        format_string="{:.3f}",
        display_units=None,
        doc="Split frac. of soec h2 to product, rest goes to recycle",
    )
    tags["oxygen_preheater_delta_T_in"] = iutil.ModelTag(
        expr=fs.oxygen_preheater.delta_temperature_in[0],
        format_string="{:.3f}",
        display_units=pyo.units.K,
        doc="Air preheater inlet approach temperature",
    )
    tags["ng_preheater_delta_T_in"] = iutil.ModelTag(
        expr=fs.ng_preheater.delta_temperature_in[0],
        format_string="{:.3f}",
        display_units=pyo.units.K,
        doc="NG preheater inlet approach temperature",
    )
    tags["air_preheater_1_delta_T_in"] = iutil.ModelTag(
        expr=fs.air_preheater_1.delta_temperature_in[0],
        format_string="{:.3f}",
        display_units=pyo.units.K,
        doc="air_preheater_1 inlet approach temperature",
    )
    tags["air_preheater_2_delta_T_in"] = iutil.ModelTag(
        expr=fs.air_preheater_2.delta_temperature_in[0],
        format_string="{:.3f}",
        display_units=pyo.units.K,
        doc="air_preheater_2 inlet approach temperature",
    )
    tags["soc_cell_potential"] = iutil.ModelTag(
        expr=fs.soec_stack.solid_oxide_cell.potential[0],
        format_string="{:.4f}",
        display_units=pyo.units.volts,
        doc="soc cell potential",
    )

    # Input variables
    tags["condenser_outlet_temperature"] = iutil.ModelTag(
        expr=fs.condenser.outlet.temperature[0],
        format_string="{:.3f}",
        display_units=pyo.units.K,
        doc="Condenser outlet temperature (controls CO2 product purity from CPU)",
    )
    tags["hydrogen_product_rate"] = iutil.ModelTag(
        expr=fs.hydrogen_product_rate[0],
        format_string="{:.3f}",
        display_units=pyo.units.kmol / pyo.units.s,
        doc="Rate of hydrogen production",
    )
    tags["n_cells"] = iutil.ModelTag(
        expr=fs.soec_stack.number_cells,
        format_string="{:,.0f}",
        display_units=None,
        doc="Number of SOEC cells",
    )
    tags["feed_water_flow"] = iutil.ModelTag(
        expr=fs.aux_boiler_feed_pump.inlet.flow_mol[0],
        format_string="{:.3f}",
        display_units=None,
        doc="Feed water flow (provides steam to soec fuel side)",
    )
    tags["sweep_air_flow"] = iutil.ModelTag(
        expr=fs.air_compressor_s1.inlet.flow_mol[0],
        format_string="{:.3f}",
        display_units=None,
        doc="Air flow to soec air side",
    )

    fs.tag_input = tags


def tags_for_pfd(fs):
    tag_group = iutil.ModelTagGroup()
    streams = tables.arcs_to_stream_dict(
        fs,
        descend_into=False,
        additional={
            "bng00": fs.ng_preheater.tube_inlet,
            "ba00": fs.air_compressor_s1.inlet,
            "a00": fs.air_blower.inlet,
            "s00": fs.aux_boiler_feed_pump.inlet,
            "out01": fs.ASU.N2_outlet,
            "out02": fs.HRSG_2.outlet,
            "out03": fs.HRSG_3.outlet,
            "out08": fs.hcmp04.outlet,
        },
    )
    stream_states = tables.stream_states_dict(streams)

    for i, s in stream_states.items():  # create the tags for stream quantities
        tag_group[f"{i}_Fmass"] = iutil.ModelTag(
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
        tag_group[f"{i}_T"] = iutil.ModelTag(
            doc=f"{i}: temperature",
            expr=s.temperature,
            format_string="{:.2f}",
            display_units=pyo.units.K,
        )
        tag_group[f"{i}_P"] = iutil.ModelTag(
            doc=f"{i}: pressure",
            expr=s.pressure,
            format_string="{:.1f}",
            display_units=pyo.units.kPa,
        )
        try:
            tag_group[f"{i}_vf"] = iutil.ModelTag(
                doc=f"{i}: vapor fraction",
                expr=100 * s.phase_frac["Vap"],
                format_string="{:.3f}",
                display_units="%",
            )
        except (KeyError, AttributeError):
            pass
        try:
            for c in s.mole_frac_comp:
                tag_group[f"{i}_y{c}"] = iutil.ModelTag(
                    doc=f"{i}: mole percent {c}",
                    expr=s.mole_frac_comp[c] * 100,
                    format_string="{:.3f}",
                    display_units="%",
                )
        except (KeyError, AttributeError):
            pass

    tag_group["soec_power_AC"] = iutil.ModelTag(
        expr=fs.soec_power_AC[0], format_string="{:.2f}", display_units=pyo.units.MW
    )
    tag_group["soec_power_DC"] = iutil.ModelTag(
        expr=fs.soec_power_DC[0], format_string="{:.2f}", display_units=pyo.units.MW
    )
    tag_group["soec_n_cells"] = iutil.ModelTag(
        expr=fs.soec_stack.number_cells, format_string="{:,.0f}", display_units=None
    )
    tag_group["E_cell"] = iutil.ModelTag(
        expr=fs.soec_stack.solid_oxide_cell.potential[0],
        format_string="{:.4f}",
        display_units=pyo.units.volts,
    )
    tag_group["current_density"] = iutil.ModelTag(
        doc="Average current density of SOEC",
        expr=fs.soec_stack.solid_oxide_cell.average_current_density[0],
        format_string="{:.0f}",
        display_units=pyo.units.A / pyo.units.m ** 2,
    )
    tag_group["h2_product_rate_mass"] = iutil.ModelTag(
        expr=fs.h2_product_rate_mass[0],
        format_string="{:.3f}",
        display_units=pyo.units.kg / pyo.units.s,
    )
    tag_group["co2_product_rate"] = iutil.ModelTag(
        expr=fs.CPU.pureco2.flow_mol[0],
        format_string="{:.3f}",
        display_units=pyo.units.kmol / pyo.units.s,
    )
    tag_group["co2_product_rate_mass"] = iutil.ModelTag(
        expr=fs.CO2_captured[0],
        format_string="{:.3f}",
        display_units=pyo.units.kg / pyo.units.s,
    )
    tag_group["net_power"] = iutil.ModelTag(
        expr=fs.net_power[0], format_string="{:.3f}", display_units=pyo.units.MW,
    )
    tag_group["net_power_per_mass_h2"] = iutil.ModelTag(
        expr=fs.net_power_per_mass_h2[0],
        format_string="{:.3f}",
        display_units=pyo.units.MWh / pyo.units.kg,
    )
    tag_group["h2_compressor_power"] = iutil.ModelTag(
        expr=fs.h2_compressor_power[0],
        format_string="{:.2f}",
        display_units=pyo.units.MW,
    )
    tag_group["feed_pump_power"] = iutil.ModelTag(
        expr=fs.aux_boiler_feed_pump.control_volume.work[0],
        format_string="{:.4f}",
        display_units=pyo.units.MW,
    )
    tag_group["fuel_rate"] = iutil.ModelTag(
        expr=fs.ng_preheater.tube.properties_in[0].flow_mol,
        format_string="{:.3f}",
        display_units=pyo.units.kmol / pyo.units.s,
    )
    tag_group["fuel_rate_mass"] = iutil.ModelTag(
        expr=fs.ng_preheater.tube.properties_in[0].flow_mass,
        format_string="{:.3f}",
        display_units=pyo.units.kg / pyo.units.s,
    )
    tag_group["feed_h2_frac"] = iutil.ModelTag(
        expr=fs.soec_stack.fuel_inlet.mole_frac_comp[0, "H2"],
        format_string="{:.3f}",
        display_units=None,
        doc="H2 side inlet H2 mole frac (from recycle)",
    )
    tag_group["preheat_fg_split_to_oxygen"] = iutil.ModelTag(
        expr=fs.preheat_split.split_fraction[0, "oxygen"],
        format_string="{:.3f}",
        display_units=None,
        doc="Split frac. of soec air to air preheater, rest goes to NG heater",
    )

    tag_group["status"] = iutil.ModelTag(expr=None, format_string="{}")
    fs.tag_pfd = tag_group


def display_input_tags(fs):
    # this is special for this model.  The input tags are not indexed
    print("")
    for key, tag in fs.tag_input.items():
        print(key)
        print(f"    {tag.doc}")
        print(f"    display units: {tag._display_units}")
        print(f"    native units: {pyo.units.get_units(tag.expression)}")
        print(f"    value {tag}, fixed: {tag.expression.fixed}")
        print("")


def stream_tables(fs):
    # creates and returns a dataframe of the stream table for the model
    streams = tables.arcs_to_stream_dict(
        fs,
        descend_into=False,
        additional={
            "bng00": fs.ng_preheater.tube_inlet,
            "ba00": fs.air_compressor_s1.inlet,
            "a00": fs.air_blower.inlet,
            "s00": fs.aux_boiler_feed_pump.inlet,
            "out01": fs.ASU.N2_outlet,
            "out02": fs.HRSG_2.outlet,
            "out03": fs.HRSG_3.outlet,
            "out08": fs.hcmp04.outlet,
        },
    )

    sd = tables.stream_states_dict(streams, 0)
    sdf = tables.generate_table(
        blocks=sd,
        attributes=[
            "flow_mass",
            "flow_mol",
            "flow_vol",
            "temperature",
            "pressure",
            "vapor_frac",
            ("mole_frac_comp", "Ar"),
            ("mole_frac_comp", "CO"),
            ("mole_frac_comp", "CO2"),
            ("mole_frac_comp", "H2"),
            ("mole_frac_comp", "H2O"),
            ("mole_frac_comp", "N2"),
            ("mole_frac_comp", "O2"),
            ("mole_frac_comp", "CH4"),
            ("mole_frac_comp", "C2H6"),
            ("mole_frac_comp", "C3H8"),
            ("mole_frac_comp", "C4H10"),
        ],
        heading=[
            "flow_mass, kg/s",
            "flow_mol, mol/s",
            "flow_vol, m**3/s",
            "temperature, K",
            "pressure, Pa",
            "vapor_frac",
            "mole_frac_Ar",
            "mole_frac_CO",
            "mole_frac_CO2",
            "mole_frac_H2",
            "mole_frac_H2O",
            "mole_frac_N2",
            "mole_frac_O2",
            "mole_frac_CH4",
            "mole_frac_C2H6",
            "mole_frac_C3H8",
            "mole_frac_C4H10",
        ],
        exception=False,
    )

    sdf.sort_index(inplace=True)

    return sdf


def write_pfd_results(m, filename, infilename=None):
    """
    Write simulation results in a template PFD in svg format and save as
    filename.

    Args:
        filename: (str) file name for output
        tags: (dict) tag keys and expression values
        tag_format: (dict) tag keys and format string values
        infilename: input file name, if you want to use an alternative diagram

    Returns:
        None
    """
    if infilename is None:
        infilename = os.path.join(this_file_dir(), "rsofc_soec_mode_template.svg")
    with open(infilename, "r") as f:
        iutil.svg_tag(svg=f, tag_group=m.soec_fs.tag_pfd, outfile=filename)


def base_case_simulation(fs, solver):
    # The base_case_simulation function simulates the model for the
    # for the base case H2 production of 2.5 kmol/s or 5 kg/s.
    # See the base_case_optimization function for the optimization of the base case
    fs.hydrogen_product_rate.fix(2500)  # 2500 mol/s
    fs.aux_boiler_feed_pump.inlet.flow_mol.unfix()

    solver.solve(
        fs,
        tee=True,
        options={
            "max_iter": 200,
            "tol": 1e-7,
            "bound_push": 1e-12,
            "linear_solver": "ma27",
            "nlp_scaling_method": "user-scaling",
        },
        symbolic_solver_labels=True,
    )


def base_case_optimization(m, solver):
    """

    Parameters
    ----------
    fs : rsofc_soec flowsheet object.

    Returns: None
    -------
    This function optimizes the rsofc_soec model for the base case
    production rate of 5 kg/s of Hydrogen.
    See the base_case_simulation function for the simulation of the base case

    """

    # Deactivate outlet combustor temperature and set bounds
    m.soec_fs.cmb_temperature_eqn.deactivate()
    m.soec_fs.cmb.outlet.temperature.setlb(1100)
    m.soec_fs.cmb.outlet.temperature.setub(2000)

    m.soec_fs.air_preheater_1.delta_temperature_in.unfix()  # fixed in initialize
    m.soec_fs.air_preheater_1.delta_temperature_in.setlb(10)

    m.soec_fs.air_preheater_2.delta_temperature_out.unfix()  # This isn't fixed in the simulation but spec to avoid violation
    m.soec_fs.air_preheater_2.delta_temperature_out.setlb(10)

    m.soec_fs.oxygen_preheater.delta_temperature_in.unfix()  # fixed in initialize
    m.soec_fs.oxygen_preheater.delta_temperature_in.setlb(10)

    m.soec_fs.ng_preheater.delta_temperature_in.unfix()  # fixed in initialize
    m.soec_fs.ng_preheater.delta_temperature_in.setlb(10)

    # Unfix tube outlet temp of air_preheater 2 but keep it below 1023.15 K
    m.soec_fs.air_preheater_2.tube_outlet.temperature.unfix()
    m.soec_fs.air_preheater_2.tube_outlet.temperature.setub(1023.15)

    # Unfix fuel inlet temperature related constraints and set upper bounds
    m.soec_fs.fuel_recycle_heater.outlet.temperature.unfix()

    @m.soec_fs.Constraint(m.soec_fs.time)
    def fuel_recycle_heater_temperature_eqn(b, t):
        return (
            b.fuel_recycle_heater.outlet.temperature[t] == b.soec_steam_temperature[t]
        )

    m.soec_fs.soec_steam_temperature.unfix()
    m.soec_fs.soec_steam_temperature.setub(1023.15)

    # excess oxygen constraint
    m.soec_fs.excess_oxygen.unfix()
    m.soec_fs.excess_oxygen.setlb(1.01)
    m.soec_fs.excess_oxygen.setub(1.2)

    m.soec_fs.CPU.pureco2.flow_mol.setlb(0)
    m.soec_fs.CPU.water.flow_mol.setlb(0)
    m.soec_fs.CPU.vent.flow_mol.setlb(0)

    # CO2 capture efficiency (> 98 %)
    m.soec_fs.CO2_capture_efficiency_inequality_constraint = pyo.Constraint(
        expr=1e2 * m.soec_fs.CO2_capture_efficiency[0] >= 1e2 * 0.98
    )

    m.soec_fs.condenser.outlet.temperature.unfix()

    #############################
    # Optimization #
    #############################

    m.soec_fs.tag_input["hydrogen_product_rate"].fix(
        float(2.50) * pyo.units.kmol / pyo.units.s
    )
    print(f"Hydrogen product rate {m.soec_fs.tag_input['hydrogen_product_rate']}.")
    m.soec_fs.aux_boiler_feed_pump.inlet.flow_mol.unfix()  # mol/s
    m.soec_fs.aux_boiler_feed_pump.inlet.flow_mol.setlb(100)
    m.soec_fs.aux_boiler_feed_pump.inlet.flow_mol.setub(8000)

    # Vary air_blower.inlet such that O2 mole frac is less than 0.35
    m.soec_fs.air_blower.inlet.flow_mol.unfix()  # mol/s
    m.soec_fs.air_blower.inlet.flow_mol.setlb(100)
    m.soec_fs.air_blower.inlet.flow_mol.setub(8000)
    m.soec_fs.soec_stack.oxygen_outlet.mole_frac_comp[0, "O2"].unfix()
    m.soec_fs.sweep_constraint = pyo.Constraint(
        expr=1e2 * m.soec_fs.soec_stack.oxygen_outlet.mole_frac_comp[0, "O2"]
        <= 1e2 * 0.35
    )

    # This allows fuel recycle flowrate to vary
    # Single pass conversion set to be > 0.50
    m.soec_fs.spltf1.split_fraction[:, "out"].unfix()
    m.soec_fs.spltf1.split_fraction[:, "out"].setlb(0.5)
    m.soec_fs.spltf1.split_fraction[:, "out"].setub(0.98)
    m.soec_fs.single_pass_water_conversion_constraint = pyo.Constraint(
        expr=1e2 * m.soec_fs.soec_single_pass_water_conversion[0] >= 1e2 * 0.50
    )

    # Outlet H2O mole fraction from the fuel side should be > 0.20
    m.soec_fs.soec_outlet_h2o_constraint = pyo.Constraint(
        expr=1e3 * m.soec_fs.spltf1.inlet.mole_frac_comp[0, "H2O"] >= 1e3 * 0.20
    )

    # Vary split ratio of preheater flue gas split going to ng/o2 preheaters
    m.soec_fs.tag_input["preheat_fg_split_to_oxygen"].unfix()  # optimization
    m.soec_fs.tag_input["preheat_fg_split_to_oxygen"].setlb(0.30)
    m.soec_fs.tag_input["preheat_fg_split_to_oxygen"].setub(0.99)

    # Average current density limitation constraint
    @m.soec_fs.Constraint(m.soec_fs.time)
    def average_current_density_constraint(b, t):
        return (
            m.soec_fs.soec_stack.solid_oxide_cell.average_current_density[0] / 1000
            >= -8
        )

    # Unfix cell potential [cell voltage] (optimization dof)
    # However ensure that it doesn't stray too far above the thermoneutral
    # point by constraining the outlet fuel/sweep temp from the soec < 1030 K
    m.soec_fs.soec_stack.solid_oxide_cell.potential.unfix()
    m.soec_fs.soec_stack.solid_oxide_cell.potential.setlb(0.50)
    m.soec_fs.soec_stack.solid_oxide_cell.potential.setub(2.40)

    # soec_stack temperature constraints
    m.soec_fs.oxygen_outlet_temperature_constraint = pyo.Constraint(
        expr=m.soec_fs.soec_stack.oxygen_outlet.temperature[0] <= 1030.15
    )
    m.soec_fs.fuel_outlet_temperature_constraint = pyo.Constraint(
        expr=m.soec_fs.soec_stack.fuel_outlet.temperature[0] <= 1030.15
    )

    # Ensure that the temperature gradient across the soec is less than 40K
    # This is set for the outlets and inlets, and air/fuel side
    m.soec_fs.soec_outlet_temperature_constraint = pyo.Constraint(
        expr=(
            (
                m.soec_fs.soec_stack.oxygen_outlet.temperature[0]
                - m.soec_fs.soec_stack.fuel_outlet.temperature[0]
            )
            ** 2
            / 100
            <= 16
        )
    )
    m.soec_fs.soec_inlet_temperature_constraint = pyo.Constraint(
        expr=(
            (
                m.soec_fs.soec_stack.oxygen_inlet.temperature[0]
                - m.soec_fs.soec_stack.fuel_inlet.temperature[0]
            )
            ** 2
            / 100
            <= 16
        )
    )
    m.soec_fs.soec_oxygen_side_DT_constraint = pyo.Constraint(
        expr=(
            (
                m.soec_fs.soec_stack.oxygen_outlet.temperature[0]
                - m.soec_fs.soec_stack.oxygen_inlet.temperature[0]
            )
            ** 2
            / 100
            <= 16
        )
    )
    m.soec_fs.soec_fuel_side_DT_constraint = pyo.Constraint(
        expr=(
            (
                m.soec_fs.soec_stack.fuel_outlet.temperature[0]
                - m.soec_fs.soec_stack.fuel_inlet.temperature[0]
            )
            ** 2
            / 100
            <= 16
        )
    )

    m.soec_fs.obj = pyo.Objective(
        expr=1e2 * m.soec_fs.costing.total_variable_OM_cost[0]
        / m.soec_fs.h2_product_rate_mass[0]
    )

    options = {
        "max_iter": 500,
        "tol": 1e-4,
        "bound_push": 1e-5,
        "linear_solver": "ma57",
        "ma57_pivtol": 1e-5,
        "ma57_pivtolmax": 0.1,
        "OF_ma57_automatic_scaling": "yes",
    }
    solver.solve(m.soec_fs, tee=True, options=options, symbolic_solver_labels=True)


def results_table_dataframe(result_variables):
    # This is special for this model
    # Input: result_variables (list of summary results of the process)
    # Returns: a dataframe of results in a table form

    variable_name = []
    variable_value = []
    variable_units = []

    # Populate results table from results_variables list
    for var in result_variables:
        variable_name.append(var[0].name)  # make descriptive Var names and update to var.doc
        variable_value.append(var[0].value)
        variable_units.append(pyo.units.get_units(var[0]))

    results_table_dict = {}
    results_table_dict["Variable"] = variable_name
    results_table_dict["Value"] = variable_value
    results_table_dict["Units"] = variable_units

    # Make a panda table of the results and format values
    results_table = pd.DataFrame(results_table_dict)
    results_table.loc[:, "Value"] = results_table["Value"].map("{:.2f}".format)
    results_table = results_table.to_string(index=False)

    return results_table


def optimize_model(fs):
    """

    Parameters
    ----------
    fs : rsofc_soec flowsheet object.

    Returns: None
    -------
    This function optimizes the rsofc_soec model for different H2 production rates.

    """

    # Deactivate outlet combustor temperature and set bounds
    fs.cmb_temperature_eqn.deactivate()
    fs.cmb.outlet.temperature.setlb(1100)
    fs.cmb.outlet.temperature.setub(2000)

    # Unfix delta_temperature at heat exchanger pinch points and set bounds
    fs.air_preheater_1.delta_temperature_in.unfix()
    fs.air_preheater_1.delta_temperature_in.setlb(10)

    fs.air_preheater_2.delta_temperature_out.unfix()  # This isn't fixed in the simulation but spec to avoid violation
    fs.air_preheater_2.delta_temperature_out.setlb(10)

    fs.oxygen_preheater.delta_temperature_in.unfix()  # fixed in initialize
    fs.oxygen_preheater.delta_temperature_in.setlb(10)

    fs.ng_preheater.delta_temperature_in.unfix()  # fixed in initialize
    fs.ng_preheater.delta_temperature_in.setlb(10)

    # Unfix tube outlet temp of air_preheater 2 but keep it below 1023.15 K
    fs.air_preheater_2.tube_outlet.temperature.unfix()
    fs.air_preheater_2.tube_outlet.temperature.setub(1023.15)

    # Unfix fuel inlet temperature related constraints and set upper bounds
    fs.fuel_recycle_heater.outlet.temperature.unfix()

    @fs.Constraint(fs.time)
    def fuel_recycle_heater_temperature_eqn(b, t):
        return (
            b.fuel_recycle_heater.outlet.temperature[t] == b.soec_steam_temperature[t]
        )

    fs.soec_steam_temperature.unfix()
    fs.soec_steam_temperature.setub(1023.15)

    # excess oxygen constraint
    fs.excess_oxygen.unfix()
    fs.excess_oxygen.setlb(1.01)
    fs.excess_oxygen.setub(1.2)

    #############################
    # Optimization #
    #############################

    fs.tag_input["hydrogen_product_rate"].fix(
        float(2.50) * pyo.units.kmol / pyo.units.s
    )
    print(f"Hydrogen product rate {fs.tag_input['hydrogen_product_rate']}.")
    fs.aux_boiler_feed_pump.inlet.flow_mol.unfix()  # mol/s
    fs.aux_boiler_feed_pump.inlet.flow_mol.setlb(1000)
    fs.aux_boiler_feed_pump.inlet.flow_mol.setub(7000)

    # Vary air_blower.inlet such that O2 mole frac is less than 0.35
    fs.air_blower.inlet.flow_mol.unfix()  # mol/s
    fs.air_blower.inlet.flow_mol.setlb(1000)
    fs.air_blower.inlet.flow_mol.setub(7000)
    fs.soec_stack.oxygen_outlet.mole_frac_comp[0, "O2"].unfix
    fs.sweep_constraint = pyo.Constraint(
        expr=1e2 * fs.soec_stack.oxygen_outlet.mole_frac_comp[0, "O2"] <= 1e2 * 0.35
    )

    # This Allows fuel recycle flowrate to vary
    # Single pass conversion set to be > 0.50
    fs.spltf1.split_fraction[:, "out"].unfix()
    fs.spltf1.split_fraction[:, "out"].setlb(0.5)
    fs.spltf1.split_fraction[:, "out"].setub(0.98)
    fs.single_pass_water_conversion_constraint = pyo.Constraint(
        expr=1e2 * fs.soec_single_pass_water_conversion[0] >= 1e2 * 0.50
    )

    # Outlet H2O mole fraction from the fuel side should be > 0.20
    fs.soec_outlet_h2o_constraint = pyo.Constraint(
        expr=1e3 * fs.spltf1.inlet.mole_frac_comp[0, "H2O"] >= 1e3 * 0.20
    )

    # Vary split ratio of preheater flue gas split going to ng/o2 preheaters
    fs.tag_input["preheat_fg_split_to_oxygen"].unfix()  # optimization
    fs.tag_input["preheat_fg_split_to_oxygen"].setlb(0.30)
    fs.tag_input["preheat_fg_split_to_oxygen"].setub(0.99)

    # Average current density limitation constraint
    @fs.Constraint(fs.time)
    def average_current_density_constraint(b, t):
        return fs.soec_stack.solid_oxide_cell.average_current_density[0] / 1000 >= -8

    # Unfix cell potential [cell voltage] (optimization dof)
    # However ensure that it doesn't stray too far above the thermoneutral
    # point by constraining the outlet fuel/sweep temp from the soec < 1030 K
    fs.soec_stack.solid_oxide_cell.potential.unfix()
    fs.soec_stack.solid_oxide_cell.potential.setlb(1.00)
    fs.soec_stack.solid_oxide_cell.potential.setub(1.40)
    fs.oxygen_outlet_temperature_constraint = pyo.Constraint(
        expr=fs.soec_stack.oxygen_outlet.temperature[0] <= 1030.15
    )
    fs.fuel_outlet_temperature_constraint = pyo.Constraint(
        expr=fs.soec_stack.fuel_outlet.temperature[0] <= 1030.15
    )

    # Ensure that the temperature gradient across the soec is less than 40K
    # This is set for the outlets and inlets, and air/fuel side
    fs.soec_outlet_temperature_constraint = pyo.Constraint(
        expr=(
            (
                fs.soec_stack.oxygen_outlet.temperature[0]
                - fs.soec_stack.fuel_outlet.temperature[0]
            )
            ** 2
            / 100
            <= 16
        )
    )
    fs.soec_inlet_temperature_constraint = pyo.Constraint(
        expr=(
            (
                fs.soec_stack.oxygen_inlet.temperature[0]
                - fs.soec_stack.fuel_inlet.temperature[0]
            )
            ** 2
            / 100
            <= 16
        )
    )
    fs.soec_oxygen_side_DT_constraint = pyo.Constraint(
        expr=(
            (
                fs.soec_stack.oxygen_outlet.temperature[0]
                - fs.soec_stack.oxygen_inlet.temperature[0]
            )
            ** 2
            / 100
            <= 16
        )
    )
    fs.soec_fuel_side_DT_constraint = pyo.Constraint(
        expr=(
            (
                fs.soec_stack.fuel_outlet.temperature[0]
                - fs.soec_stack.fuel_inlet.temperature[0]
            )
            ** 2
            / 100
            <= 16
        )
    )

    fs.obj = pyo.Objective(expr=1e2 * fs.costing.total_variable_OM_cost[0]
                           / fs.h2_product_rate_mass[0])

    options = {
        "max_iter": 150,
        "tol": 1e-4,
        "bound_push": 1e-5,
        "linear_solver": "ma57",
        "ma57_pivtol": 1e-5,
        "ma57_pivtolmax": 0.1,
        "OF_ma57_automatic_scaling": "yes",
    }

    # Additional tags for variable O&M costs
    fs.tag_pfd["total_variable_OM_cost"] = iutil.ModelTag(
        expr=fs.costing.total_variable_OM_cost[0]
        / pyo.units.convert(fs.h2_product_rate_mass[0],
                            pyo.units.kg/pyo.units.a),
        format_string="{:.3f}",
        display_units=pyo.units.MUSD_2018 / pyo.units.kg,
        doc="Total variable O&M cost $MM/kg hydrogen",
    )

    fs.tag_pfd["electricity_variable_OM_costs"] = iutil.ModelTag(
        expr=fs.costing.variable_operating_costs[0, "electricity"]
        / pyo.units.convert(fs.h2_product_rate_mass[0],
                            pyo.units.kg/pyo.units.a),
        format_string="{:.3f}",
        display_units=pyo.units.MUSD_2018 / pyo.units.kg,
        doc="Electricity variable O&M cost $MM/kg hydrogen",
    )

    fs.tag_pfd["natural_gas_variable_OM_costs"] = iutil.ModelTag(
        expr=fs.costing.variable_operating_costs[0, "natural_gas"]
        / pyo.units.convert(fs.h2_product_rate_mass[0],
                            pyo.units.kg/pyo.units.a),
        format_string="{:.3f}",
        display_units=pyo.units.MUSD_2018 / pyo.units.kg,
        doc="Natural gas variable O&M cost $MM/kg hydrogen",
    )

    fs.tag_pfd["water_variable_OM_costs"] = iutil.ModelTag(
        expr=fs.costing.variable_operating_costs[0, "water"]
        / pyo.units.convert(fs.h2_product_rate_mass[0],
                            pyo.units.kg/pyo.units.a),
        format_string="{:.3f}",
        display_units=pyo.units.MUSD_2018 / pyo.units.kg,
        doc="Water variable O&M cost $MM/kg hydrogen",
    )

    fs.tag_pfd["water_treatment_chemicals_OM_costs"] = iutil.ModelTag(
        expr=fs.costing.variable_operating_costs[0, "water_treatment_chemicals"]
        / pyo.units.convert(fs.h2_product_rate_mass[0],
                            pyo.units.kg/pyo.units.a),
        format_string="{:.3f}",
        display_units=pyo.units.MUSD_2018 / pyo.units.kg,
        doc="Water treatment chemicals O&M cost $MM/kg hydrogen",
    )

    cols_input = ("hydrogen_product_rate",)
    cols_pfd = (
        "status",
        "total_variable_OM_cost",
        "electricity_variable_OM_costs",
        "natural_gas_variable_OM_costs",
        "water_variable_OM_costs",
        "water_treatment_chemicals_OM_costs",
        "soec_n_cells",
        "h2_product_rate_mass",
        "fuel_rate",
        "fuel_rate_mass",
        "co2_product_rate",
        "co2_product_rate_mass",
        "soec_power_AC",
        "soec_power_DC",
        "h2_compressor_power",
        "feed_pump_power",
        "net_power",
        "net_power_per_mass_h2",
        "feed_h2_frac",
        "preheat_fg_split_to_oxygen",
    )

    head_1 = fs.tag_input.table_heading(tags=cols_input, units=True)
    head_2 = fs.tag_pfd.table_heading(tags=cols_pfd, units=True)
    with open("opt_res_soec.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(head_1 + head_2)
    for h in np.linspace(2.5, 0.625, 16):
        fs.tag_input["hydrogen_product_rate"].fix(
            float(h) * pyo.units.kmol / pyo.units.s
        )
        print()
        print()
        print(f"Hydrogen product rate {fs.tag_input['hydrogen_product_rate']}.")
        print(f"Number of soec cells {fs.tag_input['n_cells']}.")
        res = solver.solve(fs, tee=True, symbolic_solver_labels=True, options=options)

        stat = idaeslog.condition(res)
        fs.tag_pfd["status"].set(stat)
        row_1 = fs.tag_input.table_row(tags=cols_input, numeric=True)
        row_2 = fs.tag_pfd.table_row(tags=cols_pfd, numeric=True)
        with open("opt_res_soec.csv", "a", newline="") as f:
            w = csv.writer(f)
            w.writerow(row_1 + row_2)

        # write_pfd_results(
        #     m, f"rsofc_soec_{fs.tag_input['hydrogen_product_rate'].display(units=False)}.svg"
        # )


def get_model(m=None, name="SOEC Module"):

    # json file for saving/loading initialized model
    init_fname = "rsofc_soec_surrogate_init.json.gz"

    solver = get_solver()

    if os.path.exists(init_fname):
        # main plant
        add_flowsheet(m)
        add_properties(m.soec_fs)
        add_asu(m.soec_fs)
        add_preheater(m.soec_fs)
        add_soec_air_side_units(m.soec_fs)
        add_combustor(m.soec_fs)
        add_aux_boiler_steam(m.soec_fs)
        add_soec_unit(m.soec_fs)
        add_more_hx_connections(m.soec_fs)
        add_soec_inlet_mix(m.soec_fs)
        add_design_constraints(m.soec_fs)
        expand_arcs = pyo.TransformationFactory("network.expand_arcs")
        expand_arcs.apply_to(m.soec_fs)
        add_scaling(m.soec_fs)

        # balance of plant
        add_h2_compressor(m.soec_fs)
        add_hrsg_and_cpu(m.soec_fs)
        expand_arcs = pyo.TransformationFactory("network.expand_arcs")
        expand_arcs.apply_to(m.soec_fs)
        add_scaling_bop(m.soec_fs)

        # results
        add_result_constraints(m.soec_fs)

        # calculate all scaling factors
        set_missing_scaling_and_bounds(m.soec_fs)
        iscale.calculate_scaling_factors(m.soec_fs)

        # load model and results
        ms.from_json(m, fname=init_fname)

    else:
        # main plant
        add_flowsheet(m)
        add_properties(m.soec_fs)
        add_asu(m.soec_fs)
        add_preheater(m.soec_fs)
        add_soec_air_side_units(m.soec_fs)
        add_combustor(m.soec_fs)
        add_aux_boiler_steam(m.soec_fs)
        add_soec_unit(m.soec_fs)
        add_more_hx_connections(m.soec_fs)
        add_soec_inlet_mix(m.soec_fs)
        add_design_constraints(m.soec_fs)
        expand_arcs = pyo.TransformationFactory("network.expand_arcs")
        expand_arcs.apply_to(m.soec_fs)
        set_guess(m.soec_fs)
        set_inputs(m.soec_fs)
        add_scaling(m.soec_fs)
        iscale.scale_arc_constraints(m.soec_fs)
        initialize_plant(m.soec_fs, solver)

        # balance of plant
        add_h2_compressor(m.soec_fs)
        add_hrsg_and_cpu(m.soec_fs)
        expand_arcs = pyo.TransformationFactory("network.expand_arcs")
        expand_arcs.apply_to(m.soec_fs)
        add_scaling_bop(m.soec_fs)
        initialize_bop(m.soec_fs, solver)

        # results
        add_result_constraints(m.soec_fs)

        # calculate all scaling factors
        set_missing_scaling_and_bounds(m.soec_fs)
        iscale.calculate_scaling_factors(m.soec_fs)

        # solve for initial results
        initialize_results(m.soec_fs)

        # save model and results
        ms.to_json(m, fname=init_fname)

    return m, solver


if __name__ == "__main__":
    m = pyo.ConcreteModel()
    m, solver = get_model(m)

    tags_inputs_opt_vars(m.soec_fs)
    tags_for_pfd(m.soec_fs)

    # base_case_simulation(m.soec_fs, solver)  # solve for H2 prod. of 5 kg/s (2.5 kmol/s)
    rsofc_cost.get_rsofc_soec_variable_OM_costing(m.soec_fs)
    base_case_optimization(m, solver)  # 5 kg/s
    # uncomment to optimize model
    # optimize_model(m.soec_fs)


    # display_input_tags(m.soec_fs)
    write_pfd_results(m, "rsofc_soec_results.svg")

    # stream tables
    stream_table = stream_tables(m.soec_fs)
    # stream_table.to_csv("streams.csv")

    # Print results table
    result_variables = initialize_results(m.soec_fs)
    results_table = results_table_dataframe(result_variables)
    print(results_table)

    # uncomment to visualize flowsheet
    # m.soec_fs.visualize("rSOEC Flowsheet")
