#################################################################################
# The Institute for the Design of Advanced Energy Systems Integrated Platform
# Framework (IDAES IP) was produced under the DOE Institute for the
# Design of Advanced Energy Systems (IDAES), and is copyright (c) 2018-2021
# by the software owners: The Regents of the University of California, through
# Lawrence Berkeley National Laboratory,  National Technology & Engineering
# Solutions of Sandia, LLC, Carnegie Mellon University, West Virginia University
# Research Corporation, et al.  All rights reserved.
#
# Please see the files COPYRIGHT.md and LICENSE.md for full copyright and
# license information.
#################################################################################

__author__ = "Alex Noring"

import os
import numpy as np
import pandas as pd

import pyomo.environ as pyo
from pyomo.common.fileutils import this_file_dir
from pyomo.environ import units as pyunits
from pyomo.network import Arc
from pyomo.util.calc_var_value import calculate_variable_from_constraint
from pyomo.util.infeasible import log_infeasible_constraints

import idaes
from idaes.core import FlowsheetBlock
import idaes.core.plugins
from idaes.core.solvers import use_idaes_solver_configuration_defaults
import idaes.core.util as iutil
import idaes.core.util.initialization as iinit
import idaes.core.util.scaling as iscale
import idaes.core.util.tables as tables
from idaes.core.util.tags import svg_tag

from idaes.models.properties import iapws95
from idaes.models.properties.modular_properties.base.generic_property import (
    GenericParameterBlock)
from idaes.models.properties.modular_properties.base.generic_reaction import (
    GenericReactionParameterBlock)
import idaes.models.unit_models as gum  # generic unit models
from idaes.models.unit_models.heat_exchanger import (
    delta_temperature_underwood_callback,
)
from idaes.models.unit_models.pressure_changer import ThermodynamicAssumption
from idaes.models.unit_models.separator import SplittingType

from idaes.models_extra.power_generation.properties.natural_gas_PR import (
    get_prop,
    get_rxn,
    EosType
)
from idaes.models_extra.power_generation.unit_models.cpu import (
    CarbonProcessingUnit
)
from idaes.models_extra.power_generation.unit_models.helm import (
    HelmIsentropicCompressor
)
import idaes.models_extra.power_generation.unit_models.soc_submodels as soc


def add_properties(m):
    natural_gas_comps = [
        "CH4",
        "C2H6",
        "C3H8",
        "C4H10",
        "CO",
        "CO2",
        "H2",
        "H2O",
        "N2",
        "O2",
        "Ar"
    ]
    air_comps = [
        "CO2",
        "H2O",
        "N2",
        "O2",
        "Ar"
    ]
    h2_comps = [
        "H2",
        "H2O"
    ]
    m.rxns = {
        "c2h6_cmb": "C2H6",
        "c3h8_cmb": "C3H8",
        "c4h10_cmb": "C4H10",
        "ch4_cmb": "CH4",
        "co_cmb": "CO",
        "h2_cmb": "H2"
    }

    m.fs.cmb_props = GenericParameterBlock(
        **get_prop(natural_gas_comps, ["Vap"], eos=EosType.PR))

    m.fs.air_props = GenericParameterBlock(
        **get_prop(air_comps, ["Vap"], eos=EosType.PR))

    m.fs.flue_props = GenericParameterBlock(
        **get_prop(air_comps, ["Vap"], eos=EosType.PR))

    m.fs.flue_props_vle = GenericParameterBlock(
        **get_prop(air_comps, ["Vap", "Liq"], scaled=True))

    m.fs.h2_side_props = GenericParameterBlock(
        **get_prop(h2_comps, ["Vap"], eos=EosType.PR))

    m.fs.h2_side_props_vle = GenericParameterBlock(
        **get_prop(h2_comps, ["Vap", "Liq"], eos=EosType.PR, scaled=True))

    m.fs.h2_pure_props = GenericParameterBlock(
        **get_prop({"H2"}, ["Vap"], eos=EosType.PR))

    m.fs.steam_props = iapws95.Iapws95ParameterBlock()

    m.fs.rxn_props = GenericReactionParameterBlock(
        **get_rxn(m.fs.cmb_props, m.rxns))


def add_models(m):
    # asu unit models
    m.fs.asu_cmp01 = gum.PressureChanger(
        compressor=True,
        property_package=m.fs.air_props,
        thermodynamic_assumption=ThermodynamicAssumption.isentropic
    )
    m.fs.asu_ic01 = gum.Heater(
        property_package=m.fs.air_props,
        has_pressure_change=True
    )
    m.fs.asu_cmp02 = gum.PressureChanger(
        compressor=True,
        property_package=m.fs.air_props,
        thermodynamic_assumption=ThermodynamicAssumption.isentropic
    )
    m.fs.asu_ic02 = gum.Heater(
        property_package=m.fs.air_props,
        has_pressure_change=True
    )
    m.fs.asu_split = gum.Separator(
        outlet_list=["n2_outlet", "o2_outlet"],
        split_basis=SplittingType.componentFlow,
        property_package=m.fs.air_props
    )
    m.fs.asu_heat = gum.Heater(
        has_pressure_change=True,
        property_package=m.fs.air_props
    )
    m.fs.asu_translator = gum.Translator(
        outlet_state_defined=True,
        inlet_property_package=m.fs.air_props,
        outlet_property_package=m.fs.cmb_props
    )
    # oxycombustor unit models
    m.fs.oxycombustor_mix = gum.Mixer(
        inlet_list=["gas_inlet", "exhaust_inlet", "oxygen_inlet"],
        property_package=m.fs.cmb_props
    )
    m.fs.oxycombustor = gum.StoichiometricReactor(
        has_heat_of_reaction=False,
        has_heat_transfer=True,
        has_pressure_change=True,
        property_package=m.fs.cmb_props,
        reaction_package=m.fs.rxn_props
    )
    # flue gas pathway
    m.fs.flue_gas_translator = gum.Translator(
        outlet_state_defined=True,
        inlet_property_package=m.fs.cmb_props,
        outlet_property_package=m.fs.flue_props
    )
    m.fs.sweep_heater = gum.HeatExchanger(
        hot_side_name="shell",
        cold_side_name="tube",
        shell={"property_package": m.fs.flue_props},
        tube={"property_package": m.fs.air_props},
        delta_temperature_callback=delta_temperature_underwood_callback
    )
    m.fs.boiler = gum.HeatExchanger(
        hot_side_name="shell",
        cold_side_name="tube",
        shell={"property_package": m.fs.flue_props},
        tube={"property_package": m.fs.steam_props},
        delta_temperature_callback=delta_temperature_underwood_callback
    )
    m.fs.flue_gas_translator_2 = gum.Translator(
        outlet_state_defined=True,
        inlet_property_package=m.fs.flue_props,
        outlet_property_package=m.fs.flue_props_vle
    )
    m.fs.fg_flash = gum.Flash(
        has_heat_transfer=True,
        has_pressure_change=True,
        property_package=m.fs.flue_props_vle
    )
    m.fs.flue_gas_translator_3 = gum.Translator(
        outlet_state_defined=True,
        inlet_property_package=m.fs.flue_props_vle,
        outlet_property_package=m.fs.flue_props
    )
    m.fs.cpu = CarbonProcessingUnit()

    # water and steam pathway to H2 side of SOEC
    m.fs.bfw_pump = HelmIsentropicCompressor(
        property_package=m.fs.steam_props
    )
    m.fs.feed_hx = gum.HeatExchanger(
        hot_side_name="shell",
        cold_side_name="tube",
        shell={"property_package": m.fs.h2_side_props},
        tube={"property_package": m.fs.steam_props},
        delta_temperature_callback=delta_temperature_underwood_callback
    )
    m.fs.feed_translator = gum.Translator(
        inlet_property_package=m.fs.steam_props,
        outlet_property_package=m.fs.h2_side_props,
        outlet_state_defined=True
    )
    m.fs.feed_recycle_mix = gum.Mixer(
         property_package=m.fs.h2_side_props,
         inlet_list=["feed_inlet", "recycle_inlet"],
         momentum_mixing_type=gum.MomentumMixingType.none
    )
    m.fs.feed_heater = gum.Heater(
        property_package=m.fs.h2_side_props
    )
    m.fs.soec_module = soc.SolidOxideModuleSimple(
        solid_oxide_cell_config={
            "has_holdup": False,
            "control_volume_zfaces": np.linspace(0, 1, 11).tolist(),
            "control_volume_xfaces_fuel_electrode": [0.0, 1.0],
            "control_volume_xfaces_oxygen_electrode": [0.0, 1.0],
            "control_volume_xfaces_electrolyte": [0.0, 1.0],
            "fuel_component_list": m.fs.h2_side_props.component_list,
            "fuel_triple_phase_boundary_stoich_dict": {"H2": -0.5,
                                                       "H2O": 0.5,
                                                       "Vac": 0.5,
                                                       "O^2-": -0.5,
                                                       "e^-": 1},
            "inert_fuel_species_triple_phase_boundary": [],
            "oxygen_component_list": m.fs.air_props.component_list,
            "oxygen_triple_phase_boundary_stoich_dict": {"O2": -0.25,
                                                         "Vac": -0.5,
                                                         "O^2-": 0.5,
                                                         "e^-": -1},
            "inert_oxygen_species_triple_phase_boundary": ["N2", "Ar",
                                                           "CO2", "H2O"],
            "include_temperature_x_thermo": True,
            "include_contact_resistance": False,
        },
        fuel_property_package=m.fs.h2_side_props,
        oxygen_property_package=m.fs.air_props,
    )
    m.fs.feed_recycle_split = gum.Separator(
        property_package=m.fs.h2_side_props,
        outlet_list=["out", "recycle"]
    )
    m.fs.h2_condenser_translator = gum.Translator(
        inlet_property_package=m.fs.h2_side_props,
        outlet_property_package=m.fs.h2_side_props_vle,
        outlet_state_defined=True
    )
    m.fs.h2_condenser = gum.Flash(
        has_heat_transfer=True,
        has_pressure_change=False,
        property_package=m.fs.h2_side_props_vle
    )
    m.fs.dryer_translator = gum.Translator(
        inlet_property_package=m.fs.h2_side_props_vle,
        outlet_property_package=m.fs.h2_pure_props,
        outlet_state_defined=True
    )
    # H2 compressor train
    m.fs.cmp01 = gum.Compressor(
        property_package=m.fs.h2_pure_props
    )
    m.fs.ic01 = gum.Heater(
        property_package=m.fs.h2_pure_props
    )
    m.fs.cmp02 = gum.Compressor(
        property_package=m.fs.h2_pure_props
    )
    m.fs.ic02 = gum.Heater(
        property_package=m.fs.h2_pure_props
    )
    m.fs.cmp03 = gum.Compressor(
        property_package=m.fs.h2_pure_props
    )
    m.fs.ic03 = gum.Heater(
        property_package=m.fs.h2_pure_props
    )
    m.fs.cmp04 = gum.Compressor(
        property_package=m.fs.h2_pure_props
    )
    # air sweep
    m.fs.sweep_compressor = gum.Compressor(
        property_package=m.fs.air_props
    )
    m.fs.sweep_hx = gum.HeatExchanger(
        hot_side_name="shell",
        cold_side_name="tube",
        shell={"property_package": m.fs.air_props},
        tube={"property_package": m.fs.air_props},
    )
    m.fs.sweep_turbine = gum.Turbine(
        property_package=m.fs.air_props
    )


