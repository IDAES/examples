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
import pandas as pd

# Import Pyomo libraries
import pyomo.environ as pyo
from pyomo.environ import units as pyunits
from pyomo.network import Arc
from pyomo.common.fileutils import this_file_dir
from pyomo.util.calc_var_value import calculate_variable_from_constraint

# IDAES Imports
import idaes
import idaes.core.util as iutil
import idaes.core.util.tables as tables
import idaes.core.util.scaling as iscale
from idaes.core import FlowsheetBlock
from idaes.core.solvers import use_idaes_solver_configuration_defaults
from idaes.core.util.initialization import propagate_state
from idaes.core.util.tags import svg_tag
import idaes.logger as idaeslog

from idaes.models.properties.modular_properties.base.generic_property import (
    GenericParameterBlock)
from idaes.models.properties.modular_properties.base.generic_reaction import (
    GenericReactionParameterBlock)

from idaes.models.unit_models import (
    Mixer,
    Heater,
    HeatExchanger,
    PressureChanger,
    GibbsReactor,
    StoichiometricReactor,
    Flash,
    Separator,
    Translator
)
from idaes.models.unit_models.heat_exchanger import (
    delta_temperature_underwood_callback)
from idaes.models.unit_models.pressure_changer import ThermodynamicAssumption
from idaes.models.unit_models.separator import SplittingType
from idaes.models.unit_models.mixer import MomentumMixingType

from idaes.models_extra.power_generation.properties.natural_gas_PR import (
    get_prop,
    get_rxn
)
from idaes.models_extra.power_generation.unit_models.cpu import \
    CarbonProcessingUnit

from sofc_rom import SofcRom


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
        "N2"
        ]
    syn_gas_comps = [
        "CH4",
        "CO",
        "CO2",
        "H2",
        "H2O",
        "N2",
        "O2",
        "Ar"
        ]
    air_comps = ["CO2", "H2O", "N2", "O2", "Ar"]

    rxns = {
        "ch4_cmb": "CH4",
        "co_cmb": "CO",
        "h2_cmb": "H2"
        }

    m.fs.natural_gas_props = GenericParameterBlock(
        **get_prop(natural_gas_comps, ["Vap"], scaled=True))

    m.fs.syn_props = GenericParameterBlock(
        **get_prop(syn_gas_comps, ["Vap"], scaled=True))

    m.fs.air_props = GenericParameterBlock(
        **get_prop(air_comps, ["Vap"], scaled=True))

    m.fs.flue_props = GenericParameterBlock(
        **get_prop(air_comps, ["Vap", "Liq"], scaled=True))

    m.fs.rxn_props = GenericReactionParameterBlock(
        **get_rxn(m.fs.syn_props, rxns, scaled=True))


def add_models(m):
    ####################
    # anode side units #
    ####################
    m.fs.anode_mix = Mixer(
        inlet_list=["feed_inlet", "recycle_inlet"],
        property_package=m.fs.natural_gas_props
    )
    m.fs.anode_hx = HeatExchanger(
        hot_side_name="shell",
        cold_side_name="tube",
        shell={"property_package": m.fs.syn_props,
               "has_pressure_change": True},
        tube={"property_package": m.fs.natural_gas_props,
              "has_pressure_change": True},
        delta_temperature_callback=delta_temperature_underwood_callback
    )
    m.fs.prereformer = GibbsReactor(
        has_heat_transfer=False,
        has_pressure_change=True,
        inert_species=["N2"],
        property_package=m.fs.natural_gas_props
    )
    # C2H6, C3H8, and C4H10 are not present in the system after the prereformer
    # the property package is changed to improve model robustness
    m.fs.anode_translator = Translator(
        outlet_state_defined=True,
        inlet_property_package=m.fs.natural_gas_props,
        outlet_property_package=m.fs.syn_props
    )
    m.fs.fuel_cell_mix = Mixer(
        inlet_list=["fuel_inlet", "ion_inlet"],
        momentum_mixing_type=MomentumMixingType.none,
        property_package=m.fs.syn_props
    )
    m.fs.anode = GibbsReactor(
        has_heat_transfer=True,
        has_pressure_change=True,
        inert_species=["N2", "Ar"],
        property_package=m.fs.syn_props
    )
    m.fs.anode_recycle = Separator(
        outlet_list=["exhaust_outlet", "recycle_outlet"],
        property_package=m.fs.syn_props
    )
    m.fs.anode_blower = PressureChanger(
        compressor=True,
        property_package=m.fs.syn_props,
        thermodynamic_assumption=ThermodynamicAssumption.isentropic
    )
    # recycle is fed back to a part of the system that contains higher
    # hydrocarbons, so property package must be translated
    m.fs.recycle_translator = Translator(
        outlet_state_defined=True,
        inlet_property_package=m.fs.syn_props,
        outlet_property_package=m.fs.natural_gas_props
    )
    ######################
    # cathode side units #
    ######################
    m.fs.air_blower = PressureChanger(
        compressor=True,
        property_package=m.fs.air_props,
        thermodynamic_assumption=ThermodynamicAssumption.isentropic
    )
    m.fs.cathode_hx = HeatExchanger(
        hot_side_name="shell",
        cold_side_name="tube",
        shell={"property_package": m.fs.air_props,
               "has_pressure_change": True},
        tube={"property_package": m.fs.air_props,
              "has_pressure_change": True},
        delta_temperature_callback=delta_temperature_underwood_callback
    )
    m.fs.cathode_mix = Mixer(
        inlet_list=["air_inlet", "recycle_inlet"],
        property_package=m.fs.air_props
    )
    # represents oxygen moving across SOFC electrolyte
    m.fs.cathode = Separator(
        outlet_list=["air_outlet", "ion_outlet"],
        split_basis=SplittingType.componentFlow,
        property_package=m.fs.air_props
    )
    m.fs.cathode_translator = Translator(
        outlet_state_defined=True,
        inlet_property_package=m.fs.air_props,
        outlet_property_package=m.fs.syn_props
    )
    m.fs.cathode_heat = Heater(
        has_pressure_change=True,
        property_package=m.fs.air_props
    )
    m.fs.cathode_recycle = Separator(
        outlet_list=["exhaust_outlet", "recycle_outlet"],
        property_package=m.fs.air_props
    )
    m.fs.cathode_blower = PressureChanger(
        compressor=True,
        property_package=m.fs.air_props,
        thermodynamic_assumption=ThermodynamicAssumption.isentropic
    )
    m.fs.cathode_hrsg = Heater(
        has_pressure_change=True,
        property_package=m.fs.air_props
    )
    #########################
    # bottoming cycle units #
    #########################
    m.fs.air_compressor_s1 = PressureChanger(
        compressor=True,
        property_package=m.fs.air_props,
        thermodynamic_assumption=ThermodynamicAssumption.isentropic
    )
    m.fs.intercooler_s1 = Heater(
        has_pressure_change=True,
        property_package=m.fs.air_props
    )
    m.fs.air_compressor_s2 = PressureChanger(
        compressor=True,
        property_package=m.fs.air_props,
        thermodynamic_assumption=ThermodynamicAssumption.isentropic
    )
    m.fs.intercooler_s2 = Heater(
        has_pressure_change=True,
        property_package=m.fs.air_props
    )
    m.fs.asu = Separator(
        outlet_list=["N2_outlet", "O2_outlet"],
        split_basis=SplittingType.componentFlow,
        property_package=m.fs.air_props
    )
    m.fs.ASU_O2_outlet = Heater(
        has_pressure_change=True,
        property_package=m.fs.air_props
    )
    m.fs.oxycombustor_translator = Translator(
        outlet_state_defined=True,
        inlet_property_package=m.fs.air_props,
        outlet_property_package=m.fs.syn_props
    )
    m.fs.combustor_mix = Mixer(
        inlet_list=["anode_inlet", "oxygen_inlet"],
        property_package=m.fs.syn_props
    )
    m.fs.oxycombustor = StoichiometricReactor(
        has_heat_of_reaction=False,
        has_heat_transfer=False,
        has_pressure_change=True,
        property_package=m.fs.syn_props,
        reaction_package=m.fs.rxn_props
    )
    m.fs.anode_HRSG = Heater(
        has_pressure_change=True,
        property_package=m.fs.syn_props
    )
    m.fs.flue_gas_translator = Translator(
        outlet_state_defined=True,
        inlet_property_package=m.fs.syn_props,
        outlet_property_package=m.fs.flue_props
    )

    m.fs.condenser = Heater(
        has_pressure_change=True,
        property_package=m.fs.flue_props
    )
    m.fs.flash = Flash(
        has_heat_transfer=True,
        has_pressure_change=True,
        property_package=m.fs.flue_props
    )
    m.fs.cpu = CarbonProcessingUnit()