def add_arcs(m):
    m.fs.asu01 = Arc(
        source=m.fs.asu_cmp01.outlet,
        destination=m.fs.asu_ic01.inlet)

    m.fs.asu02 = Arc(
        source=m.fs.asu_ic01.outlet,
        destination=m.fs.asu_cmp02.inlet)

    m.fs.asu03 = Arc(
        source=m.fs.asu_cmp02.outlet,
        destination=m.fs.asu_ic02.inlet)

    m.fs.asu04 = Arc(
        source=m.fs.asu_ic02.outlet,
        destination=m.fs.asu_split.inlet)

    m.fs.asu05 = Arc(
        source=m.fs.asu_split.o2_outlet,
        destination=m.fs.asu_heat.inlet)

    m.fs.to_asu_translator = Arc(
        source=m.fs.asu_heat.outlet,
        destination=m.fs.asu_translator.inlet)

    m.fs.oxy01 = Arc(
        source=m.fs.asu_translator.outlet,
        destination=m.fs.oxycombustor_mix.oxygen_inlet)

    m.fs.oxy02 = Arc(
        source=m.fs.oxycombustor_mix.outlet,
        destination=m.fs.oxycombustor.inlet)

    m.fs.to_fg_translator = Arc(
        source=m.fs.oxycombustor.outlet,
        destination=m.fs.flue_gas_translator.inlet)

    m.fs.fg01 = Arc(
        source=m.fs.flue_gas_translator.outlet,
        destination=m.fs.sweep_heater.shell_inlet)

    m.fs.fg02 = Arc(
        source=m.fs.sweep_heater.shell_outlet,
        destination=m.fs.boiler.shell_inlet)

    m.fs.to_fg_translator_2 = Arc(
        source=m.fs.boiler.shell_outlet,
        destination=m.fs.flue_gas_translator_2.inlet)

    m.fs.fg03 = Arc(
        source=m.fs.flue_gas_translator_2.outlet,
        destination=m.fs.fg_flash.inlet)

    m.fs.to_fg_translator_3 = Arc(
        source=m.fs.fg_flash.vap_outlet,
        destination=m.fs.flue_gas_translator_3.inlet)

    m.fs.fg04 = Arc(
        source=m.fs.flue_gas_translator_3.outlet,
        destination=m.fs.cpu.inlet)

    m.fs.w01 = Arc(
        source=m.fs.bfw_pump.outlet,
        destination=m.fs.boiler.tube_inlet)

    m.fs.w02 = Arc(
        source=m.fs.boiler.tube_outlet,
        destination=m.fs.feed_hx.tube_inlet)

    m.fs.to_feed_translator = Arc(
        source=m.fs.feed_hx.tube_outlet,
        destination=m.fs.feed_translator.inlet)

    m.fs.w03 = Arc(
        source=m.fs.feed_translator.outlet,
        destination=m.fs.feed_recycle_mix.feed_inlet)

    m.fs.h01 = Arc(
        source=m.fs.feed_recycle_mix.outlet,
        destination=m.fs.feed_heater.inlet)

    m.fs.h02 = Arc(
        source=m.fs.feed_heater.outlet,
        destination=m.fs.soec_module.fuel_inlet)

    m.fs.h03 = Arc(
        source=m.fs.soec_module.fuel_outlet,
        destination=m.fs.feed_recycle_split.inlet)

    m.fs.hr01 = Arc(
        source=m.fs.feed_recycle_split.recycle,
        destination=m.fs.feed_recycle_mix.recycle_inlet)

    m.fs.h04 = Arc(
        source=m.fs.feed_recycle_split.out,
        destination=m.fs.feed_hx.shell_inlet)

    m.fs.to_h2_condenser_translator = Arc(
        source=m.fs.feed_hx.shell_outlet,
        destination=m.fs.h2_condenser_translator.inlet)

    m.fs.h05 = Arc(
        source=m.fs.h2_condenser_translator.outlet,
        destination=m.fs.h2_condenser.inlet)

    m.fs.h06 = Arc(
        source=m.fs.h2_condenser.vap_outlet,
        destination=m.fs.dryer_translator.inlet)

    m.fs.h07 = Arc(
        source=m.fs.dryer_translator.outlet,
        destination=m.fs.cmp01.inlet)

    m.fs.h08 = Arc(
        source=m.fs.cmp01.outlet,
        destination=m.fs.ic01.inlet)

    m.fs.h09 = Arc(
        source=m.fs.ic01.outlet,
        destination=m.fs.cmp02.inlet)

    m.fs.h10 = Arc(
        source=m.fs.cmp02.outlet,
        destination=m.fs.ic02.inlet)

    m.fs.h11 = Arc(
        source=m.fs.ic02.outlet,
        destination=m.fs.cmp03.inlet)

    m.fs.h12 = Arc(
        source=m.fs.cmp03.outlet,
        destination=m.fs.ic03.inlet)

    m.fs.h13 = Arc(
        source=m.fs.ic03.outlet,
        destination=m.fs.cmp04.inlet)

    m.fs.swp01 = Arc(
        source=m.fs.sweep_compressor.outlet,
        destination=m.fs.sweep_hx.tube_inlet)

    m.fs.swp02 = Arc(
        source=m.fs.sweep_hx.tube_outlet,
        destination=m.fs.sweep_heater.tube_inlet)

    m.fs.swp03 = Arc(
        source=m.fs.sweep_heater.tube_outlet,
        destination=m.fs.soec_module.oxygen_inlet)

    m.fs.swp04 = Arc(
        source=m.fs.soec_module.oxygen_outlet,
        destination=m.fs.sweep_hx.shell_inlet)

    m.fs.swp05 = Arc(
        source=m.fs.sweep_hx.shell_outlet,
        destination=m.fs.sweep_turbine.inlet)

    pyo.TransformationFactory("network.expand_arcs").apply_to(m.fs)