def add_arcs(m):
    """ Connect unit operations with arcs
    """
    # arcs for anode side
    m.fs.ng01 = Arc(
        source=m.fs.anode_mix.outlet,
        destination=m.fs.anode_hx.tube_inlet)

    m.fs.ng02 = Arc(
        source=m.fs.anode_hx.tube_outlet,
        destination=m.fs.prereformer.inlet)

    m.fs.ng02_trns = Arc(
        source=m.fs.prereformer.outlet,
        destination=m.fs.anode_translator.inlet)

    m.fs.ng03 = Arc(
        source=m.fs.anode_translator.outlet,
        destination=m.fs.fuel_cell_mix.fuel_inlet)

    m.fs.fc01 = Arc(
        source=m.fs.fuel_cell_mix.outlet,
        destination=m.fs.anode.inlet)

    m.fs.exh01 = Arc(
        source=m.fs.anode.outlet,
        destination=m.fs.anode_recycle.inlet)

    m.fs.exh02 = Arc(
        source=m.fs.anode_recycle.exhaust_outlet,
        destination=m.fs.anode_hx.shell_inlet)

    m.fs.frec01 = Arc(
        source=m.fs.anode_recycle.recycle_outlet,
        destination=m.fs.anode_blower.inlet)

    m.fs.frec02 = Arc(
        source=m.fs.anode_blower.outlet,
        destination=m.fs.recycle_translator.inlet)

    m.fs.frec02_trns = Arc(
        source=m.fs.recycle_translator.outlet,
        destination=m.fs.anode_mix.recycle_inlet)

    # arcs for cathode side
    m.fs.air01 = Arc(
        source=m.fs.air_blower.outlet,
        destination=m.fs.cathode_hx.tube_inlet)

    m.fs.air02 = Arc(
        source=m.fs.cathode_hx.tube_outlet,
        destination=m.fs.cathode_mix.air_inlet)

    m.fs.air03 = Arc(
        source=m.fs.cathode_mix.outlet,
        destination=m.fs.cathode.inlet)

    m.fs.ion01 = Arc(
        source=m.fs.cathode.ion_outlet,
        destination=m.fs.cathode_translator.inlet)

    m.fs.ion01_trns = Arc(
        source=m.fs.cathode_translator.outlet,
        destination=m.fs.fuel_cell_mix.ion_inlet)

    m.fs.cat01 = Arc(
        source=m.fs.cathode.air_outlet,
        destination=m.fs.cathode_heat.inlet)

    m.fs.air04 = Arc(
        source=m.fs.cathode_heat.outlet,
        destination=m.fs.cathode_recycle.inlet)

    m.fs.air05 = Arc(
        source=m.fs.cathode_recycle.exhaust_outlet,
        destination=m.fs.cathode_hx.shell_inlet)

    m.fs.arec01 = Arc(
        source=m.fs.cathode_recycle.recycle_outlet,
        destination=m.fs.cathode_blower.inlet)

    m.fs.arec02 = Arc(
        source=m.fs.cathode_blower.outlet,
        destination=m.fs.cathode_mix.recycle_inlet)

    m.fs.air06 = Arc(
        source=m.fs.cathode_hx.shell_outlet,
        destination=m.fs.cathode_hrsg.inlet)

    # arcs for ASU, oxycombustor, and CPU
    m.fs.asu01 = Arc(
        source=m.fs.air_compressor_s1.outlet,
        destination=m.fs.intercooler_s1.inlet)

    m.fs.asu02 = Arc(
        source=m.fs.intercooler_s1.outlet,
        destination=m.fs.air_compressor_s2.inlet)

    m.fs.asu03 = Arc(
        source=m.fs.air_compressor_s2.outlet,
        destination=m.fs.intercooler_s2.inlet)

    m.fs.asu04 = Arc(
        source=m.fs.intercooler_s2.outlet,
        destination=m.fs.asu.inlet)

    m.fs.asu05 = Arc(
        source=m.fs.asu.O2_outlet,
        destination=m.fs.ASU_O2_outlet.inlet)

    m.fs.asu05_trns = Arc(
        source=m.fs.ASU_O2_outlet.outlet,
        destination=m.fs.oxycombustor_translator.inlet)

    m.fs.exh03 = Arc(
        source=m.fs.anode_hx.shell_outlet,
        destination=m.fs.combustor_mix.anode_inlet)

    m.fs.oxy01 = Arc(
        source=m.fs.oxycombustor_translator.outlet,
        destination=m.fs.combustor_mix.oxygen_inlet)

    m.fs.oxy02 = Arc(
        source=m.fs.combustor_mix.outlet,
        destination=m.fs.oxycombustor.inlet)

    m.fs.fg01 = Arc(
        source=m.fs.oxycombustor.outlet,
        destination=m.fs.anode_HRSG.inlet)

    m.fs.fg01_trns = Arc(
        source=m.fs.anode_HRSG.outlet,
        destination=m.fs.flue_gas_translator.inlet)

    m.fs.fg02 = Arc(
        source=m.fs.flue_gas_translator.outlet,
        destination=m.fs.condenser.inlet)

    m.fs.fg03 = Arc(
        source=m.fs.condenser.outlet,
        destination=m.fs.flash.inlet)

    pyo.TransformationFactory("network.expand_arcs").apply_to(m.fs)