def add_constraints(m):
    # To reduced complexity, this model uses surrogate equations to represent
    # the SOFC power island. The input variable is the SOFC AC power output
    # and the output variables are the flowrate, temperature, and composition
    # of the SOFC anode exhaust stream entering the oxycombustor.
    m.fs.sofc_power = pyo.Var(
        m.fs.time,
        initialize=680,
        bounds=(200, 680),
        units=pyunits.MW
    )

    @m.fs.Constraint(m.fs.time)
    def anode_exhaust_F(fs, t):
        return fs.oxycombustor_mix.exhaust_inlet.flow_mol[t] == (
            5.4282*fs.sofc_power[t] - 72.537
        )

    # significant change
    @m.fs.Constraint(m.fs.time)
    def anode_exhaust_T(fs, t):
        return fs.oxycombustor_mix.exhaust_inlet.temperature[t] == (
            -5.3702e-10*fs.sofc_power[t]**4 +
            1.1479e-6*fs.sofc_power[t]**3 -
            9.4658e-4*fs.sofc_power[t]**2 +
            3.7400e-1*fs.sofc_power[t] +
            829.05
        )

    @m.fs.Constraint(m.fs.time)
    def anode_exhaust_x_ch4(fs, t):
        return fs.oxycombustor_mix.exhaust_inlet.mole_frac_comp[t, "CH4"] == (
            -6.5697e-20*fs.sofc_power[t]**6 +
            1.7870e-16*fs.sofc_power[t]**5 -
            1.9533e-13*fs.sofc_power[t]**4 +
            1.0878e-10*fs.sofc_power[t]**3 -
            3.2039e-08*fs.sofc_power[t]**2 +
            4.6091e-06*fs.sofc_power[t] -
            2.2630e-04
        )

    @m.fs.Constraint(m.fs.time)
    def anode_exhaust_x_co(fs, t):
        return fs.oxycombustor_mix.exhaust_inlet.mole_frac_comp[t, "CO"] == (
            2.5526e-17*fs.sofc_power[t]**6 -
            7.0210e-14*fs.sofc_power[t]**5 +
            7.7885e-11*fs.sofc_power[t]**4 -
            4.4268e-08*fs.sofc_power[t]**3 +
            1.3439e-05*fs.sofc_power[t]**2 -
            2.0319e-03*fs.sofc_power[t] +
            1.7434e-01
        )

    @m.fs.Constraint(m.fs.time)
    def anode_exhaust_x_co2(fs, t):
        return fs.oxycombustor_mix.exhaust_inlet.mole_frac_comp[t, "CO2"] == (
            -2.5503e-17*fs.sofc_power[t]**6 +
            7.0149e-14*fs.sofc_power[t]**5 -
            7.7818e-11*fs.sofc_power[t]**4 +
            4.4230e-08*fs.sofc_power[t]**3 -
            1.3427e-05*fs.sofc_power[t]**2 +
            2.0303e-03*fs.sofc_power[t] +
            1.6582e-01
        )

    @m.fs.Constraint(m.fs.time)
    def anode_exhaust_x_h2(fs, t):
        return fs.oxycombustor_mix.exhaust_inlet.mole_frac_comp[t, "H2"] == (
            -2.5261e-17*fs.sofc_power[t]**6 +
            6.9488e-14*fs.sofc_power[t]**5 -
            7.7093e-11*fs.sofc_power[t]**4 +
            4.3825e-08*fs.sofc_power[t]**3 -
            1.3307e-05*fs.sofc_power[t]**2 +
            2.0128e-03*fs.sofc_power[t] +
            2.5867e-02
        )

    @m.fs.Constraint(m.fs.time)
    def anode_exhaust_x_n2(fs, t):
        return fs.oxycombustor_mix.exhaust_inlet.mole_frac_comp[t, "N2"] == (
            -8.0828e-22*fs.sofc_power[t]**6 +
            2.2077e-18*fs.sofc_power[t]**5 -
            2.4241e-15*fs.sofc_power[t]**4 +
            1.3575e-12*fs.sofc_power[t]**3 -
            4.0306e-10*fs.sofc_power[t]**2 +
            5.8862e-08*fs.sofc_power[t] +
            5.2190e-03
        )

    @m.fs.Constraint(m.fs.time)
    def anode_exhaust_mole_frac_sum(fs, t):
        return 1 == sum(fs.oxycombustor_mix.exhaust_inlet.mole_frac_comp[t, j]
                        for j in fs.cmb_props.component_list
                        )

    # oxycombustor constraints
    @m.fs.oxycombustor.Constraint(m.fs.time, m.rxns.keys())
    def reaction_extent(b, t, r):
        k = m.rxns[r]
        prp = b.control_volume.properties_in[t]
        stc = -m.fs.rxn_props.rate_reaction_stoichiometry[r, "Vap", k]
        extent = b.rate_reaction_extent[t, r]
        return extent == prp.flow_mol * prp.mole_frac_comp[k] / stc

    @m.fs.Constraint()
    def oxygen_flowrate(fs):
        XS = 1.09  # excess oxygen

        F_CH4 = (fs.oxycombustor.inlet.flow_mol[0] *
                 fs.oxycombustor.inlet.mole_frac_comp[(0, "CH4")])
        F_C2H6 = (fs.oxycombustor.inlet.flow_mol[0] *
                  fs.oxycombustor.inlet.mole_frac_comp[(0, "C2H6")])
        F_C3H8 = (fs.oxycombustor.inlet.flow_mol[0] *
                  fs.oxycombustor.inlet.mole_frac_comp[(0, "C3H8")])
        F_C4H10 = (fs.oxycombustor.inlet.flow_mol[0] *
                   fs.oxycombustor.inlet.mole_frac_comp[(0, "C4H10")])
        F_CO = (fs.oxycombustor.inlet.flow_mol[0] *
                fs.oxycombustor.inlet.mole_frac_comp[(0, "CO")])
        F_H2 = (fs.oxycombustor.inlet.flow_mol[0] *
                fs.oxycombustor.inlet.mole_frac_comp[(0, "H2")])

        O2_required = 0.5*F_CO + 0.5*F_H2 + 2*F_CH4 + 3.5*F_C2H6 + 5*F_C3H8 + 6.5*F_C4H10

        O2_fed = (fs.oxycombustor_mix.oxygen_inlet.flow_mol[0] *
                  fs.oxycombustor_mix.oxygen_inlet.mole_frac_comp[(0, "O2")])
        return O2_fed == XS*O2_required

    @m.fs.feed_recycle_mix.Constraint(m.fs.time)
    def pressure_equality_eqn(b, t):
        return b.mixed_state[t].pressure == b.feed_inlet_state[t].pressure

    m.fs.hydrogen_product_rate = pyo.Var(
        m.fs.time,
        initialize=5,
        bounds=(0, 6),
        units=pyo.units.kg / pyo.units.s,
    )

    @m.fs.Constraint(m.fs.time)
    def hydrogen_product_rate_eqn(b, t):
        return (
            b.hydrogen_product_rate[t] ==
            b.cmp04.control_volume.properties_out[0].flow_mass
        )

    m.fs.soec_single_pass_water_conversion = pyo.Var(
        m.fs.time,
        initialize=0.7,
        bounds=(0, 1)
    )

    @m.fs.Constraint(m.fs.time)
    def soec_single_pass_water_conversion_eqn(b, t):
        return b.soec_single_pass_water_conversion[t] == (
            (
                b.soec_module.solid_oxide_cell.fuel_channel.flow_mol_comp_outlet[t, "H2"]
                - b.soec_module.solid_oxide_cell.fuel_channel.flow_mol_comp_inlet[t, "H2"]
            )
            / b.soec_module.solid_oxide_cell.fuel_channel.flow_mol_comp_inlet[t, "H2O"]
        )

    # translator constraints
    def translator_F_rule(b, t):
        return b.inlet.flow_mol[t] == b.outlet.flow_mol[t]

    def translator_T_rule(b, t):
        return b.inlet.temperature[t] == b.outlet.temperature[t]

    def translator_P_rule(b, t):
        return b.inlet.pressure[t] == b.outlet.pressure[t]

    def translator_x_rule(b, t, j):
        inlet_comps = b.properties_in[0].component_list
        if j in inlet_comps:
            return b.inlet.mole_frac_comp[t, j] == b.outlet.mole_frac_comp[t, j]
        else:
            return b.outlet.mole_frac_comp[t, j] == 0

    translators = {m.fs.asu_translator,
                   m.fs.flue_gas_translator}

    for t in translators:

        t.F_eq = pyo.Constraint(m.fs.time, rule=translator_F_rule)
        t.T_eq = pyo.Constraint(m.fs.time, rule=translator_T_rule)
        t.P_eq = pyo.Constraint(m.fs.time, rule=translator_P_rule)

        outlet_comps = t.properties_out[0].component_list

        t.x_eq = pyo.Constraint(m.fs.time, outlet_comps,
                                rule=translator_x_rule)

    # feed translator
    m.fs.feed_translator.F_eq = pyo.Constraint(m.fs.time,
                                               rule=translator_F_rule)

    @m.fs.feed_translator.Constraint(m.fs.time)
    def translator_T_rule(b, t):
        return b.properties_in[t].temperature == b.outlet.temperature[t]

    m.fs.feed_translator.P_eq = pyo.Constraint(m.fs.time,
                                               rule=translator_P_rule)

    m.fs.feed_translator.outlet.mole_frac_comp[0, "H2"].fix(1e-19)
    m.fs.feed_translator.outlet.mole_frac_comp[0, "H2O"].fix(1)

    # 2nd flue gas translator
    @m.fs.flue_gas_translator_2.Constraint(m.fs.time)
    def translator_F_rule(b, t):
        return pyunits.convert(b.inlet.flow_mol[t], pyunits.kmol/pyunits.s) == b.outlet.flow_mol[t]

    m.fs.flue_gas_translator_2.T_eq = pyo.Constraint(m.fs.time, rule=translator_T_rule)

    @m.fs.flue_gas_translator_2.Constraint(m.fs.time)
    def translator_P_rule(b, t):
        return pyunits.convert(b.inlet.pressure[t], pyunits.kPa) == b.outlet.pressure[t]

    outlet_comps = m.fs.flue_gas_translator_2.properties_out[0].component_list

    m.fs.flue_gas_translator_2.x_eq = pyo.Constraint(m.fs.time, outlet_comps,
                                                     rule=translator_x_rule)

    # 3rd flue gas translator
    @m.fs.flue_gas_translator_3.Constraint(m.fs.time)
    def translator_F_rule(b, t):
        return pyunits.convert(b.inlet.flow_mol[t], pyunits.mol/pyunits.s) == b.outlet.flow_mol[t]

    m.fs.flue_gas_translator_3.T_eq = pyo.Constraint(m.fs.time, rule=translator_T_rule)

    @m.fs.flue_gas_translator_3.Constraint(m.fs.time)
    def translator_P_rule(b, t):
        return pyunits.convert(b.inlet.pressure[t], pyunits.Pa) == b.outlet.pressure[t]

    outlet_comps = m.fs.flue_gas_translator_3.properties_out[0].component_list

    m.fs.flue_gas_translator_3.x_eq = pyo.Constraint(m.fs.time, outlet_comps,
                                                     rule=translator_x_rule)

    # h2 condenser translator
    @m.fs.h2_condenser_translator.Constraint(m.fs.time)
    def translator_F_rule(b, t):
        return pyunits.convert(b.inlet.flow_mol[t], pyunits.kmol/pyunits.s) == b.outlet.flow_mol[t]

    m.fs.h2_condenser_translator.T_eq = pyo.Constraint(m.fs.time, rule=translator_T_rule)

    @m.fs.h2_condenser_translator.Constraint(m.fs.time)
    def translator_P_rule(b, t):
        return pyunits.convert(b.inlet.pressure[t], pyunits.kPa) == b.outlet.pressure[t]

    outlet_comps = m.fs.h2_condenser_translator.properties_out[0].component_list

    m.fs.h2_condenser_translator.x_eq = pyo.Constraint(m.fs.time, outlet_comps,
                                                       rule=translator_x_rule)

    # dryer translator
    @m.fs.dryer_translator.Constraint(m.fs.time)
    def translator_F_rule(b, t):
        return pyunits.convert(b.inlet.flow_mol[t], pyunits.mol/pyunits.s) == b.outlet.flow_mol[t]

    m.fs.dryer_translator.T_eq = pyo.Constraint(m.fs.time, rule=translator_T_rule)

    @m.fs.dryer_translator.Constraint(m.fs.time)
    def translator_P_rule(b, t):
        return pyunits.convert(b.inlet.pressure[t], pyunits.Pa) == b.outlet.pressure[t]

    m.fs.dryer_translator.outlet.mole_frac_comp[0, "H2"].fix(1)