def add_constraints(m):
    """ Add additional flowsheet constraints and expressions
    """

    # add SOFC ROM
    # build_SOFC_ROM(m.fs)
    m.fs.sofc = SofcRom()

    # build constraints connecting flowsheet to ROM input vars
    @m.fs.Constraint()
    def ROM_fuel_inlet_temperature(fs):
        return(fs.sofc.fuel_temperature ==
               fs.anode_mix.feed_inlet.temperature[0]/pyunits.K - 273.15)

    @m.fs.Constraint()
    def ROM_air_inlet_temperature(fs):
        return(fs.sofc.air_temperature ==
               fs.cathode.inlet.temperature[0]/pyunits.K - 273.15)

    @m.fs.Constraint()
    def ROM_air_recirculation(fs):
        return(fs.sofc.air_recirculation ==
               fs.cathode_recycle.split_fraction[0, 'recycle_outlet'])

    @m.fs.Constraint()
    def ROM_OTC(fs):
        O_frac = (1 * fs.fuel_cell_mix.fuel_inlet.mole_frac_comp[0, 'CO']
                  + 2 * fs.fuel_cell_mix.fuel_inlet.mole_frac_comp[0, 'CO2']
                  + 1 * fs.fuel_cell_mix.fuel_inlet.mole_frac_comp[0, 'H2O'])

        C_frac = (1 * fs.fuel_cell_mix.fuel_inlet.mole_frac_comp[0, 'CO']
                  + 1 * fs.fuel_cell_mix.fuel_inlet.mole_frac_comp[0, 'CO2']
                  + 1 * fs.fuel_cell_mix.fuel_inlet.mole_frac_comp[0, 'CH4'])

        return fs.sofc.OTC == O_frac/C_frac

    @m.fs.Constraint()
    def ROM_fuel_utilization(fs):
        full_O2_flow = (fs.anode_mix.feed_inlet.flow_mol[0] * (
            0.5 * fs.anode_mix.feed_inlet.mole_frac_comp[0, 'H2'] +
            0.5 * fs.anode_mix.feed_inlet.mole_frac_comp[0, 'CO'] +
            2.0 * fs.anode_mix.feed_inlet.mole_frac_comp[0, 'CH4'] +
            3.5 * fs.anode_mix.feed_inlet.mole_frac_comp[0, 'C2H6'] +
            5.0 * fs.anode_mix.feed_inlet.mole_frac_comp[0, 'C3H8'] +
            6.5 * fs.anode_mix.feed_inlet.mole_frac_comp[0, 'C4H10']))

        return (fs.sofc.fuel_util*full_O2_flow ==
                fs.cathode.ion_outlet.flow_mol[0])

    @m.fs.Constraint()
    def ROM_air_utilization(fs):
        air_in = (fs.cathode_hx.tube_inlet.flow_mol[0] *
                  fs.cathode_hx.tube_inlet.mole_frac_comp[0, 'O2'])

        air_out = (fs.cathode_hx.shell_inlet.flow_mol[0] *
                   fs.cathode_hx.shell_inlet.mole_frac_comp[0, 'O2'])

        return fs.sofc.air_util == 1 - air_out/air_in

    @m.fs.Constraint()
    def ROM_anode_outlet_temperature(fs):
        return (fs.sofc.anode_outlet_temperature ==
                fs.anode.outlet.temperature[0]/pyunits.K - 273.15)

    # add constraints for power calculations
    m.fs.stack_current = pyo.Var(initialize=650, units=pyunits.MA)
    m.fs.sofc_power_dc = pyo.Var(initialize=600, units=pyunits.MW)

    @m.fs.Constraint()
    def stack_current_constraint(fs):
        return (fs.stack_current ==
                pyunits.convert(4*96487*pyunits.C/pyunits.mol*m.fs.cathode.ion_outlet.flow_mol[0],
                                pyunits.MA))

    @m.fs.Constraint()
    def sofc_power_dc_constraint(fs):
        return fs.sofc_power_dc == fs.stack_current*fs.sofc.stack_voltage

    @m.fs.Constraint()
    def SOFC_energy_balance(fs):
        return (-1*pyunits.convert(fs.anode.heat_duty[0], pyunits.MW) ==
                fs.sofc_power_dc +
                pyunits.convert(fs.cathode_heat.heat_duty[0], pyunits.MW))

    # outlet pressure should be equal to fuel inlet pressure because oxygen is
    # traveling through a solid electrolyte
    @m.fs.fuel_cell_mix.Constraint(m.fs.time)
    def ion_mix_constraint(b, t):
        return b.outlet.pressure[t] == b.fuel_inlet.pressure[t]

    @m.fs.Constraint()
    def air_to_combustor(fs):
        XS = 1.09  # excess oxygen

        F_CH4 = (fs.combustor_mix.anode_inlet.flow_mol[0] *
                 fs.combustor_mix.anode_inlet.mole_frac_comp[(0, "CH4")])
        F_CO = (fs.combustor_mix.anode_inlet.flow_mol[0] *
                fs.combustor_mix.anode_inlet.mole_frac_comp[(0, "CO")])
        F_H2 = (fs.combustor_mix.anode_inlet.flow_mol[0] *
                fs.combustor_mix.anode_inlet.mole_frac_comp[(0, "H2")])
        O2_required = 2*F_CH4 + 0.5*F_CO + 0.5*F_H2

        O2_fed = (fs.combustor_mix.oxygen_inlet.flow_mol[0] *
                  fs.combustor_mix.oxygen_inlet.mole_frac_comp[(0, "O2")])
        return O2_fed == XS*O2_required

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

    # anode translator
    m.fs.anode_translator.F_eq = pyo.Constraint(
        m.fs.time, rule=translator_F_rule)

    m.fs.anode_translator.T_eq = pyo.Constraint(
        m.fs.time, rule=translator_T_rule)

    m.fs.anode_translator.P_eq = pyo.Constraint(
        m.fs.time, rule=translator_P_rule)

    m.fs.anode_translator.x_eq = pyo.Constraint(
        m.fs.time, m.fs.syn_props.component_list, rule=translator_x_rule)

    # recycle translator
    m.fs.recycle_translator.F_eq = pyo.Constraint(
        m.fs.time, rule=translator_F_rule)

    m.fs.recycle_translator.T_eq = pyo.Constraint(
        m.fs.time, rule=translator_T_rule)

    m.fs.recycle_translator.P_eq = pyo.Constraint(
        m.fs.time, rule=translator_P_rule)

    m.fs.recycle_translator.x_eq = pyo.Constraint(
        m.fs.time, m.fs.natural_gas_props.component_list, rule=translator_x_rule)

    # cathode translator
    m.fs.cathode_translator.F_eq = pyo.Constraint(
        m.fs.time, rule=translator_F_rule)

    m.fs.cathode_translator.T_eq = pyo.Constraint(
        m.fs.time, rule=translator_T_rule)

    m.fs.cathode_translator.P_eq = pyo.Constraint(
        m.fs.time, rule=translator_P_rule)

    m.fs.cathode_translator.x_eq = pyo.Constraint(
        m.fs.time, m.fs.syn_props.component_list, rule=translator_x_rule)

    # oxycombustor translator
    m.fs.oxycombustor_translator.F_eq = pyo.Constraint(
        m.fs.time, rule=translator_F_rule)

    m.fs.oxycombustor_translator.T_eq = pyo.Constraint(
        m.fs.time, rule=translator_T_rule)

    m.fs.oxycombustor_translator.P_eq = pyo.Constraint(
        m.fs.time, rule=translator_P_rule)

    m.fs.oxycombustor_translator.x_eq = pyo.Constraint(
        m.fs.time, m.fs.syn_props.component_list, rule=translator_x_rule)

    # flue gas translator
    m.fs.flue_gas_translator.F_eq = pyo.Constraint(
        m.fs.time, rule=translator_F_rule)

    m.fs.flue_gas_translator.T_eq = pyo.Constraint(
        m.fs.time, rule=translator_T_rule)

    m.fs.flue_gas_translator.P_eq = pyo.Constraint(
        m.fs.time, rule=translator_P_rule)

    m.fs.flue_gas_translator.x_eq = pyo.Constraint(
        m.fs.time, m.fs.flue_props.component_list, rule=translator_x_rule)

    # cpu does not have a property package so "arc" is made manually
    @m.fs.Constraint(m.fs.time)
    def CPU_inlet_F(fs, t):  # converting from kmol/s to mol/s
        return fs.cpu.inlet.flow_mol[t] == fs.flash.vap_outlet.flow_mol[t]*1000

    @m.fs.Constraint(m.fs.time)
    def CPU_inlet_T(fs, t):
        return (fs.cpu.inlet.temperature[t] ==
                fs.flash.vap_outlet.temperature[t])

    @m.fs.Constraint(m.fs.time)
    def CPU_inlet_P(fs, t):  # converting from kPa to Pa
        return fs.cpu.inlet.pressure[t] == fs.flash.vap_outlet.pressure[t]*1000

    @m.fs.Constraint(m.fs.time, m.fs.flue_props.component_list)
    def CPU_inlet_x(fs, t, j):
        return (fs.cpu.inlet.mole_frac_comp[t, j] ==
                fs.flash.vap_outlet.mole_frac_comp[t, j])