def set_inputs(m):
    m.fs.hydrogen_product_rate.fix(5)
    m.fs.sofc_power.fix(680)
    m.fs.soec_single_pass_water_conversion.fix(0.7)

    # air to ASU
    m.fs.asu_cmp01.inlet.temperature.fix(288.15)  # K
    m.fs.asu_cmp01.inlet.pressure.fix(101353)  # kPa (14.7 psia)
    m.fs.asu_cmp01.inlet.mole_frac_comp[0, 'CO2'].fix(0.0003)
    m.fs.asu_cmp01.inlet.mole_frac_comp[0, 'H2O'].fix(0.0104)
    m.fs.asu_cmp01.inlet.mole_frac_comp[0, 'N2'].fix(0.7722)
    m.fs.asu_cmp01.inlet.mole_frac_comp[0, 'O2'].fix(0.2077)
    m.fs.asu_cmp01.inlet.mole_frac_comp[0, 'Ar'].fix(0.0094)

    # air compressors and intercoolers
    m.fs.asu_cmp01.outlet.pressure.fix(234422)  # kPa (34 psia)
    m.fs.asu_cmp01.efficiency_isentropic.fix(0.84)

    m.fs.asu_ic01.outlet.temperature.fix(310.93)  # K (100 F)
    m.fs.asu_ic01.deltaP.fix(-3447)  # kPa (-0.5 psi)

    m.fs.asu_cmp02.outlet.pressure.fix(544686)  # kPa (79 psia)
    m.fs.asu_cmp02.efficiency_isentropic.fix(0.84)

    m.fs.asu_ic02.outlet.temperature.fix(310.93)  # K (100 F)
    m.fs.asu_ic02.deltaP.fix(-3447)  # kPa (-0.5 psi)

    # air seperation unit
    m.fs.asu_split.split_fraction[0, "o2_outlet", "N2"].fix(0.0005)
    m.fs.asu_split.split_fraction[0, "o2_outlet", "O2"].fix(0.9691)
    m.fs.asu_split.split_fraction[0, "o2_outlet", "Ar"].fix(0.0673)
    m.fs.asu_split.o2_outlet.mole_frac_comp[0, "CO2"].fix(1e-19)
    m.fs.asu_split.o2_outlet.mole_frac_comp[0, "H2O"].fix(1e-19)

    m.fs.asu_heat.outlet.temperature.fix(299.82)  # K (80 F)
    m.fs.asu_heat.outlet.pressure.fix(158579)  # kPa (23 psia)

    # natural gas to oxycombustor
    m.fs.oxycombustor_mix.gas_inlet.flow_mol.fix(10)  # kmol/s
    m.fs.oxycombustor_mix.gas_inlet.temperature.fix(288.15)  # K
    m.fs.oxycombustor_mix.gas_inlet.pressure.fix(137895)  # kPa (20 psia)
    m.fs.oxycombustor_mix.gas_inlet.mole_frac_comp[0, 'CH4'].fix(0.931)
    m.fs.oxycombustor_mix.gas_inlet.mole_frac_comp[0, 'C2H6'].fix(0.032)
    m.fs.oxycombustor_mix.gas_inlet.mole_frac_comp[0, 'C3H8'].fix(0.007)
    m.fs.oxycombustor_mix.gas_inlet.mole_frac_comp[0, 'C4H10'].fix(0.004)
    m.fs.oxycombustor_mix.gas_inlet.mole_frac_comp[0, 'CO'].fix(1e-19)
    m.fs.oxycombustor_mix.gas_inlet.mole_frac_comp[0, 'CO2'].fix(0.01)
    m.fs.oxycombustor_mix.gas_inlet.mole_frac_comp[0, 'H2'].fix(1e-19)
    m.fs.oxycombustor_mix.gas_inlet.mole_frac_comp[0, 'H2O'].fix(1e-19)
    m.fs.oxycombustor_mix.gas_inlet.mole_frac_comp[0, 'N2'].fix(0.016)
    m.fs.oxycombustor_mix.gas_inlet.mole_frac_comp[0, 'O2'].fix(1e-19)
    m.fs.oxycombustor_mix.gas_inlet.mole_frac_comp[0, 'Ar'].fix(1e-19)

    # anode exhaust to oxycombustor
    m.fs.oxycombustor_mix.exhaust_inlet.pressure.fix(136999)
    m.fs.oxycombustor_mix.exhaust_inlet.mole_frac_comp[0, 'C2H6'].fix(1e-19)
    m.fs.oxycombustor_mix.exhaust_inlet.mole_frac_comp[0, 'C3H8'].fix(1e-19)
    m.fs.oxycombustor_mix.exhaust_inlet.mole_frac_comp[0, 'C4H10'].fix(1e-19)
    m.fs.oxycombustor_mix.exhaust_inlet.mole_frac_comp[0, 'O2'].fix(1e-19)
    m.fs.oxycombustor_mix.exhaust_inlet.mole_frac_comp[0, 'Ar'].fix(1e-19)

    m.fs.oxycombustor.heat_duty.fix(-71144050)
    m.fs.oxycombustor.deltaP.fix(-6895)  # kPa (-1 psi)

    m.fs.sweep_heater.tube_outlet.temperature.fix(1023.15)  # K (750 C)
    m.fs.sweep_heater.overall_heat_transfer_coefficient.fix(100)

    m.fs.boiler.tube_outlet.enth_mol.fix(
        iapws95.htpx(P=6e5*pyunits.Pa, x=1))
    m.fs.boiler.overall_heat_transfer_coefficient.fix(100)

    m.fs.fg_flash.control_volume.properties_out[0].temperature.fix(310.9)  # K
    m.fs.fg_flash.control_volume.properties_out[0].pressure.fix(101.325)  # kPa (14.7 psia)

    m.fs.bfw_pump.inlet.enth_mol.fix(
        iapws95.htpx(T=288.15*pyo.units.K, P=101325*pyo.units.Pa))  # 15 C
    m.fs.bfw_pump.inlet.pressure.fix(101325)

    m.fs.bfw_pump.outlet.pressure.fix(6e5)  # 4.2 psi
    m.fs.bfw_pump.efficiency_isentropic.fix(0.85)

    m.fs.feed_hx.shell_outlet.temperature.fix(523)  # 250 C
    m.fs.feed_hx.overall_heat_transfer_coefficient.fix(100)

    m.fs.feed_heater.outlet.temperature.fix(1000)

    m.fs.feed_recycle_split.split_fraction[:, "out"].fix(0.95)

    m.fs.h2_condenser.control_volume.properties_out[0].temperature.fix(300)

    m.fs.cmp01.ratioP.fix(1.81)
    m.fs.cmp01.efficiency_isentropic.fix(0.85)
    m.fs.ic01.control_volume.properties_out[:].temperature.fix(300)
    m.fs.cmp02.ratioP.fix(1.81)
    m.fs.cmp02.efficiency_isentropic.fix(0.85)
    m.fs.ic02.control_volume.properties_out[:].temperature.fix(300)
    m.fs.cmp03.ratioP.fix(1.81)
    m.fs.cmp03.efficiency_isentropic.fix(0.85)
    m.fs.ic03.control_volume.properties_out[:].temperature.fix(300)
    m.fs.cmp04.control_volume.properties_out[:].pressure.fix(64.78*1e5)
    m.fs.cmp04.efficiency_isentropic.fix(0.85)

    m.fs.sweep_compressor.inlet.flow_mol.fix(5635)  # kmol/s
    m.fs.sweep_compressor.inlet.temperature.fix(288.15)  # K
    m.fs.sweep_compressor.inlet.pressure.fix(101353)  # kPa (14.7 psia)
    m.fs.sweep_compressor.inlet.mole_frac_comp[0, 'CO2'].fix(0.0003)
    m.fs.sweep_compressor.inlet.mole_frac_comp[0, 'H2O'].fix(0.0104)
    m.fs.sweep_compressor.inlet.mole_frac_comp[0, 'N2'].fix(0.7722)
    m.fs.sweep_compressor.inlet.mole_frac_comp[0, 'O2'].fix(0.2077)
    m.fs.sweep_compressor.inlet.mole_frac_comp[0, 'Ar'].fix(0.0094)

    m.fs.sweep_compressor.efficiency_isentropic.fix(0.85)
    m.fs.sweep_compressor.control_volume.properties_out[:].pressure.fix(6e5)

    m.fs.sweep_hx.area.fix(4000)
    m.fs.sweep_hx.overall_heat_transfer_coefficient.fix(100)

    m.fs.sweep_turbine.efficiency_isentropic.fix(0.85)
    m.fs.sweep_turbine.control_volume.properties_out[:].pressure.fix(101353)


def set_cell_params(m):
    m.fs.soec_module.number_cells.fix(1e6)

    m.fs.soec_module.solid_oxide_cell.fuel_channel.length_x.fix(0.002)
    m.fs.soec_module.solid_oxide_cell.length_y.fix(0.2345)
    m.fs.soec_module.solid_oxide_cell.length_z.fix(0.2345)
    m.fs.soec_module.solid_oxide_cell.fuel_channel.heat_transfer_coefficient.fix(100)

    m.fs.soec_module.solid_oxide_cell.oxygen_channel.length_x.fix(0.002)
    m.fs.soec_module.solid_oxide_cell.oxygen_channel.heat_transfer_coefficient.fix(100)

    m.fs.soec_module.solid_oxide_cell.fuel_electrode.length_x.fix(1e-3)
    m.fs.soec_module.solid_oxide_cell.fuel_electrode.porosity.fix(0.326)
    m.fs.soec_module.solid_oxide_cell.fuel_electrode.tortuosity.fix(3)
    m.fs.soec_module.solid_oxide_cell.fuel_electrode.solid_heat_capacity.fix(595)
    m.fs.soec_module.solid_oxide_cell.fuel_electrode.solid_density.fix(7740.0)
    m.fs.soec_module.solid_oxide_cell.fuel_electrode.solid_thermal_conductivity.fix(6.23)
    m.fs.soec_module.solid_oxide_cell.fuel_electrode.resistivity_log_preexponential_factor.fix(
        pyo.log(2.5e-5)
    )
    m.fs.soec_module.solid_oxide_cell.fuel_electrode.resistivity_thermal_exponent_dividend.fix(0)

    m.fs.soec_module.solid_oxide_cell.oxygen_electrode.length_x.fix(40e-6)
    m.fs.soec_module.solid_oxide_cell.oxygen_electrode.porosity.fix(0.30717)
    m.fs.soec_module.solid_oxide_cell.oxygen_electrode.tortuosity.fix(3.0)
    m.fs.soec_module.solid_oxide_cell.oxygen_electrode.solid_heat_capacity.fix(142.3)
    m.fs.soec_module.solid_oxide_cell.oxygen_electrode.solid_density.fix(3030)
    m.fs.soec_module.solid_oxide_cell.oxygen_electrode.solid_thermal_conductivity.fix(5.84)
    m.fs.soec_module.solid_oxide_cell.oxygen_electrode.resistivity_log_preexponential_factor.fix(
        pyo.log(7.8125e-05)
    )
    m.fs.soec_module.solid_oxide_cell.oxygen_electrode.resistivity_thermal_exponent_dividend.fix(0)

    m.fs.soec_module.solid_oxide_cell.electrolyte.length_x.fix(10.5e-6)
    m.fs.soec_module.solid_oxide_cell.electrolyte.heat_capacity.fix(400)
    m.fs.soec_module.solid_oxide_cell.electrolyte.density.fix(6000)
    m.fs.soec_module.solid_oxide_cell.electrolyte.thermal_conductivity.fix(2.17)
    m.fs.soec_module.solid_oxide_cell.electrolyte.resistivity_log_preexponential_factor.fix(-9.001)
    m.fs.soec_module.solid_oxide_cell.electrolyte.resistivity_thermal_exponent_dividend.fix(8988.134)

    m.fs.soec_module.solid_oxide_cell.fuel_triple_phase_boundary.exchange_current_log_preexponential_factor.fix(
        22.5
    )
    m.fs.soec_module.solid_oxide_cell.fuel_triple_phase_boundary.exchange_current_activation_energy.fix(110.802e3)
    m.fs.soec_module.solid_oxide_cell.fuel_triple_phase_boundary.activation_potential_alpha1.fix(0.647816)
    m.fs.soec_module.solid_oxide_cell.fuel_triple_phase_boundary.activation_potential_alpha2.fix(0.352184)

    m.fs.soec_module.solid_oxide_cell.fuel_triple_phase_boundary.exchange_current_exponent_comp["H2"].fix(1)
    m.fs.soec_module.solid_oxide_cell.fuel_triple_phase_boundary.exchange_current_exponent_comp["H2O"].fix(1)

    m.fs.soec_module.solid_oxide_cell.oxygen_triple_phase_boundary.exchange_current_log_preexponential_factor.fix(
        25.5
    )
    m.fs.soec_module.solid_oxide_cell.oxygen_triple_phase_boundary.exchange_current_activation_energy.fix(112.066e3)
    m.fs.soec_module.solid_oxide_cell.oxygen_triple_phase_boundary.activation_potential_alpha1.fix(0.503)
    m.fs.soec_module.solid_oxide_cell.oxygen_triple_phase_boundary.activation_potential_alpha2.fix(0.497)

    m.fs.soec_module.solid_oxide_cell.oxygen_triple_phase_boundary.exchange_current_exponent_comp["O2"].fix(0.5)