def set_inputs(m):
    ###################
    # anode side inputs
    ###################
    # natural gas feed conditions
    m.fs.anode_mix.feed_inlet.flow_mol.fix(1.1116)  # kmol/s
    m.fs.anode_mix.feed_inlet.temperature.fix(288.15)  # K
    m.fs.anode_mix.feed_inlet.pressure.fix(137.895)  # kPa (20 psia)
    m.fs.anode_mix.feed_inlet.mole_frac_comp[0, 'CH4'].fix(0.931)
    m.fs.anode_mix.feed_inlet.mole_frac_comp[0, 'C2H6'].fix(0.032)
    m.fs.anode_mix.feed_inlet.mole_frac_comp[0, 'C3H8'].fix(0.007)
    m.fs.anode_mix.feed_inlet.mole_frac_comp[0, 'C4H10'].fix(0.004)
    m.fs.anode_mix.feed_inlet.mole_frac_comp[0, 'CO'].fix(1e-19)
    m.fs.anode_mix.feed_inlet.mole_frac_comp[0, 'CO2'].fix(0.01)
    m.fs.anode_mix.feed_inlet.mole_frac_comp[0, 'H2'].fix(1e-19)
    m.fs.anode_mix.feed_inlet.mole_frac_comp[0, 'H2O'].fix(1e-19)
    m.fs.anode_mix.feed_inlet.mole_frac_comp[0, 'N2'].fix(0.016)

    # anode heat exchanger
    m.fs.anode_hx.tube.deltaP.fix(-.1379)  # kPa (-0.02 psi)
    m.fs.anode_hx.shell.deltaP.fix(-.1379)  # kPa (-0.02 psi)
    m.fs.anode_hx.area.fix(3000)  # m2
    m.fs.anode_hx.overall_heat_transfer_coefficient.fix(80e-3)  # mW/m^2K

    # prereformer and anode
    m.fs.prereformer.deltaP.fix(-.1379)  # kPa (-0.02 psi)

    m.fs.anode.outlet.pressure.fix(137.137)  # kPa (19.89 psia)

    m.fs.anode_blower.outlet.pressure.fix(137.888)  # kPa (20 psia)
    m.fs.anode_blower.efficiency_isentropic.fix(0.8)

    #####################
    # cathode side inputs
    #####################

    # air feed conditions
    m.fs.air_blower.inlet.flow_mol.fix(11.444)  # kmol/s, unfixed by ROM
    m.fs.air_blower.inlet.temperature.fix(288.15)  # K (59 F)
    m.fs.air_blower.inlet.pressure.fix(101.353)  # kPa (14.7 psia)
    m.fs.air_blower.inlet.mole_frac_comp[0, 'H2O'].fix(0.0104)
    m.fs.air_blower.inlet.mole_frac_comp[0, 'CO2'].fix(0.0003)
    m.fs.air_blower.inlet.mole_frac_comp[0, 'N2'].fix(0.7722)
    m.fs.air_blower.inlet.mole_frac_comp[0, 'O2'].fix(0.2077)
    m.fs.air_blower.inlet.mole_frac_comp[0, 'Ar'].fix(0.0094)

    # air blower
    m.fs.air_blower.outlet.pressure.fix(111.006)  # kPa (16.1 psia)
    m.fs.air_blower.efficiency_isentropic.fix(0.82)

    # cathode heat exchanger
    m.fs.cathode_hx.tube_outlet.pressure.fix(105.490)  # kPa (15.3 psia)
    m.fs.cathode_hx.shell.deltaP.fix(-1.379)  # kPa (-0.2 psi)
    m.fs.cathode_hx.area.fix(14098)  # m2, unfixed by ROM
    m.fs.cathode_hx.overall_heat_transfer_coefficient.fix(80e-3)  # mW/m2K

    # cathode
    # cathode split fractions
    m.fs.cathode.split_fraction[0, 'ion_outlet', 'H2O'].fix(1e-19)
    m.fs.cathode.split_fraction[0, 'ion_outlet', 'CO2'].fix(1e-19)
    m.fs.cathode.split_fraction[0, 'ion_outlet', 'N2'].fix(1e-19)
    m.fs.cathode.split_fraction[0, 'ion_outlet', 'Ar'].fix(1e-19)

    m.fs.cathode_heat.outlet.pressure.fix(104.111)  # kPa (15.1 psia)

    # cathode recycle and blower
    m.fs.cathode_recycle.split_fraction[0, 'recycle_outlet'].fix(0.5)

    m.fs.cathode_blower.outlet.pressure.fix(105.490)  # kPa (15.3 psi)
    m.fs.cathode_blower.efficiency_isentropic.fix(0.8)

    m.fs.cathode_hrsg.outlet.temperature.fix(405.7)  # K (270 F)
    m.fs.cathode_hrsg.deltaP.fix(-1.379)  # kPa (-0.2 psi)

    #####################################
    # ASU, oxycombustor, and CPU inputs #
    #####################################
    # air to ASU
    m.fs.air_compressor_s1.inlet.temperature.fix(288.15)  # K
    m.fs.air_compressor_s1.inlet.pressure.fix(101.353)  # kPa (14.7 psia)
    m.fs.air_compressor_s1.inlet.mole_frac_comp[0, 'CO2'].fix(0.0003)
    m.fs.air_compressor_s1.inlet.mole_frac_comp[0, 'H2O'].fix(0.0104)
    m.fs.air_compressor_s1.inlet.mole_frac_comp[0, 'N2'].fix(0.7722)
    m.fs.air_compressor_s1.inlet.mole_frac_comp[0, 'O2'].fix(0.2077)
    m.fs.air_compressor_s1.inlet.mole_frac_comp[0, 'Ar'].fix(0.0094)

    # air compressors and intercoolers
    m.fs.air_compressor_s1.outlet.pressure.fix(234.422)  # kPa (34 psia)
    m.fs.air_compressor_s1.efficiency_isentropic.fix(0.84)

    m.fs.intercooler_s1.outlet.temperature.fix(310.93)  # K (100 F)
    m.fs.intercooler_s1.deltaP.fix(-3.447)  # kPa (-0.5 psi)

    m.fs.air_compressor_s2.outlet.pressure.fix(544.686)  # kPa (79 psia)
    m.fs.air_compressor_s2.efficiency_isentropic.fix(0.84)

    m.fs.intercooler_s2.outlet.temperature.fix(310.93)  # K (100 F)
    m.fs.intercooler_s2.deltaP.fix(-3.447)  # kPa (-0.5 psi)

    # air seperation unit
    m.fs.asu.O2_outlet.mole_frac_comp[0, "CO2"].fix(1e-19)
    m.fs.asu.O2_outlet.mole_frac_comp[0, "H2O"].fix(1e-19)
    m.fs.asu.split_fraction[0, "O2_outlet", "N2"].fix(0.0005)
    m.fs.asu.split_fraction[0, "O2_outlet", "O2"].fix(0.9691)
    m.fs.asu.split_fraction[0, "O2_outlet", "Ar"].fix(0.0673)

    m.fs.ASU_O2_outlet.outlet.temperature.fix(299.82)  # K (80 F)
    m.fs.ASU_O2_outlet.outlet.pressure.fix(158.579)  # kPa (23 psia)

    m.fs.oxycombustor.outlet.temperature.setub(2000)
    m.fs.oxycombustor.deltaP.fix(-6.895)  # kPa (-1 psi)

    m.fs.oxycombustor.outlet.mole_frac_comp[0, "H2"].fix(1e-19)
    m.fs.oxycombustor.outlet.mole_frac_comp[0, "CO"].fix(1e-19)
    m.fs.oxycombustor.outlet.mole_frac_comp[0, "CH4"].fix(1e-19)

    m.fs.anode_HRSG.inlet.temperature.setub(2000)
    m.fs.anode_HRSG.outlet.temperature.fix(405)  # K
    m.fs.anode_HRSG.deltaP.fix(-6.895)  # kPa (-1 psi)

    m.fs.condenser.outlet.temperature.fix(310.9)  # K (100 F)
    m.fs.condenser.deltaP.fix(-6.895)  # kPa (-1 psi)

    m.fs.flash.control_volume.properties_out[0].temperature.fix(310.9)  # K
    m.fs.flash.control_volume.properties_out[0].pressure.fix(101.3529)  # kPa (14.7 psia)

    # SOFC ROM inputs
    m.fs.sofc.current_density.fix(4000)
    m.fs.sofc.fuel_util.fix(0.85)
    m.fs.sofc.OTC.fix(2.1)
    m.fs.sofc.internal_reforming.fix(1)
    m.fs.sofc.pressure.fix(1)