def scale_flowsheet(m):
    generic_prop_packages = [
        m.fs.cmb_props,
        m.fs.air_props,
        m.fs.flue_props,
        m.fs.h2_side_props,
        m.fs.h2_pure_props
    ]
    for pp in generic_prop_packages:
        pp.set_default_scaling("flow_mol", 1e-3)
        pp.set_default_scaling("flow_mol_phase", 1e-3)
        pp.set_default_scaling("temperature", 1e-2)
        pp.set_default_scaling("pressure", 1e-5)
        pp.set_default_scaling("mole_frac_comp", 1e2)
        pp.set_default_scaling("mole_frac_phase_comp", 1e2)
        pp.set_default_scaling("enth_mol_phase", 1e-3)

    vle_prop_packages = [
        m.fs.flue_props_vle,
        m.fs.h2_side_props_vle
    ]
    for pp in vle_prop_packages:
        pp.set_default_scaling("flow_mol", 1)
        pp.set_default_scaling("flow_mol_phase", 1)
        pp.set_default_scaling("temperature", 1e-2)
        pp.set_default_scaling("pressure", 1e-2)
        pp.set_default_scaling("mole_frac_comp", 1e2)
        pp.set_default_scaling("mole_frac_phase_comp", 1e2)
        pp.set_default_scaling("enth_mol_phase", 1e-3)

    # heat exchanger areas and overall heat transfer coefficiencts
    iscale.set_scaling_factor(m.fs.boiler.area, 1e-3)
    iscale.set_scaling_factor(m.fs.boiler.overall_heat_transfer_coefficient, 1e-2)
    iscale.set_scaling_factor(m.fs.feed_hx.area, 1e-3)
    iscale.set_scaling_factor(m.fs.feed_hx.overall_heat_transfer_coefficient, 1e-2)
    iscale.set_scaling_factor(m.fs.sweep_hx.area, 1e-3)
    iscale.set_scaling_factor(m.fs.sweep_hx.overall_heat_transfer_coefficient, 1e-2)
    iscale.set_scaling_factor(m.fs.sweep_heater.area, 1e-2)
    iscale.set_scaling_factor(m.fs.sweep_heater.overall_heat_transfer_coefficient, 1e-2)

    # control volume heats
    iscale.set_scaling_factor(m.fs.boiler.tube.heat, 1e-7)
    iscale.set_scaling_factor(m.fs.boiler.shell.heat, 1e-7)
    iscale.set_scaling_factor(m.fs.feed_hx.tube.heat, 1e-7)
    iscale.set_scaling_factor(m.fs.feed_hx.shell.heat, 1e-7)
    iscale.set_scaling_factor(m.fs.feed_heater.control_volume.heat, 1e-6)
    iscale.set_scaling_factor(m.fs.h2_condenser.control_volume.heat, 1e-4)
    iscale.set_scaling_factor(m.fs.ic01.control_volume.heat, 1e-5)
    iscale.set_scaling_factor(m.fs.ic02.control_volume.heat, 1e-5)
    iscale.set_scaling_factor(m.fs.ic03.control_volume.heat, 1e-5)
    iscale.set_scaling_factor(m.fs.sweep_hx.tube.heat, 1e-6)
    iscale.set_scaling_factor(m.fs.sweep_hx.shell.heat, 1e-6)
    iscale.set_scaling_factor(m.fs.sweep_heater.tube.heat, 1e-6)
    iscale.set_scaling_factor(m.fs.sweep_heater.shell.heat, 1e-6)
    iscale.set_scaling_factor(m.fs.asu_ic01.control_volume.heat, 1e-6)
    iscale.set_scaling_factor(m.fs.asu_ic02.control_volume.heat, 1e-6)
    iscale.set_scaling_factor(m.fs.asu_heat.control_volume.heat, 1e-4)
    iscale.set_scaling_factor(m.fs.oxycombustor.control_volume.heat, 1e-6)
    iscale.set_scaling_factor(m.fs.fg_flash.control_volume.heat, 1e-5)

    # control volume works
    iscale.set_scaling_factor(m.fs.bfw_pump.control_volume.work, 1e-3)
    iscale.set_scaling_factor(m.fs.sweep_compressor.control_volume.work, 1e-6)
    iscale.set_scaling_factor(m.fs.sweep_turbine.control_volume.work, 1e-6)
    iscale.set_scaling_factor(m.fs.asu_cmp01.control_volume.work, 1e-6)
    iscale.set_scaling_factor(m.fs.asu_cmp02.control_volume.work, 1e-6)
    iscale.set_scaling_factor(m.fs.cmp01.control_volume.work, 1e-5)
    iscale.set_scaling_factor(m.fs.cmp02.control_volume.work, 1e-5)
    iscale.set_scaling_factor(m.fs.cmp03.control_volume.work, 1e-5)
    iscale.set_scaling_factor(m.fs.cmp04.control_volume.work, 1e-5)

    # reaction extents
    iscale.set_scaling_factor(m.fs.oxycombustor.control_volume.rate_reaction_extent[0, "h2_cmb"], 1e-1)
    iscale.set_scaling_factor(m.fs.oxycombustor.control_volume.rate_reaction_extent[0, "co_cmb"], 1e-1)
    iscale.set_scaling_factor(m.fs.oxycombustor.control_volume.rate_reaction_extent[0, "ch4_cmb"], 1)
    iscale.set_scaling_factor(m.fs.oxycombustor.control_volume.rate_reaction_extent[0, "c2h6_cmb"], 1e2)
    iscale.set_scaling_factor(m.fs.oxycombustor.control_volume.rate_reaction_extent[0, "c3h8_cmb"], 1e2)
    iscale.set_scaling_factor(m.fs.oxycombustor.control_volume.rate_reaction_extent[0, "c4h10_cmb"], 1e2)

    # vle property mole fractions
    iscale.set_scaling_factor(m.fs.flue_gas_translator_2.properties_out[0.0].mole_frac_comp, 1e1)
    iscale.set_scaling_factor(m.fs.fg_flash.control_volume.properties_in[0.0].mole_frac_comp, 1e1)
    iscale.set_scaling_factor(m.fs.fg_flash.control_volume.properties_out[0.0].mole_frac_comp, 1e1)
    iscale.set_scaling_factor(m.fs.flue_gas_translator_3.properties_in[0.0].mole_frac_comp, 1e1)
    iscale.set_scaling_factor(m.fs.h2_condenser_translator.properties_out[0.0].mole_frac_comp, 1e1)
    iscale.set_scaling_factor(m.fs.h2_condenser.control_volume.properties_in[0.0].mole_frac_comp, 1e1)
    iscale.set_scaling_factor(m.fs.h2_condenser.control_volume.properties_out[0.0].mole_frac_comp, 1e1)
    iscale.set_scaling_factor(m.fs.dryer_translator.properties_in[0.0].mole_frac_comp, 1e1)

    # flash
    iscale.set_scaling_factor(m.fs.fg_flash.split._Vap_flow_mol_ref[0.0], 1)
    iscale.set_scaling_factor(m.fs.fg_flash.split._Vap_mole_frac_comp_ref[0.0, "CO2"], 1e1)
    iscale.set_scaling_factor(m.fs.fg_flash.split._Vap_mole_frac_comp_ref[0.0, "H2O"], 1e1)
    iscale.set_scaling_factor(m.fs.fg_flash.split._Vap_mole_frac_comp_ref[0.0, "N2"], 1e1)
    iscale.set_scaling_factor(m.fs.fg_flash.split._Vap_mole_frac_comp_ref[0.0, "O2"], 1e1)
    iscale.set_scaling_factor(m.fs.fg_flash.split._Vap_mole_frac_comp_ref[0.0, "Ar"], 1e3)

    # cpu
    iscale.set_scaling_factor(m.fs.cpu.inlet_mole_frac_comp[0.0, "CO2"], 1e1)
    iscale.set_scaling_factor(m.fs.cpu.inlet_mole_frac_comp[0.0, "H2O"], 1e1)
    iscale.set_scaling_factor(m.fs.cpu.inlet_mole_frac_comp[0.0, "N2"], 1e1)
    iscale.set_scaling_factor(m.fs.cpu.inlet_mole_frac_comp[0.0, "O2"], 1e1)
    iscale.set_scaling_factor(m.fs.cpu.inlet_mole_frac_comp[0.0, "Ar"], 1e3)

    # hydrogen condenser
    iscale.set_scaling_factor(m.fs.h2_condenser.split._Vap_flow_mol_ref[0.0], 1)
    iscale.set_scaling_factor(m.fs.h2_condenser.split._Vap_mole_frac_comp_ref[0.0, "H2"], 1e1)
    iscale.set_scaling_factor(m.fs.h2_condenser.split._Vap_mole_frac_comp_ref[0.0, "H2O"], 1e2)

    iscale.set_scaling_factor(m.fs.soec_module.number_cells, 1e-6)

    translator_blocks = [
        m.fs.asu_translator,
        m.fs.flue_gas_translator,
        m.fs.flue_gas_translator_3,
        m.fs.feed_translator,
        m.fs.dryer_translator,
        ]
    for b in translator_blocks:
        if hasattr(b, "F_eq"):
            iscale.constraint_scaling_transform(
                b.F_eq[0], 1e-3
            )
            iscale.constraint_scaling_transform(
                b.P_eq[0], 1e-5
            )
        else:
            iscale.constraint_scaling_transform(
                b.translator_F_rule[0], 1e-3
            )
            iscale.constraint_scaling_transform(
                b.translator_P_rule[0], 1e-5
            )

    iscale.calculate_scaling_factors(m)


def add_results(m):
    ###########################################################################
    # HRSG and STEAM CYCLE
    water_density = 8.333*pyunits.lb/pyunits.gal
    steam_cycle_efficiency = 0.381
    ref_st_power = 262800*pyunits.kW

    # total heat supplied to HRSG in MMBtu/hr
    @m.fs.Expression(m.fs.time)
    def hrsg_heat_duty(fs, t):
        return -1*pyunits.convert(fs.oxycombustor.heat_duty[t],
                                  pyunits.MBtu/pyunits.hr)

    # heat duty of steam required for ASU in MMBtu/hr
    @m.fs.Expression(m.fs.time)
    def asu_steam_duty(fs, t):
        return pyunits.convert(
                (10206.4*pyunits.Btu/pyunits.kmol *
                 fs.asu_split.o2_outlet.flow_mol[t]),
                pyunits.MBtu/pyunits.hr)

    # HRSG heat applied toward steam cycle in MMBtu/hr
    @m.fs.Expression(m.fs.time)
    def steam_cycle_heat_duty(fs, t):
        return fs.hrsg_heat_duty[t] - fs.asu_steam_duty[t]

    # power generated by steam cycle in kW
    @m.fs.Expression(m.fs.time)
    def steam_cycle_power(fs, t):
        return pyunits.convert(
            fs.steam_cycle_heat_duty[t]*steam_cycle_efficiency,
            pyunits.kW)

    # steam cycle condenser duty in MMBtu/hr
    @m.fs.Expression(m.fs.time)
    def condenser_duty(b, t):
        return pyunits.convert(
            b.steam_cycle_heat_duty[t]*(1 - steam_cycle_efficiency),
            pyunits.MBtu/pyunits.hr)

    # boiler feed water flow in lb/hr
    @m.fs.Expression(m.fs.time)
    def feedwater_flow(b, t):
        ref_flowrate = 1398910*pyunits.lb/pyunits.hr
        return ref_flowrate*(b.steam_cycle_power[t]/ref_st_power)

    # BFW makeup flow in gpm
    @m.fs.Expression(m.fs.time)
    def bfw_makeup(b, t):
        return pyunits.convert(0.01*b.feedwater_flow[t]/water_density,
                               pyunits.gal/pyunits.min)

    # BFW pump load in kW
    @m.fs.Expression(m.fs.time)
    def bfw_pump_work(b, t):
        ref_pump_work = 4830*pyunits.kW
        return ref_pump_work*(b.steam_cycle_power[t]/ref_st_power)

    # condensate pump load in kW
    @m.fs.Expression(m.fs.time)
    def condensate_pump_work(b, t):
        ref_pump_work = 150*pyunits.kW
        return ref_pump_work*(b.steam_cycle_power[t]/ref_st_power)

    # steam turbine auxiliary load in kW
    @m.fs.Expression(m.fs.time)
    def steam_turbine_aux_load(b, t):
        ref_aux_load = 200*pyunits.kW
        return ref_aux_load*(b.steam_cycle_power[t]/ref_st_power)

    ###########################################################################
    # COOLING WATER SYSTEM

    water_molar_mass = 18*pyunits.g/pyunits.mol
    water_heat_capacity = 1*pyunits.Btu/pyunits.lb/pyunits.F
    CW_range = 20*pyunits.F
    cycles_of_concentration = 4
    baseline_cw_flow = 220784*pyunits.gal/pyunits.min

    # cooling water duty in MMBtu/hr
    # includes 25 MMBtu/hr of misc cooling loads
    @m.fs.Expression(m.fs.time)
    def cooling_water_duty(b, t):
        return (b.condenser_duty[t] +
                25*pyunits.MBtu/pyunits.hr +
                pyunits.convert(b.cpu.heat_duty[t],
                                pyunits.MBtu/pyunits.hr) +
                pyunits.convert(-1*b.asu_ic01.heat_duty[t] +
                                -1*b.asu_ic02.heat_duty[t] +
                                -1*b.ic01.heat_duty[t] +
                                -1*b.ic02.heat_duty[t] +
                                -1*b.ic03.heat_duty[t],
                                pyunits.MBtu/pyunits.hr) +
                pyunits.convert(-1*b.fg_flash.heat_duty[t] +
                                -1*b.h2_condenser.heat_duty[t],
                                pyunits.MBtu/pyunits.hr))

    # cooling water circulation rate in gpm
    @m.fs.Expression(m.fs.time)
    def cooling_water_flow(b, t):
        return pyunits.convert(
            b.cooling_water_duty[t]/water_heat_capacity/CW_range/water_density,
            pyunits.gal/pyunits.min)

    # cooling tower evaporation losses in gpm
    @m.fs.Expression(m.fs.time)
    def evaporation_losses(b, t):
        return 0.008*20/10*b.cooling_water_flow[t]

    # cooling tower blowdown losses in gpm
    @m.fs.Expression(m.fs.time)
    def blowdown_losses(b, t):
        return b.evaporation_losses[t]/(cycles_of_concentration-1)

    # cooling water pump auxiliary load
    @m.fs.Expression(m.fs.time)
    def cooling_water_pump_load(b, t):
        baseline_pump_load = 4580*pyunits.kW
        return baseline_pump_load*(b.cooling_water_flow[t]/baseline_cw_flow)

    # cooling tower fans auxiliary load
    @m.fs.Expression(m.fs.time)
    def cooling_tower_fan_load(b, t):
        baseline_fan_load = 2370*pyunits.kW
        return baseline_fan_load*(b.cooling_water_flow[t]/baseline_cw_flow)

    ###########################################################################
    # SYSTEM WATER USAGE

    @m.fs.Expression(m.fs.time)
    def electrolysis_water_demand(b, t):
        return pyunits.convert(
            b.bfw_pump.control_volume.properties_in[0].flow_vol,
            pyunits.gal/pyunits.min)

    # water demand in gpm
    @m.fs.Expression(m.fs.time)
    def water_demand(b, t):
        return (b.electrolysis_water_demand[t] +
                b.evaporation_losses[t] +
                b.blowdown_losses[t] +
                b.bfw_makeup[t])

    # internal recycle in gpm
    @m.fs.Expression(m.fs.time)
    def water_recycle(b, t):
        water_flow_mol = (
            b.fg_flash.liq_outlet.flow_mol[t] +
            b.h2_condenser.liq_outlet.flow_mol[t] +
            pyunits.convert(
                b.cpu.water.flow_mol[t],
                pyunits.kmol/pyunits.s
            )
        )
        return pyunits.convert(
            water_flow_mol*water_molar_mass/water_density,
            pyunits.gal/pyunits.min)

    # raw water withdrawal in gpm
    @m.fs.Expression(m.fs.time)
    def raw_water_withdrawal(b, t):
        return b.water_demand[t] - b.water_recycle[t]

    # process water discharge in gpm
    @m.fs.Expression(m.fs.time)
    def process_water_discharge(b, t):
        return b.blowdown_losses[t]*0.9

    # raw water consumption in gpm
    @m.fs.Expression(m.fs.time)
    def raw_water_consumption(b, t):
        return b.raw_water_withdrawal[t] - b.process_water_discharge[t]

    ###########################################################################
    # AUXILIARY LOADS AND NET POWER

    m.fs.inverter_efficiency = pyo.Param(initialize=0.97, mutable=True)

    @m.fs.Expression(m.fs.time)
    def sofc_power_ac(fs, t):
        return pyunits.convert(fs.sofc_power[t] * fs.inverter_efficiency,
                               pyunits.kW)

    @m.fs.Expression(m.fs.time)
    def gross_power(fs, t):
        return (
            fs.sofc_power_ac[t] +
            fs.steam_cycle_power[t] +
            -1*pyunits.convert(
                fs.sweep_turbine.control_volume.work[t],
                pyunits.kW
            )
        )

    @m.fs.Expression(m.fs.time)
    def soec_load(fs, t):
        return pyunits.convert(
            fs.soec_module.electrical_work[t],
            pyunits.kW)

    @m.fs.Expression(m.fs.time)
    def soec_load_ac(fs, t):
        return fs.soec_load[t]/0.97

    @m.fs.Expression(m.fs.time)
    def asu_load(fs, t):
        return pyunits.convert(
            (fs.asu_cmp01.work_mechanical[t]/0.96 +
             fs.asu_cmp02.work_mechanical[t]/0.96),
            pyunits.kW)

    @m.fs.Expression(m.fs.time)
    def h2_compressor_load(fs, t):
        return pyunits.convert(
            (fs.cmp01.control_volume.work[t] +
             fs.cmp02.control_volume.work[t] +
             fs.cmp03.control_volume.work[t] +
             fs.cmp04.control_volume.work[t]),
            pyunits.kW)

    @m.fs.Expression(m.fs.time)
    def cpu_load(fs, t):
        return pyunits.convert(fs.cpu.work[t], pyunits.kW)

    @m.fs.Expression(m.fs.time)
    def sofc_power_island_load(fs, t):
        return (6.5889*fs.sofc_power[t]/pyunits.MW + 69.141)*pyunits.kW

    # auxiliary load of the plant excluding transformer losses
    @m.fs.Expression(m.fs.time)
    def pre_transformer_loss_aux_load(fs, t):
        return (fs.bfw_pump_work[t] +
                fs.condensate_pump_work[t] +
                fs.steam_turbine_aux_load[t] +
                fs.cooling_water_pump_load[t] +
                fs.cooling_tower_fan_load[t] +
                fs.asu_load[t] +
                fs.h2_compressor_load[t] +
                fs.cpu_load[t] +
                fs.soec_load_ac[t] +
                pyunits.convert(
                    (fs.sweep_compressor.control_volume.work[t] +
                     fs.bfw_pump.control_volume.work[t] +
                     fs.feed_heater.heat_duty[t]),
                    pyunits.kW))

    @m.fs.Expression(m.fs.time)
    def transformer_losses(fs, t):
        HV_aux = fs.asu_load[t] + fs.cpu_load[t] + fs.h2_compressor_load[t]
        MV_aux = fs.pre_transformer_loss_aux_load[t] - HV_aux
        LV_aux = MV_aux*0.15

        HV_gen_loss = ((fs.gross_power[t] - fs.pre_transformer_loss_aux_load[t]) + HV_aux)*.003
        HV_loss = HV_aux*.003
        MV_loss = MV_aux*.005
        LV_loss = LV_aux*.005

        return HV_gen_loss + HV_loss + MV_loss + LV_loss

    # true auxiliary load
    @m.fs.Expression(m.fs.time)
    def auxiliary_load(fs, t):
        return fs.pre_transformer_loss_aux_load[t] + fs.transformer_losses[t]

    @m.fs.Expression(m.fs.time)
    def other_loads(fs, t):
        return (
            fs.auxiliary_load[t] -
            fs.soec_load_ac[t] -
            fs.asu_load[t] -
            fs.cpu_load[t] -
            fs.h2_compressor_load[t]
        )

    @m.fs.Expression(m.fs.time)
    def net_power(fs, t):
        return fs.gross_power[t] - fs.auxiliary_load[t]

    ###########################################################################
    # OTHER RESULTS

    @m.fs.Expression(m.fs.time)
    def stack_conversion(fs, t):
        water_in = (fs.soec_module.fuel_inlet.flow_mol[t] *
                    fs.soec_module.fuel_inlet.mole_frac_comp[t, "H2O"])
        h2_out = (fs.soec_module.fuel_outlet.flow_mol[t] *
                  fs.soec_module.fuel_outlet.mole_frac_comp[t, "H2"])
        return 100 * h2_out/water_in

    @m.fs.Expression(m.fs.time)
    def overall_conversion(fs, t):
        water_in = (fs.feed_recycle_mix.feed_inlet.flow_mol[t] *
                    fs.feed_recycle_mix.feed_inlet.mole_frac_comp[t, "H2O"])
        h2_out = (fs.feed_recycle_split.out.flow_mol[t] *
                  fs.feed_recycle_split.out.mole_frac_comp[t, "H2"])
        return 100 * h2_out/water_in

    # natural gas
    @m.fs.Expression(m.fs.time)
    def sofc_natural_gas_flow_mol(fs, t):
        return (1.77*fs.sofc_power[t]/pyunits.MW - 23.68)*pyunits.mol/pyunits.s

    @m.fs.Expression(m.fs.time)
    def sofc_natural_gas_flow_mass(fs, t):
        return pyunits.convert(
            17.328*pyunits.g/pyunits.mol * fs.sofc_natural_gas_flow_mol[t],
            pyunits.kg/pyunits.s)

    @m.fs.Expression(m.fs.time)
    def natural_gas_flow_mol(fs, t):
        return (fs.sofc_natural_gas_flow_mol[t] +
                fs.oxycombustor_mix.gas_inlet.flow_mol[t])

    @m.fs.Expression(m.fs.time)
    def natural_gas_flow_mass(fs, t):
        return pyunits.convert(
            17.328*pyunits.g/pyunits.mol * fs.natural_gas_flow_mol[t],
            pyunits.kg/pyunits.s)

    @m.fs.Expression(m.fs.time)
    def natural_gas_flow_energy(fs, t):
        ng_hhv = 908839.23*pyunits.J/pyunits.mol
        return pyunits.convert(
            fs.natural_gas_flow_mol[t] * ng_hhv,
            pyunits.kW)

    @m.fs.Expression(m.fs.time)
    def thermal_input_per_kg(fs, t):
        ng_hhv = 908839.23*pyunits.J/pyunits.mol
        return pyunits.convert(
            fs.natural_gas_flow_mol[t] * ng_hhv / fs.hydrogen_product_rate[t],
            pyunits.kWh/pyunits.kg)

    @m.fs.Expression(m.fs.time)
    def electric_input_per_kg(fs, t):
        return pyunits.convert(
            fs.net_power[t] / fs.hydrogen_product_rate[t],
            pyunits.kWh/pyunits.kg)

    @m.fs.Expression(m.fs.time)
    def hydrogen_flow_energy(fs, t):
        hydrogen_hhv = 141.88 * pyunits.MJ/pyunits.kg
        return pyunits.convert(
            fs.hydrogen_product_rate[t] * hydrogen_hhv,
            pyunits.kW)

    @m.fs.Expression(m.fs.time)
    def efficiency_hhv(fs, t):
        return 100 * (fs.hydrogen_flow_energy[t] /
                      (fs.natural_gas_flow_energy[t] - fs.net_power[t]))

    @m.fs.Expression(m.fs.time)
    def co2_emissions(fs, t):
        cpu_co2_flow = (
            fs.cpu.vent.flow_mol[t] * fs.cpu.vent.mole_frac_comp[t, 'CO2'])

        return pyunits.convert(
            (cpu_co2_flow) * 44.01*pyunits.g/pyunits.mol,
            pyunits.kg/pyunits.hr)

    @m.fs.Expression(m.fs.time)
    def co2_emissions_sweep(fs, t):
        air_co2_flow = (
            fs.sweep_hx.shell_outlet.flow_mol[t] *
            fs.sweep_hx.shell_outlet.mole_frac_comp[t, 'CO2'])

        return pyunits.convert(
            (air_co2_flow) * 44.01*pyunits.g/pyunits.mol,
            pyunits.kg/pyunits.hr)

    @m.fs.Expression(m.fs.time)
    def cpu_exhaust_flow_vol(fs, t):
        flow_vol = (
            m.fs.cpu.vent.flow_mol[t] * 772.56*pyunits.ft**3/pyunits.kmol
        )
        return pyunits.convert(flow_vol, pyunits.ft**3/pyunits.min)

    @m.fs.Expression(m.fs.time)
    def carbon_intensity(fs, t):
        cpu_co2_flow = (
            fs.cpu.vent.flow_mol[t] * fs.cpu.vent.mole_frac_comp[t, 'CO2'])

        air_co2_flow = (
            fs.sweep_hx.shell_outlet.flow_mol[t] *
            fs.sweep_hx.shell_outlet.mole_frac_comp[t, 'CO2'])

        co2_mass_flow = (
            (cpu_co2_flow + air_co2_flow) * 44.01*pyunits.g/pyunits.mol)

        return pyunits.convert(co2_mass_flow/fs.gross_power[t],
                               pyunits.kg/pyunits.MWh)