def scale_flowsheet(m):
    # natural gas properties default scaling
    m.fs.natural_gas_props.set_default_scaling("flow_mol", 1)
    m.fs.natural_gas_props.set_default_scaling("flow_mol_phase", 1)
    m.fs.natural_gas_props.set_default_scaling("temperature", 1e-2)
    m.fs.natural_gas_props.set_default_scaling("pressure", 1e-2)
    m.fs.natural_gas_props.set_default_scaling("mole_frac_comp", 1e2)
    m.fs.natural_gas_props.set_default_scaling("mole_frac_phase_comp", 1e2)
    m.fs.natural_gas_props.set_default_scaling("enth_mol_phase", 1e-3)
    m.fs.natural_gas_props.set_default_scaling("entr_mol_phase", 1e-3)

    # syngas properties default scaling
    m.fs.syn_props.set_default_scaling("flow_mol", 1)
    m.fs.syn_props.set_default_scaling("flow_mol_phase", 1)
    m.fs.syn_props.set_default_scaling("temperature", 1e-2)
    m.fs.syn_props.set_default_scaling("pressure", 1e-2)
    m.fs.syn_props.set_default_scaling("mole_frac_comp", 1e2)
    m.fs.syn_props.set_default_scaling("mole_frac_phase_comp", 1e2)
    m.fs.syn_props.set_default_scaling("enth_mol_phase", 1e-3)
    m.fs.syn_props.set_default_scaling("entr_mol_phase", 1e-3)

    # set air properties default scaling
    m.fs.air_props.set_default_scaling("flow_mol", 1)
    m.fs.air_props.set_default_scaling("flow_mol_phase", 1)
    m.fs.air_props.set_default_scaling("temperature", 1e-2)
    m.fs.air_props.set_default_scaling("pressure", 1e-2)
    m.fs.air_props.set_default_scaling("mole_frac_comp", 1e2)
    m.fs.air_props.set_default_scaling("mole_frac_phase_comp", 1e2)
    m.fs.air_props.set_default_scaling("enth_mol_phase", 1e-3)
    m.fs.air_props.set_default_scaling("entr_mol_phase", 1e-3)

    # flue gas properties default scaling
    m.fs.flue_props.set_default_scaling("flow_mol", 1)
    m.fs.flue_props.set_default_scaling("flow_mol_phase", 1)
    m.fs.flue_props.set_default_scaling("temperature", 1e-2)
    m.fs.flue_props.set_default_scaling("pressure", 1e-2)
    m.fs.flue_props.set_default_scaling("mole_frac_comp", 1e1)
    m.fs.flue_props.set_default_scaling("mole_frac_phase_comp", 1e1)
    m.fs.flue_props.set_default_scaling("enth_mol_phase", 1e-3)
    m.fs.flue_props.set_default_scaling("entr_mol_phase", 1e-3)

    iscale.set_scaling_factor(m.fs.prereformer.lagrange_mult, 1e-4)
    iscale.set_scaling_factor(m.fs.anode.lagrange_mult, 1e-4)

    # some specific variable scaling

    # heat exchanger areas and overall heat transfer coefficiencts
    iscale.set_scaling_factor(m.fs.anode_hx.area, 1e-4)
    iscale.set_scaling_factor(m.fs.anode_hx.overall_heat_transfer_coefficient, 1e2)
    iscale.set_scaling_factor(m.fs.cathode_hx.area, 1e-4)
    iscale.set_scaling_factor(m.fs.cathode_hx.overall_heat_transfer_coefficient, 1e2)

    # control volume heats
    iscale.set_scaling_factor(m.fs.anode_hx.tube.heat, 1e-4)
    iscale.set_scaling_factor(m.fs.anode_hx.shell.heat, 1e-4)
    iscale.set_scaling_factor(m.fs.anode.control_volume.heat, 1e-5)
    iscale.set_scaling_factor(m.fs.cathode_hx.tube.heat, 1e-5)
    iscale.set_scaling_factor(m.fs.cathode_hx.shell.heat, 1e-5)
    iscale.set_scaling_factor(m.fs.cathode_heat.control_volume.heat, 1e-5)
    iscale.set_scaling_factor(m.fs.cathode_hrsg.control_volume.heat, 1e-2)
    iscale.set_scaling_factor(m.fs.intercooler_s1.control_volume.heat, 1e-3)
    iscale.set_scaling_factor(m.fs.intercooler_s2.control_volume.heat, 1e-3)
    iscale.set_scaling_factor(m.fs.ASU_O2_outlet.control_volume.heat, 1e-1)
    iscale.set_scaling_factor(m.fs.anode_HRSG.control_volume.heat, 1e-5)
    iscale.set_scaling_factor(m.fs.condenser.control_volume.heat, 1e-4)
    iscale.set_scaling_factor(m.fs.flash.control_volume.heat, 1e-2)

    # work
    iscale.set_scaling_factor(m.fs.anode_blower.control_volume.work, 1e-2)
    iscale.set_scaling_factor(m.fs.air_blower.control_volume.work, 1e-3)
    iscale.set_scaling_factor(m.fs.cathode_blower.control_volume.work, 1e-2)
    iscale.set_scaling_factor(m.fs.air_compressor_s1.control_volume.work, 1e-3)
    iscale.set_scaling_factor(m.fs.air_compressor_s2.control_volume.work, 1e-3)

    # reaction extents
    iscale.set_scaling_factor(m.fs.oxycombustor.control_volume.rate_reaction_extent[0, "h2_cmb"], 1e2)
    iscale.set_scaling_factor(m.fs.oxycombustor.control_volume.rate_reaction_extent[0, "co_cmb"], 1e2)
    iscale.set_scaling_factor(m.fs.oxycombustor.control_volume.rate_reaction_extent[0, "ch4_cmb"], 1e5)

    # default property package scaling was not working here
    iscale.set_scaling_factor(m.fs.flue_gas_translator.properties_out[0].mole_frac_comp, 1e1)
    iscale.set_scaling_factor(m.fs.condenser.control_volume.properties_in[0].mole_frac_comp, 1e1)
    iscale.set_scaling_factor(m.fs.condenser.control_volume.properties_out[0].mole_frac_comp, 1e1)
    iscale.set_scaling_factor(m.fs.flash.control_volume.properties_in[0].mole_frac_comp, 1e1)
    iscale.set_scaling_factor(m.fs.flash.control_volume.properties_out[0].mole_frac_comp, 1e1)

    # hide missing scaling factor wornings
    scaling_log = idaeslog.getLogger(
        "idaes.core.util.scaling", level=idaeslog.ERROR
    )

    iscale.calculate_scaling_factors(m)