def get_model():
    m = pyo.ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    add_properties(m)
    add_models(m)
    add_arcs(m)
    add_constraints(m)
    set_inputs(m)
    set_cell_params(m)
    scale_flowsheet(m)
    add_results(m)
    return m


def initialize(m):
    # initialize ASU
    m.fs.asu_cmp01.inlet.flow_mol[0] = 2066
    m.fs.asu_cmp01.initialize()

    iinit.propagate_state(m.fs.asu01)

    m.fs.asu_ic01.initialize()

    iinit.propagate_state(m.fs.asu02)

    m.fs.asu_cmp02.initialize()

    iinit.propagate_state(m.fs.asu03)

    m.fs.asu_ic02.initialize()

    iinit.propagate_state(m.fs.asu04)

    m.fs.asu_split.initialize()

    iinit.propagate_state(m.fs.asu05)

    m.fs.asu_heat.initialize()

    iinit.propagate_state(m.fs.to_asu_translator)

    m.fs.asu_translator.initialize()

    iinit.propagate_state(m.fs.oxy01)

    # initialize oxycombustor
    exh_in = m.fs.oxycombustor_mix.exhaust_inlet

    calculate_variable_from_constraint(exh_in.flow_mol[0],
                                       m.fs.anode_exhaust_F[0])

    calculate_variable_from_constraint(exh_in.temperature[0],
                                       m.fs.anode_exhaust_T[0])

    calculate_variable_from_constraint(exh_in.mole_frac_comp[0, "CH4"],
                                       m.fs.anode_exhaust_x_ch4[0])

    calculate_variable_from_constraint(exh_in.mole_frac_comp[0, "CO"],
                                       m.fs.anode_exhaust_x_co[0])

    calculate_variable_from_constraint(exh_in.mole_frac_comp[0, "CO2"],
                                       m.fs.anode_exhaust_x_co2[0])

    calculate_variable_from_constraint(exh_in.mole_frac_comp[0, "H2"],
                                       m.fs.anode_exhaust_x_h2[0])

    calculate_variable_from_constraint(exh_in.mole_frac_comp[0, "N2"],
                                       m.fs.anode_exhaust_x_n2[0])

    calculate_variable_from_constraint(exh_in.mole_frac_comp[0, "H2O"],
                                       m.fs.anode_exhaust_mole_frac_sum[0])

    m.fs.oxycombustor_mix.initialize()

    iinit.propagate_state(m.fs.oxy02)

    m.fs.oxycombustor.initialize()

    iinit.propagate_state(m.fs.to_fg_translator)

    m.fs.flue_gas_translator.initialize()

    iinit.propagate_state(m.fs.fg01)

    m.fs.sweep_heater.tube_inlet.flow_mol[0] = 5635
    m.fs.sweep_heater.tube_inlet.temperature[0] = 900
    m.fs.sweep_heater.tube_inlet.pressure[0] = 6e5
    m.fs.sweep_heater.tube_inlet.mole_frac_comp[0, 'CO2'] = 0.0003
    m.fs.sweep_heater.tube_inlet.mole_frac_comp[0, 'H2O'] = 0.0104
    m.fs.sweep_heater.tube_inlet.mole_frac_comp[0, 'N2'] = 0.7722
    m.fs.sweep_heater.tube_inlet.mole_frac_comp[0, 'O2'] = 0.2077
    m.fs.sweep_heater.tube_inlet.mole_frac_comp[0, 'Ar'] = 0.0094
    m.fs.sweep_heater.initialize()

    iinit.propagate_state(m.fs.fg02)

    m.fs.bfw_pump.inlet.flow_mol[0] = 3472
    m.fs.bfw_pump.initialize()

    iinit.propagate_state(m.fs.w01)

    m.fs.boiler.initialize()

    iinit.propagate_state(m.fs.w02)

    iinit.propagate_state(m.fs.to_fg_translator_2)

    m.fs.flue_gas_translator_2.initialize()

    iinit.propagate_state(m.fs.fg03)

    m.fs.fg_flash.initialize()

    iinit.propagate_state(m.fs.to_fg_translator_3)

    m.fs.flue_gas_translator_3.initialize()

    iinit.propagate_state(m.fs.fg04)

    m.fs.cpu.initialize()

    iinit.propagate_state(m.fs.swp03)

    m.fs.soec_module.fuel_inlet.flow_mol[0] = 3655
    m.fs.soec_module.fuel_inlet.temperature[0] = 1000
    m.fs.soec_module.fuel_inlet.pressure[0] = 6e5
    m.fs.soec_module.fuel_inlet.mole_frac_comp[0, "H2"] = 0.035
    m.fs.soec_module.fuel_inlet.mole_frac_comp[0, "H2O"] = 0.965
    m.fs.soec_module.potential_cell.fix(1.3007)
    m.fs.soec_module.initialize(
        current_density_guess=-8650,
        temperature_guess=1040,
        )
    m.fs.soec_module.potential_cell.unfix()

    iinit.propagate_state(m.fs.h03)

    m.fs.feed_recycle_split.initialize()

    iinit.propagate_state(m.fs.hr01)
    iinit.propagate_state(m.fs.h04)

    m.fs.feed_hx.initialize()

    iinit.propagate_state(m.fs.to_h2_condenser_translator)

    m.fs.h2_condenser_translator.initialize()

    iinit.propagate_state(m.fs.h05)

    m.fs.h2_condenser.initialize()

    iinit.propagate_state(m.fs.h06)

    m.fs.dryer_translator.initialize()

    iinit.propagate_state(m.fs.h07)
    m.fs.cmp01.initialize()
    iinit.propagate_state(m.fs.h08)
    m.fs.ic01.initialize()
    iinit.propagate_state(m.fs.h09)
    m.fs.cmp02.initialize()
    iinit.propagate_state(m.fs.h10)
    m.fs.ic02.initialize()
    iinit.propagate_state(m.fs.h11)
    m.fs.cmp03.initialize()
    iinit.propagate_state(m.fs.h12)
    m.fs.ic03.initialize()
    iinit.propagate_state(m.fs.h13)
    m.fs.cmp04.initialize()

    iinit.propagate_state(m.fs.to_feed_translator)

    m.fs.feed_translator.inlet.fix()
    m.fs.feed_translator.initialize()
    m.fs.feed_translator.inlet.unfix()

    iinit.propagate_state(m.fs.w03)

    m.fs.feed_recycle_mix.initialize()

    iinit.propagate_state(m.fs.h01)

    m.fs.feed_heater.initialize()

    iinit.propagate_state(m.fs.swp04)

    m.fs.sweep_compressor.initialize()

    iinit.propagate_state(m.fs.swp01)

    m.fs.sweep_hx.initialize()

    iinit.propagate_state(m.fs.swp05)

    m.fs.sweep_turbine.initialize()