def initialize(m):
    # set tear streams and other initial guesses

    # cathode inlet
    m.fs.cathode.inlet.flow_mol[0] = 21  # kmol/s
    m.fs.cathode.inlet.temperature[0] = 832  # K
    m.fs.cathode.inlet.pressure[0] = 105.4895  # kPa
    m.fs.cathode.inlet.mole_frac_comp[0, 'H2O'] = 0.0113
    m.fs.cathode.inlet.mole_frac_comp[0, 'CO2'] = 0.0003
    m.fs.cathode.inlet.mole_frac_comp[0, 'N2'] = 0.8418
    m.fs.cathode.inlet.mole_frac_comp[0, 'O2'] = 0.1362
    m.fs.cathode.inlet.mole_frac_comp[0, 'Ar'] = 0.0102

    # prereformer outlet
    m.fs.fuel_cell_mix.fuel_inlet.flow_mol[0] = 7.2  # kmol/s
    m.fs.fuel_cell_mix.fuel_inlet.temperature[0] = 789  # K
    m.fs.fuel_cell_mix.fuel_inlet.pressure[0] = 137.6  # kPa
    m.fs.fuel_cell_mix.fuel_inlet.mole_frac_comp[0, 'CH4'] = 0.1234
    m.fs.fuel_cell_mix.fuel_inlet.mole_frac_comp[0, 'CO'] = 0.0425
    m.fs.fuel_cell_mix.fuel_inlet.mole_frac_comp[0, 'CO2'] = 0.2581
    m.fs.fuel_cell_mix.fuel_inlet.mole_frac_comp[0, 'H2'] = 0.2379
    m.fs.fuel_cell_mix.fuel_inlet.mole_frac_comp[0, 'H2O'] = 0.3316
    m.fs.fuel_cell_mix.fuel_inlet.mole_frac_comp[0, 'N2'] = 0.0065
    m.fs.fuel_cell_mix.fuel_inlet.mole_frac_comp[0, 'O2'] = 1e-19
    m.fs.fuel_cell_mix.fuel_inlet.mole_frac_comp[0, 'Ar'] = 1e-19

    # others, unfixed at end of initialization
    m.fs.air_compressor_s1.inlet.flow_mol.fix(1.8)
    m.fs.cathode.ion_outlet.flow_mol.fix(1.893)
    m.fs.anode.outlet.temperature.fix(1001.1)
    m.fs.cathode_heat.outlet.temperature.fix(972.5)
    m.fs.anode_recycle.split_fraction[0, 'recycle_outlet'].fix(0.627)

    # cathode side
    m.fs.air_blower.initialize()

    propagate_state(arc=m.fs.air01)

    m.fs.cathode.initialize()

    # cathode translator block
    propagate_state(arc=m.fs.ion01)

    m.fs.cathode_translator.initialize()

    # rest of cathode side
    propagate_state(arc=m.fs.cat01)

    m.fs.cathode_heat.initialize()

    propagate_state(arc=m.fs.air04)

    m.fs.cathode_recycle.initialize()

    propagate_state(arc=m.fs.air05)

    m.fs.cathode_hx.initialize()

    propagate_state(arc=m.fs.arec01)

    m.fs.cathode_blower.initialize()

    propagate_state(arc=m.fs.arec02)

    propagate_state(arc=m.fs.air02)

    m.fs.cathode_mix.initialize()

    propagate_state(arc=m.fs.air06)

    m.fs.cathode_hrsg.initialize()

    # anode side
    propagate_state(arc=m.fs.ion01_trns)

    m.fs.fuel_cell_mix.initialize()

    propagate_state(arc=m.fs.fc01)

    # m.fs.anode.lagrange_mult[0, "C"] = 48722
    # m.fs.anode.lagrange_mult[0, "H"] = 77156
    # m.fs.anode.lagrange_mult[0, "O"] = 291729
    # m.fs.anode.outlet.mole_frac_comp[0, "O2"] = 1e-19
    # m.fs.anode.gibbs_scaling = 1e-4

    m.fs.anode.initialize()

    propagate_state(arc=m.fs.exh01)
    
    m.fs.anode_recycle.initialize()

    propagate_state(arc=m.fs.frec01)

    m.fs.anode_blower.initialize()

    propagate_state(arc=m.fs.frec02)

    m.fs.recycle_translator.initialize()

    propagate_state(arc=m.fs.frec02_trns)

    m.fs.anode_mix.initialize()

    propagate_state(arc=m.fs.ng01)

    propagate_state(arc=m.fs.exh02)

    m.fs.anode_hx.initialize()

    propagate_state(arc=m.fs.ng02)

    propagate_state(source=m.fs.prereformer.inlet,
                    destination=m.fs.prereformer.outlet)

    m.fs.prereformer.lagrange_mult[0, "C"] = 10000
    m.fs.prereformer.lagrange_mult[0, "H"] = 60000
    m.fs.prereformer.lagrange_mult[0, "O"] = 300000
    m.fs.prereformer.outlet.mole_frac_comp[0, "C2H6"] = 1e-19
    m.fs.prereformer.outlet.mole_frac_comp[0, "C3H8"] = 1e-19
    m.fs.prereformer.outlet.mole_frac_comp[0, "C4H10"] = 1e-19
    m.fs.prereformer.gibbs_scaling = 1e-2

    m.fs.prereformer.initialize()

    propagate_state(arc=m.fs.ng02_trns)

    m.fs.anode_translator.initialize()

    #############################
    # ASU, oxycombustor and CPU #
    #############################
    # air compressor train
    m.fs.air_compressor_s1.initialize()

    propagate_state(arc=m.fs.asu01)

    m.fs.intercooler_s1.initialize()

    propagate_state(arc=m.fs.asu02)

    m.fs.air_compressor_s2.initialize()

    propagate_state(arc=m.fs.asu03)

    m.fs.intercooler_s2.initialize()

    propagate_state(arc=m.fs.asu04)

    m.fs.asu.initialize()

    propagate_state(arc=m.fs.asu05)

    m.fs.ASU_O2_outlet.initialize()

    propagate_state(arc=m.fs.asu05_trns)

    m.fs.oxycombustor_translator.initialize()

    propagate_state(arc=m.fs.exh03)

    propagate_state(arc=m.fs.oxy01)

    m.fs.combustor_mix.initialize()

    propagate_state(arc=m.fs.oxy02)

    m.fs.oxycombustor.initialize()

    propagate_state(arc=m.fs.fg01)

    m.fs.anode_HRSG.initialize()

    propagate_state(arc=m.fs.fg01_trns)

    m.fs.flue_gas_translator.initialize()

    propagate_state(arc=m.fs.fg02)

    m.fs.condenser.initialize()

    propagate_state(arc=m.fs.fg03)

    m.fs.flash.initialize()

    propagate_state(source=m.fs.flash.vap_outlet,
                    destination=m.fs.cpu.inlet)

    calculate_variable_from_constraint(m.fs.cpu.inlet.flow_mol[0],
                                       m.fs.CPU_inlet_F[0])

    calculate_variable_from_constraint(m.fs.cpu.inlet.pressure[0],
                                       m.fs.CPU_inlet_P[0])

    m.fs.cpu.initialize()

    # initialize ROM
    calculate_variable_from_constraint(m.fs.sofc.fuel_temperature,
                                       m.fs.ROM_fuel_inlet_temperature)
    calculate_variable_from_constraint(m.fs.sofc.air_temperature,
                                       m.fs.ROM_air_inlet_temperature)
    calculate_variable_from_constraint(m.fs.sofc.air_util,
                                       m.fs.ROM_air_utilization)

    m.fs.sofc.initialize()

    # initialize power calculations
    calculate_variable_from_constraint(m.fs.stack_current,
                                       m.fs.stack_current_constraint)
    calculate_variable_from_constraint(m.fs.sofc_power_dc,
                                       m.fs.sofc_power_dc_constraint)

    m.fs.air_compressor_s1.inlet.flow_mol.unfix()
    m.fs.cathode.ion_outlet.flow_mol.unfix()
    m.fs.anode.outlet.temperature.unfix()
    m.fs.cathode_heat.outlet.temperature.unfix()
    m.fs.anode_recycle.split_fraction[0, 'recycle_outlet'].unfix()


def add_result_expressions(m):
    ###########################################################################
    # HRSG and STEAM CYCLE
    water_density = 8.333*pyunits.lb/pyunits.gal
    steam_cycle_efficiency = 0.381
    ref_st_power = 262800*pyunits.kW

    # total heat supplied to HRSG in MMBtu/hr
    @m.fs.Expression(m.fs.time)
    def hrsg_heat_duty(fs, t):
        return -1*pyunits.convert(
            (fs.anode_HRSG.heat_duty[t] + fs.cathode_hrsg.heat_duty[t]),
            pyunits.MBtu/pyunits.hr)

    # heat duty of steam required for ASU in MMBtu/hr
    @m.fs.Expression(m.fs.time)
    def asu_steam_duty(fs, t):
        return pyunits.convert(
                10206.4*pyunits.Btu/pyunits.kmol * fs.asu.O2_outlet.flow_mol[t],
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
                pyunits.convert(-1*b.intercooler_s1.heat_duty[t] +
                                -1*b.intercooler_s2.heat_duty[t] +
                                -1*b.condenser.heat_duty[t],
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

    # water demand in gpm
    @m.fs.Expression(m.fs.time)
    def water_demand(b, t):
        return (b.evaporation_losses[t] +
                b.blowdown_losses[t] +
                b.bfw_makeup[t])

    # internal recycle in gpm
    @m.fs.Expression(m.fs.time)
    def water_recycle(b, t):
        cpu_water = pyunits.convert(
            b.cpu.water.flow_mol[t]*water_molar_mass/water_density,
            pyunits.gal/pyunits.min)
        flash_water = pyunits.convert(
            b.flash.liq_outlet.flow_mol[t]*water_molar_mass/water_density,
            pyunits.gal/pyunits.min)
        return cpu_water + flash_water

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

    # stack AC power
    m.fs.inverter_efficiency = pyo.Param(initialize=0.97, mutable=True)

    @m.fs.Expression(m.fs.time)
    def sofc_power_ac(fs, t):
        return pyunits.convert(fs.sofc_power_dc * fs.inverter_efficiency,
                               pyunits.kW)

    # gross plant power
    @m.fs.Expression(m.fs.time)
    def gross_power(fs, t):
        return fs.sofc_power_ac[t] + fs.steam_cycle_power[t]

    # miscellaneous BOP - scaled from BB based on NG mass flow
    @m.fs.Expression(m.fs.time)
    def misc_aux_loads(fs, t):
        ng_flow = pyunits.convert(
            m.fs.anode_mix.feed_inlet_state[t].flow_mass,
            pyunits.lb/pyunits.hr)
        ref_ng_flow = 148095*pyunits.lb/pyunits.hr
        ref_load = 396*pyunits.kW
        return ref_load*(ng_flow/ref_ng_flow)

    # auxiliary load of the plant excluding transformer losses
    @m.fs.Expression(m.fs.time)
    def pre_transformer_loss_aux_load(fs, t):
        return (fs.bfw_pump_work[t] +
                fs.condensate_pump_work[t] +
                fs.steam_turbine_aux_load[t] +
                fs.cooling_water_pump_load[t] +
                fs.cooling_tower_fan_load[t] +
                fs.misc_aux_loads[t] +
                fs.air_blower.work_mechanical[t]/0.95 +
                fs.cathode_blower.work_mechanical[t]/0.95 +
                fs.anode_blower.work_mechanical[t]/0.95 +
                fs.air_compressor_s1.work_mechanical[t]/0.96 +
                fs.air_compressor_s2.work_mechanical[t]/0.96 +
                pyunits.convert(fs.cpu.work[t], pyunits.kW))

    # transformer losses
    @m.fs.Expression(m.fs.time)
    def transformer_losses(fs, t):
        HV_aux = (
            pyunits.convert(
                fs.air_compressor_s1.work_mechanical[t]/0.96 +
                fs.air_compressor_s2.work_mechanical[t]/0.96,
                pyunits.kW) +
            pyunits.convert(
                fs.cpu.work[t],
                pyunits.kW))
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

    # used in results summary
    @m.fs.Expression(m.fs.time)
    def other_loads(fs, t):
        return (fs.auxiliary_load[t] -
                (fs.air_blower.work_mechanical[t]/0.95 +
                 fs.cathode_blower.work_mechanical[t]/0.95 +
                 fs.anode_blower.work_mechanical[t]/0.95 +
                 fs.air_compressor_s1.work_mechanical[t]/0.96 +
                 fs.air_compressor_s2.work_mechanical[t]/0.96 +
                 pyunits.convert(fs.cpu.work[t], pyunits.kW)))

    # net plant power
    @m.fs.Expression(m.fs.time)
    def net_power(fs, t):
        return fs.gross_power[t] - fs.auxiliary_load[t]

    # HHV efficiency
    @m.fs.Expression(m.fs.time)
    def efficiency_hhv(fs, t):
        ng_hhv = 908839.23*pyunits.J/pyunits.mol
        ng_lhv = 0.9016*ng_hhv
        return (fs.net_power[t] /
                pyunits.convert(
                    (ng_hhv * fs.anode_mix.feed_inlet.flow_mol[t]),
                    pyunits.kW))

    @m.fs.Expression(m.fs.time)
    def co2_emissions(fs, t):
        cpu_co2_flow = (
            fs.cpu.vent.flow_mol[t] * fs.cpu.vent.mole_frac_comp[t, 'CO2']
        )
        return pyunits.convert(
            (cpu_co2_flow) * 44.01*pyunits.g/pyunits.mol,
            pyunits.kg/pyunits.hr)

    @m.fs.Expression(m.fs.time)
    def co2_emissions_cathode(fs, t):
        air_co2_flow = (
            fs.cathode_hx.shell_outlet.flow_mol[t] *
            fs.cathode_hx.shell_outlet.mole_frac_comp[t, 'CO2']
        )
        return pyunits.convert(
            (air_co2_flow) * 44.01*pyunits.g/pyunits.mol,
            pyunits.kg/pyunits.hr)

    # CO2 emissions in kg/MWh
    @m.fs.Expression(m.fs.time)
    def carbon_intensity(fs, t):
        cpu_co2_flow = pyunits.convert(
            fs.cpu.vent.flow_mol[t] * fs.cpu.vent.mole_frac_comp[t, 'CO2'],
            pyunits.kmol/pyunits.s)

        cathode_co2_flow = (
            fs.cathode_hx.shell_outlet.flow_mol[t] *
            fs.cathode_hx.shell_outlet.mole_frac_comp[t, 'CO2'])

        co2_mass_flow = (
            (cpu_co2_flow + cathode_co2_flow) * 44.01*pyunits.g/pyunits.mol)

        return pyunits.convert(co2_mass_flow/fs.gross_power[t],
                               pyunits.kg/pyunits.MWh)

    @m.fs.Expression(m.fs.time)
    def carbon_intensity_gross(fs, t):
        mass_flow = (fs.cpu.vent.flow_mol[t] *
                     fs.cpu.vent.mole_frac_comp[t, 'CO2'] *
                     44.01*pyunits.g/pyunits.mol)
        return pyunits.convert((mass_flow/fs.gross_power[t]),
                               (pyunits.kg/pyunits.MWh))

    @m.fs.Expression(m.fs.time)
    def natural_gas_flow_mass(fs, t):
        return pyunits.convert(
            (m.fs.anode_mix.feed_inlet.flow_mol[t] *
             17.325*pyunits.g/pyunits.mol),
            pyunits.lb/pyunits.hr
            )

    @m.fs.Expression(m.fs.time)
    def cpu_exhaust_flow_vol(fs, t):
        flow_vol = (
            m.fs.cpu.vent.flow_mol[t] * 772.56*pyunits.ft**3/pyunits.kmol
        )
        return pyunits.convert(flow_vol, pyunits.ft**3/pyunits.min)

    @m.fs.Expression(m.fs.time)
    def cathode_exhaust_flow_mol(fs, t):
        flow_vol = m.fs.cathode_hrsg.control_volume.properties_out[t].flow_vol
        return pyunits.convert(flow_vol, pyunits.ft**3/pyunits.min)

    @m.fs.Expression(m.fs.time)
    def smokestack_flow_vol(fs, t):
        return m.fs.cpu_exhaust_flow_vol[t] + m.fs.cathode_exhaust_flow_mol[t]


def add_tags(m):
    tag_group = iutil.ModelTagGroup()
    m._tags_streams = tag_group
    stream_states = tables.stream_states_dict(
        tables.arcs_to_stream_dict(
            m.fs,
            descend_into=False,
            additional={
                "ng00": m.fs.anode_mix.feed_inlet,
                "air00": m.fs.air_blower.inlet,
                "asu00": m.fs.air_compressor_s1.inlet,
                "n2": m.fs.asu.N2_outlet,
                "air07": m.fs.cathode_hrsg.outlet,
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
        for c in s.mole_frac_comp:
            tag_group[f"{i}_y{c}"] = iutil.ModelTag(
                doc=f"{i}: mole percent {c}",
                expr=s.mole_frac_comp[c] * 100,
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

    other_ports = {"wat01": m.fs.flash.liq_outlet,
                   "fg04": m.fs.flash.vap_outlet,
                   "wat02": m.fs.cpu.water,
                   "co2": m.fs.cpu.pureco2,
                   "vent": m.fs.cpu.vent}

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
    tag_group["sofc_power"] = iutil.ModelTag(
        expr=m.fs.sofc_power_ac[0],
        format_string="{:.1f}",
        display_units=pyunits.MW,
    )
    tag_group["voltage"] = iutil.ModelTag(
        expr=m.fs.sofc.stack_voltage,
        format_string="{:.3f}",
        display_units="V",
    )
    tag_group["current_density"] = iutil.ModelTag(
        expr=m.fs.sofc.current_density,
        format_string="{:.0f}",
        display_units="mA/cm2",
    )
    tag_group["turbine_power"] = iutil.ModelTag(
        expr=m.fs.steam_cycle_power[0],
        format_string="{:.1f}",
        display_units=pyo.units.MW,
    )
    tag_group["gross_power"] = iutil.ModelTag(
        expr=m.fs.gross_power[0],
        format_string="{:.1f}",
        display_units=pyo.units.MW,
    )
    tag_group["asu_load"] = iutil.ModelTag(
        expr=(m.fs.air_compressor_s1.work_mechanical[0]/0.96 +
              m.fs.air_compressor_s2.work_mechanical[0]/0.96),
        format_string="{:.1f}",
        display_units=pyo.units.MW,
    )
    tag_group["cpu_load"] = iutil.ModelTag(
        expr=m.fs.cpu.work[0],
        format_string="{:.1f}",
        display_units=pyo.units.MW,
    )
    tag_group["anode_blower_load"] = iutil.ModelTag(
        expr=m.fs.anode_blower.work_mechanical[0]/0.95,
        format_string="{:.0f}",
        display_units=pyo.units.kW,
    )
    tag_group["cathode_blower_load"] = iutil.ModelTag(
        expr=m.fs.cathode_blower.work_mechanical[0]/0.95,
        format_string="{:.0f}",
        display_units=pyo.units.kW,
    )
    tag_group["air_blower_load"] = iutil.ModelTag(
        expr=m.fs.air_blower.work_mechanical[0]/0.95,
        format_string="{:.0f}",
        display_units=pyo.units.kW,
    )
    tag_group["other_loads"] = iutil.ModelTag(
        expr=m.fs.other_loads[0],
        format_string="{:.0f}",
        display_units=pyo.units.kW,
    )
    tag_group["total_aux_load"] = iutil.ModelTag(
        expr=m.fs.auxiliary_load[0],
        format_string="{:.1f}",
        display_units=pyo.units.MW,
    )
    tag_group["net_power"] = iutil.ModelTag(
        expr=m.fs.net_power[0],
        format_string="{:.1f}",
        display_units=pyo.units.MW,
    )
    tag_group["thermal_input"] = iutil.ModelTag(
        expr=m.fs.net_power[0]/m.fs.efficiency_hhv[0],
        format_string="{:.0f}",
        display_units=pyo.units.MW,
    )
    tag_group["efficiency"] = iutil.ModelTag(
        expr=m.fs.efficiency_hhv[0]*100,
        format_string="{:.2f}",
        display_units="%",
    )
    tag_group["carbon_intensity"] = iutil.ModelTag(
        expr=m.fs.carbon_intensity[0],
        format_string="{:.2f}",
        display_units=pyo.units.g/pyunits.kWh,
    )
    tag_group["natural_gas_flow"] = iutil.ModelTag(
        expr=m.fs.anode_mix.feed_inlet.flow_mol[0],
        format_string="{:.2f}",
        display_units=pyo.units.kmol/pyunits.s,
    )
    tag_group["total_variable_cost"] = iutil.ModelTag(
        expr=m.fs.costing.total_variable_OM_cost[0],
        format_string="{:.2f}",
        display_units=pyunits.USD_2018/pyunits.hour,
    )
    tag_group["natural_gas_cost"] = iutil.ModelTag(
        expr=m.fs.costing.variable_operating_costs[0, "natural gas"],
        format_string="{:.2f}",
        display_units=pyunits.USD_2018/pyunits.hour,
    )
    tag_group["water_cost"] = iutil.ModelTag(
        expr=m.fs.costing.variable_operating_costs[0, "water"],
        format_string="{:.2f}",
        display_units=pyunits.USD_2018/pyunits.hour,
    )
    tag_group["water_treatment_cost"] = iutil.ModelTag(
        expr=m.fs.costing.variable_operating_costs[0, "water treatment chemicals"],
        format_string="{:.2f}",
        display_units=pyunits.USD_2018/pyunits.hour,
    )
    tag_group["desulfurization_cost"] = iutil.ModelTag(
        expr=m.fs.costing.variable_operating_costs[0, "desulfur adsorbent"],
        format_string="{:.2f}",
        display_units=pyunits.USD_2018/pyunits.hour,
    )
    tag_group["prereformer_catalyst_cost"] = iutil.ModelTag(
        expr=m.fs.costing.variable_operating_costs[0, "prereformer catalyst"],
        format_string="{:.2f}",
        display_units=pyunits.USD_2018/pyunits.hour,
    )
    tag_group["SOFC_DC_power"] = iutil.ModelTag(
        expr=m.fs.sofc_power_dc,
        format_string="{:.2f}",
        display_units=pyunits.MW,
    )
    tag_group["SOFC_aux_load"] = iutil.ModelTag(
        expr=(m.fs.air_blower.work_mechanical[0]/0.95 +
              m.fs.cathode_blower.work_mechanical[0]/0.95 +
              m.fs.anode_blower.work_mechanical[0]/0.95),
        format_string="{:.2f}",
        display_units=pyunits.kW,
    )
    tag_group["anode_exhaust_F"] = iutil.ModelTag(
        expr=m.fs.anode_hx.shell_outlet.flow_mol[0],
        format_string="{:.2f}",
        display_units=pyunits.kmol/pyunits.s,
    )
    tag_group["anode_exhaust_T"] = iutil.ModelTag(
        expr=m.fs.anode_hx.shell_outlet.temperature[0],
        format_string="{:.2f}",
        display_units=pyunits.K,
    )
    tag_group["anode_exhaust_P"] = iutil.ModelTag(
        expr=m.fs.anode_hx.shell_outlet.pressure[0],
        format_string="{:.2f}",
        display_units=pyunits.kPa,
    )
    tag_group["anode_exhaust_xCH4"] = iutil.ModelTag(
        expr=m.fs.anode_hx.shell_outlet.mole_frac_comp[0, "CH4"],
        format_string="{:.2f}",
        display_units="",
    )
    tag_group["anode_exhaust_xCO"] = iutil.ModelTag(
        expr=m.fs.anode_hx.shell_outlet.mole_frac_comp[0, "CO"],
        format_string="{:.2f}",
        display_units="",
    )
    tag_group["anode_exhaust_xCO2"] = iutil.ModelTag(
        expr=m.fs.anode_hx.shell_outlet.mole_frac_comp[0, "CO2"],
        format_string="{:.2f}",
        display_units="",
    )
    tag_group["anode_exhaust_xH2"] = iutil.ModelTag(
        expr=m.fs.anode_hx.shell_outlet.mole_frac_comp[0, "H2"],
        format_string="{:.2f}",
        display_units="",
    )
    tag_group["anode_exhaust_xH2O"] = iutil.ModelTag(
        expr=m.fs.anode_hx.shell_outlet.mole_frac_comp[0, "H2O"],
        format_string="{:.2f}",
        display_units="",
    )
    tag_group["anode_exhaust_xN2"] = iutil.ModelTag(
        expr=m.fs.anode_hx.shell_outlet.mole_frac_comp[0, "N2"],
        format_string="{:.2f}",
        display_units="",
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

    infilename = os.path.join(this_file_dir(), "sofc_template.svg")
    with open(infilename, "r") as f:
        s = svg_tag(svg=f, tag_group=m._tags_streams, outfile=None)
    s = svg_tag(svg=s, tag_group=m._tags_output, outfile=fname)
    if fname is None:
        return s


def get_model():
    m = pyo.ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    add_properties(m)
    add_models(m)
    add_arcs(m)
    add_constraints(m)
    add_result_expressions(m)
    set_inputs(m)
    scale_flowsheet(m)
    return m


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

    m = pyo.ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    add_properties(m)
    add_models(m)
    add_arcs(m)
    add_constraints(m)
    set_inputs(m)

    scale_flowsheet(m)
    initialize(m)
    solver.solve(m, tee=True)

    add_tags(m)
    make_stream_table(m._tags_streams).to_csv("data_tabulated/sofc_streams.csv")