def add_tags(m):
    tag_group = iutil.ModelTagGroup()
    m._tags_streams = tag_group
    stream_states = tables.stream_states_dict(
        tables.arcs_to_stream_dict(
            m.fs,
            descend_into=False,
            additional={
                "exh01": m.fs.oxycombustor_mix.exhaust_inlet,
                "ng02": m.fs.oxycombustor_mix.gas_inlet,
                "asu00": m.fs.asu_cmp01.inlet,
                "n2": m.fs.asu_split.n2_outlet,
                "swp00": m.fs.sweep_compressor.inlet,
                "swp06": m.fs.sweep_turbine.outlet,
                "w00": m.fs.bfw_pump.inlet,
                "h14": m.fs.cmp04.outlet,
            }
        )
    )
    for i, s in stream_states.items():  # create the tags for steam quantities
        tag_group[f"{i}_Fmass"] = iutil.ModelTag(
            doc=f"{i}: mass flow",
            expr=s.flow_mass,
            format_string="{:.3f}",
            display_units=pyo.units.kg / pyo.units.s,
        )
        tag_group[f"{i}_F"] = iutil.ModelTag(
            doc=f"{i}: mole flow",
            expr=s.flow_mol,
            format_string="{:.3f}",
            display_units=pyo.units.kmol / pyo.units.s,
        )
        if hasattr(s, "mole_frac_comp"):
            for c in s.mole_frac_comp:
                tag_group[f"{i}_y{c}"] = iutil.ModelTag(
                    doc=f"{i}: mole percent {c}",
                    expr=s.mole_frac_comp[c] * 100,
                    format_string="{:.3f}",
                    display_units="%",
                )
        else:  # it's steam
            tag_group[f"{i}_yH2O"] = iutil.ModelTag(
                doc=f"{i}: mole percent {c}",
                expr=100,
                format_string="{:.3f}",
                display_units="%",
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
        tag_group[f"{i}_Fvol"] = iutil.ModelTag(
            doc=f"{i}: volumetric flow",
            expr=s.flow_vol,
            format_string="{:.3f}",
            display_units=pyo.units.m**3 / pyo.units.s,
        )
        if hasattr(s, "vapor_frac"):
            vf = 100 * s.vapor_frac
        else:
            vf = 100
        tag_group[f"{i}_vf"] = iutil.ModelTag(
            doc=f"{i}: vapor fraction",
            expr=vf,
            format_string="{:.2f}",
            display_units="%",
        )

    other_ports = {
        "wat01": m.fs.fg_flash.liq_outlet,
        "fg04": m.fs.fg_flash.vap_outlet,
        "wat02": m.fs.cpu.water,
        "co2": m.fs.cpu.pureco2,
        "vent": m.fs.cpu.vent
    }

    for i, p in other_ports.items():
        tag_group[f"{i}_F"] = iutil.ModelTag(
            doc=f"{i}: mole flow",
            expr=p.flow_mol[0],
            format_string="{:.3f}",
            display_units=pyo.units.kmol / pyo.units.s,
        )
        for c in p.mole_frac_comp:
            j = c[1]
            tag_group[f"{i}_y{j}"] = iutil.ModelTag(
                doc=f"{i}: mole percent {j}",
                expr=p.mole_frac_comp[c] * 100,
                format_string="{:.3f}",
                display_units="%",
            )
        tag_group[f"{i}_P"] = iutil.ModelTag(
            doc=f"{i}: pressure",
            expr=p.pressure[0],
            format_string="{:.3f}",
            display_units=pyo.units.bar,
        )
        tag_group[f"{i}_T"] = iutil.ModelTag(
            doc=f"{i}: temperature",
            expr=p.temperature[0],
            format_string="{:.2f}",
            display_units=pyo.units.K,
        )

    tag_group = iutil.ModelTagGroup()
    m._tags_output = tag_group
    tag_group["sofc_power_dc"] = iutil.ModelTag(
        expr=m.fs.sofc_power[0],
        format_string="{:.1f}",
        display_units=pyunits.MW,
    )
    tag_group["sofc_power_ac"] = iutil.ModelTag(
        expr=m.fs.sofc_power_ac[0],
        format_string="{:.1f}",
        display_units=pyunits.MW,
    )
    tag_group["steam_turbine_power"] = iutil.ModelTag(
        expr=m.fs.steam_cycle_power[0],
        format_string="{:.1f}",
        display_units=pyo.units.MW,
    )
    tag_group["sweep_turbine_power"] = iutil.ModelTag(
        expr=-m.fs.sweep_turbine.work_mechanical[0],
        format_string="{:.1f}",
        display_units=pyo.units.MW,
    )
    tag_group["gross_power"] = iutil.ModelTag(
        expr=m.fs.gross_power[0],
        format_string="{:.1f}",
        display_units=pyo.units.MW,
    )
    tag_group["soec_load_ac"] = iutil.ModelTag(
        expr=m.fs.soec_load_ac[0],
        format_string="{:.1f}",
        display_units=pyo.units.MW,
    )
    tag_group["asu_load"] = iutil.ModelTag(
        expr=m.fs.asu_load[0],
        format_string="{:.1f}",
        display_units=pyo.units.MW,
    )
    tag_group["cpu_load"] = iutil.ModelTag(
        expr=m.fs.cpu.work[0],
        format_string="{:.1f}",
        display_units=pyo.units.MW,
    )
    tag_group["h2_compressor_load"] = iutil.ModelTag(
        expr=m.fs.h2_compressor_load[0],
        format_string="{:.1f}",
        display_units=pyo.units.MW,
    )
    tag_group["other_loads"] = iutil.ModelTag(
        expr=m.fs.other_loads[0],
        format_string="{:.1f}",
        display_units=pyo.units.MW,
    )
    tag_group["auxiliary_load"] = iutil.ModelTag(
        expr=m.fs.auxiliary_load[0],
        format_string="{:.1f}",
        display_units=pyo.units.MW,
    )
    tag_group["net_power"] = iutil.ModelTag(
        expr=m.fs.net_power[0],
        format_string="{:.0f}",
        display_units=pyo.units.MW,
    )
    tag_group["number_of_cells"] = iutil.ModelTag(
        expr=m.fs.soec_module.number_cells,
        format_string="{:.0f}",
        display_units="",
    )
    tag_group["cell_potential"] = iutil.ModelTag(
        expr=m.fs.soec_module.potential_cell[0],
        format_string="{:.3f}",
        display_units=pyo.units.V,
    )
    tag_group["current_density"] = iutil.ModelTag(
        expr=m.fs.soec_module.solid_oxide_cell.average_current_density[0],
        format_string="{:.0f}",
        display_units=pyo.units.A / pyo.units.m**2,
    )
    tag_group["soec_power_per_h2"] = iutil.ModelTag(
        expr=m.fs.soec_load_ac[0]/m.fs.hydrogen_product_rate[0],
        format_string="{:.3f}",
        display_units=pyo.units.MJ/pyo.units.kg,
    )
    tag_group["hydrogen_production"] = iutil.ModelTag(
        expr=m.fs.hydrogen_product_rate[0],
        format_string="{:.0f}",
        display_units=pyo.units.kg/pyunits.s,
    )
    tag_group["overall_conversion"] = iutil.ModelTag(
        expr=m.fs.overall_conversion[0],
        format_string="{:.2f}",
        display_units="%",
    )
    tag_group["sofc_natural_gas_flow"] = iutil.ModelTag(
        expr=m.fs.sofc_natural_gas_flow_mol[0],
        format_string="{:.2f}",
        display_units=pyo.units.kmol/pyunits.s,
    )
    tag_group["oxycombustor_natural_gas_flow"] = iutil.ModelTag(
        expr=m.fs.oxycombustor_mix.gas_inlet.flow_mol[0],
        format_string="{:.2f}",
        display_units=pyo.units.kmol/pyunits.s,
    )
    tag_group["total_natural_gas_flow"] = iutil.ModelTag(
        expr=m.fs.natural_gas_flow_mol[0],
        format_string="{:.2f}",
        display_units=pyo.units.kmol/pyunits.s,
    )
    tag_group["total_variable_cost"] = iutil.ModelTag(
        expr=m.fs.costing.total_variable_OM_cost[0],
        format_string="{:.2f}",
        display_units=pyo.units.USD_2018/pyunits.hr,
    )
    tag_group["natural_gas_cost"] = iutil.ModelTag(
        expr=m.fs.costing.variable_operating_costs[0, "natural gas"],
        format_string="{:.2f}",
        display_units=pyo.units.USD_2018/pyunits.hr,
    )
    tag_group["water_cost"] = iutil.ModelTag(
        expr=m.fs.costing.variable_operating_costs[0, "water"],
        format_string="{:.2f}",
        display_units=pyo.units.USD_2018/pyunits.hr,
    )
    tag_group["desulfurization_cost"] = iutil.ModelTag(
        expr=m.fs.costing.variable_operating_costs[0, "desulfur adsorbent"],
        format_string="{:.2f}",
        display_units=pyo.units.USD_2018/pyunits.hr,
    )
    tag_group["prereformer_catalyst_cost"] = iutil.ModelTag(
        expr=m.fs.costing.variable_operating_costs[0, "prereformer catalyst"],
        format_string="{:.2f}",
        display_units=pyo.units.USD_2018/pyunits.hr,
    )
    tag_group["water_treatment_cost"] = iutil.ModelTag(
        expr=m.fs.costing.variable_operating_costs[0, "water treatment chemicals"],
        format_string="{:.2f}",
        display_units=pyo.units.USD_2018/pyunits.hr,
    )
    tag_group["water flowrate to SOEC"] = iutil.ModelTag(
        expr=m.fs.bfw_pump.control_volume.properties_in[0].flow_mass,
        format_string="{:.2f}",
        display_units=pyunits.kg/pyunits.s,
    )
    tag_group["stack_conversion"] = iutil.ModelTag(
        expr=m.fs.stack_conversion[0],
        format_string="{:.2f}",
        display_units="%",
    )


def _stream_col_gen(tag_group):
    """Generate a stream table heading from a group of stream tags
    """
    for tag in tag_group.values():
        spltstr = tag.doc.split(":")
        stream = spltstr[0].strip()
        col = f"{spltstr[1].strip()} ({tag.get_unit_str()})"
        yield tag, stream, col


def make_stream_table(tag_group):
    """Generate a stream table from a group of stream tags
    """
    rows = set()
    cols = set()
    tags = []
    for tag, stream, col in _stream_col_gen(tag_group):
        rows.add(stream)
        cols.add(col)
        tags.append((tag, stream, col))
    df = pd.DataFrame(index=sorted(rows), columns=sorted(cols))
    for tag, stream, col in tags:
        df.at[stream, col] = tag.get_display_value()
    return df


def write_pfd(m, fname=None):
    """Add model results to the flowsheet template.  If fname is specified,
    this saves the resulting svg to a file.  If fname is not specified, it
    returns the svg string.

    Args:
        fname: Name of file to save svg.  If None, return the svg string
    Returns: (None or Str)
    """
    add_tags(m)

    infilename = os.path.join(this_file_dir(), "sofc_soec_template.svg")
    with open(infilename, "r") as f:
        s = svg_tag(svg=f, tag_group=m._tags_streams, outfile=None)
    s = svg_tag(svg=s, tag_group=m._tags_output, outfile=fname)
    if fname is None:
        return s


if __name__ == "__main__":
    # solver setup
    use_idaes_solver_configuration_defaults()
    idaes.cfg.ipopt.options.nlp_scaling_method = "user-scaling"
    idaes.cfg.ipopt.options.linear_solver = "ma57"
    idaes.cfg.ipopt.options.OF_ma57_automatic_scaling = "yes"
    idaes.cfg.ipopt.options.ma57_pivtol = 1e-5
    idaes.cfg.ipopt.options.ma57_pivtolmax = 0.1
    idaes.cfg.ipopt.options.bound_push = 1e-20
    solver = pyo.SolverFactory("ipopt")

    m = get_model()
    initialize(m)
    solver.solve(m, tee=True)


