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
NGCC HRSG subsystem for a 690MWe with 97% CO2 capture
"""

__author__ = ["M. Zamarripa", "John Eslick"]

import os
from pathlib import Path

import pandas as pd

from pyomo.common.fileutils import this_file_dir
import pyomo.environ as pyo
from pyomo.network import Arc

import idaes.logger as idaeslog
import idaes.core.util.tables as ta
from idaes.core.util.tags import svg_tag
from idaes.core.util.initialization import propagate_state
from idaes.core import FlowsheetBlockData, declare_process_block_class
import idaes.core.util as iutil
from idaes.core.solvers import get_solver
import idaes.core.util.scaling as iscale
from idaes.models.properties import iapws95
from idaes.models_extra.power_generation.properties import FlueGasParameterBlock
from idaes.models_extra.power_generation.unit_models.helm.phase_separator import (
    HelmPhaseSeparator,
)
from idaes.models_extra.power_generation.unit_models.helm import (
    HelmMixer,
    MomentumMixingType,
    HelmSplitter,
    HelmValve,
    HelmIsentropicCompressor as WaterPump,
)
from idaes.models.unit_models import Mixer, Separator as Splitter
from idaes.models.unit_models.heat_exchanger import (
    HeatExchanger,
    HeatExchangerFlowPattern,
    delta_temperature_lmtd_callback as delta_temp_cb,
    delta_temperature_lmtd_callback,
)
from idaes.models_extra.power_generation.unit_models.boiler_heat_exchanger import (
    BoilerHeatExchanger,
    TubeArrangement,
)


@declare_process_block_class(
    "HrsgFlowsheet",
    doc=(
        "The HRSG Flowsheet is base on NETL report 'Cost and Performance Baseline "
        "for Fossil Energy Plants Volume 1: Bituminous Coal and Natural Gas to "
        "Electricity.' Sept 2019, Case B31B. This flowsheet is intended for steady "
        "state off-design calculations."
    ),
)
class HrsgFlowsheetData(FlowsheetBlockData):
    def build(self):
        super().build()
        self._add_properties()
        self._add_unit_models()
        self._add_flowsheet_constraints()
        self._add_arcs()
        self._initial_design_variables()
        self._set_scaling_factors()
        self._stream_tags()

    def _add_properties(self):
        """Add property parameter blocks for steam (prop_water) and flue gas
        (prop_gas).
        """
        self.prop_water = iapws95.Iapws95ParameterBlock()
        self.prop_gas = FlueGasParameterBlock(
            components=["N2", "O2", "CO2", "H2O"]
        )

    def _add_unit_models(self):
        """Add process unit models"""
        # short refernce to property parameter blocks
        prop_water = self.prop_water
        prop_gas = self.prop_gas

        ######### LP Section ###########
        self.econ_lp = BoilerHeatExchanger(
            doc="LP Economizer",
            delta_temperature_callback=delta_temp_cb,
            cold_side_name="tube",
            hot_side_name="shell",
            tube={"property_package": prop_water,
                  "has_pressure_change": False,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": False,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Liq",
            has_radiation=False,
        )
        self.mixer1 = HelmMixer(
            doc="Mixer for econ_lp outlet and NG preheater return streams",
            dynamic=False,
            property_package=prop_water,
            momentum_mixing_type=MomentumMixingType.none,
            inlet_list=["econ_lp", "Preheater"],
        )
        self.drum_lp = HelmPhaseSeparator(
            doc="Phase seperator for LP evaporator (parital evaporator)",
            property_package=prop_water,
        )
        self.evap_lp = HeatExchanger(
            doc="LP evaporator heat exchanger section",
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": prop_gas},
            tube={"property_package": prop_water},
            delta_temperature_callback=delta_temperature_lmtd_callback,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
        )
        self.mixer_soec = HelmMixer(
            doc="Mixer for evap_lp outlet and soec makeup",
            dynamic=False,
            property_package=prop_water,
            momentum_mixing_type=MomentumMixingType.none,
            inlet_list=["main", "soec_makeup"],
        )
        self.split_fg_lp = Splitter(
            doc="LP superheater flue bypass gas splitter",
            property_package=prop_gas,
            ideal_separation=False,
            outlet_list=["toLP_SH", "toMixer"],
        )
        self.mixer_lp2 = Mixer(
            doc="LP section flue gas bypass mixer",
            property_package=prop_gas,
            inlet_list=["fromLP_SH", "bypass"],
        )
        self.sh_lp = BoilerHeatExchanger(
            doc="LP superheater",
            delta_temperature_callback=delta_temp_cb,
            hot_side_name="shell",
            cold_side_name="tube",
            tube={"property_package": prop_water,
                  "has_pressure_change": False,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": False,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Vap",
            has_radiation=False,
        )
        self.splitter1 = HelmSplitter(
            doc="LP liquid split to IP and HP pumps",
            property_package=prop_water,
            outlet_list=["toIP", "toHP"],
        )
        self.pump_ip = WaterPump(
            doc="Intermediate pressure pump",
            property_package=prop_water,
        )
        self.pump_hp = WaterPump(
            doc="High pressure pump",
            property_package=prop_water,
        )
        ######### IP Section ###########
        self.econ_ip1 = BoilerHeatExchanger(
            doc="IP ecomonmizer part 1",
            delta_temperature_callback=delta_temp_cb,
            hot_side_name="shell",
            cold_side_name="tube",
            tube={"property_package": prop_water,
                  "has_pressure_change": True,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": True,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Liq",
            has_radiation=False,
        )
        self.splitter_ip1 = HelmSplitter(
            doc="IP economizer hot water split for natural gas preheater",
            property_package=prop_water,
            outlet_list=["toIP_ECON2", "toNGPH"],
        )
        self.econ_ip2 = BoilerHeatExchanger(
            doc="IP ecomonmizer part 2",
            delta_temperature_callback=delta_temp_cb,
            hot_side_name="shell",
            cold_side_name="tube",
            tube={"property_package": prop_water,
                  "has_pressure_change": True,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": True,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Liq",
            has_radiation=False,
        )
        self.evap_ip = HeatExchanger(
            doc="IP evaporator (total evaporator)",
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": prop_gas},
            tube={"property_package": prop_water},
            delta_temperature_callback=delta_temperature_lmtd_callback,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
        )
        self.sh_ip1 = BoilerHeatExchanger(
            doc="IP superheater 1",
            delta_temperature_callback=delta_temp_cb,
            hot_side_name="shell",
            cold_side_name="tube",
            tube={"property_package": prop_water,
                  "has_pressure_change": True,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": True,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Vap",
            has_radiation=False,
        )
        self.mixer_ip1 = HelmMixer(
            doc="Mixer for econ_lp outlet and Preheater streams",
            dynamic=False,
            property_package=prop_water,
            momentum_mixing_type=MomentumMixingType.none,
            inlet_list=["sh_ip1", "Cold_reheat"],
        )
        self.splitter_ip2 = HelmSplitter(
            doc="IP Splitter 2, for ejector, reclaimer and dryer",
            property_package=prop_water,
            outlet_list=["Cold_reheat", "toEjector", "toReclaimer", "toDryer"],
        )
        self.sh_ip2 = BoilerHeatExchanger(
            doc="IP superheater 2",
            delta_temperature_callback=delta_temp_cb,
            hot_side_name="shell",
            cold_side_name="tube",
            tube={"property_package": prop_water,
                  "has_pressure_change": True,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": True,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Vap",
            has_radiation=False,
        )
        self.sh_ip3 = BoilerHeatExchanger(
            doc="IP superheater 3",
            delta_temperature_callback=delta_temp_cb,
            hot_side_name="shell",
            cold_side_name="tube",
            tube={"property_package": prop_water,
                  "has_pressure_change": True,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": True,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Vap",
            has_radiation=False,
        )
        self.econ_hp1 = BoilerHeatExchanger(
            doc="HP economizer 1",
            delta_temperature_callback=delta_temp_cb,
            hot_side_name="shell",
            cold_side_name="tube",
            tube={"property_package": prop_water,
                  "has_pressure_change": True,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": True,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Liq",
            has_radiation=False,
        )
        self.econ_hp2 = BoilerHeatExchanger(
            doc="HP economizer 2",
            delta_temperature_callback=delta_temp_cb,
            hot_side_name="shell",
            cold_side_name="tube",
            tube={"property_package": prop_water,
                  "has_pressure_change": True,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": True,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Liq",
            has_radiation=False,
        )
        self.econ_hp3 = BoilerHeatExchanger(
            doc="HP economizer 3",
            delta_temperature_callback=delta_temp_cb,
            hot_side_name="shell",
            cold_side_name="tube",
            tube={"property_package": prop_water,
                  "has_pressure_change": True,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": True,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Liq",
            has_radiation=False,
        )
        self.econ_hp4 = BoilerHeatExchanger(
            doc="HP economizer 4",
            delta_temperature_callback=delta_temp_cb,
            hot_side_name="shell",
            cold_side_name="tube",
            tube={"property_package": prop_water,
                  "has_pressure_change": True,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": True,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Liq",
            has_radiation=False,
        )
        self.econ_hp5 = BoilerHeatExchanger(
            doc="HP economizer 5",
            delta_temperature_callback=delta_temp_cb,
            hot_side_name="shell",
            cold_side_name="tube",
            tube={"property_package": prop_water,
                  "has_pressure_change": True,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": True,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Liq",
            has_radiation=False,
        )
        self.evap_hp_valve = HelmValve(
            doc="HP evaporator valve",
            property_package=prop_water,
        )
        self.evap_hp_valve.pressure_flow_equation.deactivate()
        self.evap_hp = HeatExchanger(
            doc="HP evaporator (total evaporator)",
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": prop_gas},
            tube={"property_package": prop_water},
            delta_temperature_callback=delta_temperature_lmtd_callback,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
        )
        self.sh_hp1 = BoilerHeatExchanger(
            doc="HP superheater 1",
            delta_temperature_callback=delta_temp_cb,
            hot_side_name="shell",
            cold_side_name="tube",
            tube={"property_package": prop_water,
                  "has_pressure_change": True,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": True,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Vap",
            has_radiation=False,
        )
        self.sh_hp2 = BoilerHeatExchanger(
            doc="HP superheater 2",
            delta_temperature_callback=delta_temp_cb,
            hot_side_name="shell",
            cold_side_name="tube",
            tube={"property_package": prop_water,
                  "has_pressure_change": True,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": True,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Vap",
            has_radiation=False,
        )
        self.sh_hp3 = BoilerHeatExchanger(
            doc="HP superheater 3",
            delta_temperature_callback=delta_temp_cb,
            hot_side_name="shell",
            cold_side_name="tube",
            tube={"property_package": prop_water,
                  "has_pressure_change": True,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": True,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Vap",
            has_radiation=False,
        )
        self.sh_hp4 = BoilerHeatExchanger(
            doc="HP superheater 4",
            delta_temperature_callback=delta_temp_cb,
            hot_side_name="shell",
            cold_side_name="tube",
            tube={"property_package": prop_water,
                  "has_pressure_change": True,},
            shell={"property_package": prop_gas,
                   "has_pressure_change": True,},
            has_holdup=False,
            flow_pattern=HeatExchangerFlowPattern.countercurrent,
            tube_arrangement=TubeArrangement.inLine,
            cold_side_water_phase="Vap",
            has_radiation=False,
        )

    def _add_flowsheet_constraints(self):
        """Add additional flowsheet constraints."""

        @self.evap_ip.Constraint(
            self.config.time, doc="Everything evaporates in IP evaporator"
        )
        def ip_sat_vap_eqn(b, t):
            return (
                b.tube.properties_out[t].enth_mol / 1e4
                == (b.tube.properties_out[t].enth_mol_sat_phase["Vap"] + 30) / 1e4
            )

        @self.evap_hp.Constraint(
            self.config.time, doc="Everything evaporates in HP evaporator"
        )
        def hp_sat_vap_eqn(b, t):
            return (
                b.tube.properties_out[t].enth_mol / 1e4
                == (b.tube.properties_out[t].enth_mol_sat_phase["Vap"] + 30) / 1e4
            )

        @self.mixer1.Constraint(self.config.time, doc="Mixed state pressure eqn.")
        def mixer1_pressure_eqn(b, t):
            return b.mixed_state[t].pressure == b.econ_lp_state[t].pressure

        @self.mixer_soec.Constraint(self.config.time, doc="Mixed state pressure eqn.")
        def mixer_soec_pressure_eqn(b, t):
            return b.mixed_state[t].pressure == b.main_state[t].pressure

        @self.mixer_ip1.Constraint(self.config.time, doc="Mixed state pressure eqn.")
        def mixer_ip1_pressure_eqn(b, t):
            return b.mixed_state[t].pressure == b.Cold_reheat_state[t].pressure

    def _add_arcs(self):
        ######### LP Section ###########
        self.lp02 = Arc(
            doc="econ_lp to mixer1",
            source=self.econ_lp.tube_outlet,
            destination=self.mixer1.econ_lp,
        )
        self.lp04 = Arc(
            doc="mixer1 to evap_lp",
            source=self.mixer1.outlet,
            destination=self.evap_lp.tube_inlet,
        )
        self.lp05 = Arc(
            doc="evap_lp to drum_lp",
            source=self.evap_lp.tube_outlet,
            destination=self.mixer_soec.main,
        )
        self.lp13 = Arc(
            doc="evap_lp to drum_lp",
            source=self.mixer_soec.outlet,
            destination=self.drum_lp.inlet,
        )
        self.lp10 = Arc(
            doc="drum_lp vapor to sh_lp",
            source=self.drum_lp.vap_outlet,
            destination=self.sh_lp.tube_inlet,
        )
        self.lp06 = Arc(
            doc="drum_lp liquid to splitter1",
            source=self.drum_lp.liq_outlet,
            destination=self.splitter1.inlet,
        )
        self.lp08 = Arc(
            doc="splitter1 to pump_ip",
            source=self.splitter1.toIP,
            destination=self.pump_ip.inlet,
        )
        self.lp09 = Arc(
            doc="splitter1 to pump_hp",
            source=self.splitter1.toHP,
            destination=self.pump_hp.inlet,
        )
        ######### IP Section ###########
        self.ip01 = Arc(
            doc="pump_ip to econ_ip1",
            source=self.pump_ip.outlet,
            destination=self.econ_ip1.tube_inlet,
        )
        self.ip02 = Arc(
            doc="econ_ip1 to splitter_ip1",
            source=self.econ_ip1.tube_outlet,
            destination=self.splitter_ip1.inlet,
        )
        self.ip03 = Arc(
            doc="splitter_ip1 to econ_ip2",
            source=self.splitter_ip1.toIP_ECON2,
            destination=self.econ_ip2.tube_inlet,
        )
        self.ip05 = Arc(
            doc="econ_ip2 to evap_ip",
            source=self.econ_ip2.tube_outlet,
            destination=self.evap_ip.tube_inlet,
        )
        self.ip06 = Arc(
            doc="evap_ip to IPSH1",
            source=self.evap_ip.tube_outlet,
            destination=self.sh_ip1.tube_inlet,
        )
        self.ip07 = Arc(
            doc="sh_ip1 to mixer_ip1",
            source=self.sh_ip1.tube_outlet,
            destination=self.mixer_ip1.sh_ip1,
        )
        self.ip15 = Arc(
            doc="splitter_ip2 to Cold_reheat",
            source=self.splitter_ip2.Cold_reheat,
            destination=self.mixer_ip1.Cold_reheat,
        )
        self.ip08 = Arc(
            doc="mixer_ip1 to sh_ip2",
            source=self.mixer_ip1.outlet,
            destination=self.sh_ip2.tube_inlet,
        )
        self.ip09 = Arc(
            doc="sh_ip2 to IPSH3",
            source=self.sh_ip2.tube_outlet,
            destination=self.sh_ip3.tube_inlet,
        )
        ######### HP Section ###########
        self.hp01 = Arc(
            doc="pump_hp to HP_ECON",
            source=self.pump_hp.outlet,
            destination=self.econ_hp1.tube_inlet,
        )
        self.hp02 = Arc(
            doc="HP_ECON to econ_hp2",
            source=self.econ_hp1.tube_outlet,
            destination=self.econ_hp2.tube_inlet,
        )
        self.hp03 = Arc(
            doc="econ_hp3 to econ_hp4",
            source=self.econ_hp2.tube_outlet,
            destination=self.econ_hp3.tube_inlet,
        )
        self.hp04 = Arc(
            doc="econ_hp3 to econ_hp4",
            source=self.econ_hp3.tube_outlet,
            destination=self.econ_hp4.tube_inlet,
        )
        self.hp05 = Arc(
            doc="econ_hp4 to econ_hp5",
            source=self.econ_hp4.tube_outlet,
            destination=self.econ_hp5.tube_inlet,
        )
        self.hp06 = Arc(
            doc="econ_hp5 to evap_hp",
            source=self.econ_hp5.tube_outlet,
            destination=self.evap_hp_valve.inlet,
        )
        self.hp06b = Arc(
            doc="evap_hp to sh_hp1",
            source=self.evap_hp_valve.outlet,
            destination=self.evap_hp.tube_inlet,
        )
        self.hp07 = Arc(
            doc="evap_hp to sh_hp1",
            source=self.evap_hp.tube_outlet,
            destination=self.sh_hp1.tube_inlet,
        )
        self.hp08 = Arc(
            doc="sh_hp1 to sh_hp2",
            source=self.sh_hp1.tube_outlet,
            destination=self.sh_hp2.tube_inlet,
        )
        self.hp09 = Arc(
            doc="sh_hp2 to sh_hp3",
            source=self.sh_hp2.tube_outlet,
            destination=self.sh_hp3.tube_inlet,
        )
        self.hp10 = Arc(
            doc="Flue gas from sh_hp3 to sh_hp4",
            source=self.sh_hp3.tube_outlet,
            destination=self.sh_hp4.tube_inlet,
        )
        self.g09 = Arc(
            doc="Flue gas from sh_hp4 to sh_ip3",
            source=self.sh_hp4.shell_outlet,
            destination=self.sh_ip3.shell_inlet,
        )
        self.g10 = Arc(
            doc="Flue gas from sh_ip3 to sh_hp3",
            source=self.sh_ip3.shell_outlet,
            destination=self.sh_hp3.shell_inlet,
        )
        self.g11 = Arc(
            doc="Flue gas from sh_hp3 to sh_hp2",
            source=self.sh_hp3.shell_outlet,
            destination=self.sh_hp2.shell_inlet,
        )
        self.g12 = Arc(
            doc="Flue gas from sh_hp2 to sh_ip2",
            source=self.sh_hp2.shell_outlet,
            destination=self.sh_ip2.shell_inlet,
        )
        self.g13 = Arc(
            doc="Flue gas from sh_ip2 to sh_hp1",
            source=self.sh_ip2.shell_outlet,
            destination=self.sh_hp1.shell_inlet,
        )
        self.g14 = Arc(
            doc="Flue gas from sh_hp1 to evap_hp",
            source=self.sh_hp1.shell_outlet,
            destination=self.evap_hp.shell_inlet,
        )
        self.g15 = Arc(
            doc="Flue gas from evap_hp to econ_hp5",
            source=self.evap_hp.shell_outlet,
            destination=self.econ_hp5.shell_inlet,
        )
        self.g16 = Arc(
            doc="Flue gas from econ_hp5 to sh_ip1",
            source=self.econ_hp5.shell_outlet,
            destination=self.sh_ip1.shell_inlet,
        )
        self.g17 = Arc(
            doc="Flue gas from sh_ip1 to econ_hp4",
            source=self.sh_ip1.shell_outlet,
            destination=self.econ_hp4.shell_inlet,
        )
        self.g18 = Arc(
            doc="Flue gas from econ_hp4 to econ_hp3",
            source=self.econ_hp4.shell_outlet,
            destination=self.econ_hp3.shell_inlet,
        )
        self.g19 = Arc(
            doc="Flue gas from econ_hp3 to split_fg_lp",
            source=self.econ_hp3.shell_outlet,
            destination=self.split_fg_lp.inlet,
        )
        self.g20 = Arc(
            doc="Flue gas from split_fg_lp to sh_lp",
            source=self.split_fg_lp.toLP_SH,
            destination=self.sh_lp.shell_inlet,
        )
        self.g21 = Arc(
            doc="Flue gas from sh_lp to mixer_lp2",
            source=self.sh_lp.shell_outlet,
            destination=self.mixer_lp2.fromLP_SH,
        )
        self.g22 = Arc(
            doc="Flue gas from split_fg_lp to mixer_lp2",
            source=self.split_fg_lp.toMixer,
            destination=self.mixer_lp2.bypass,
        )
        self.g23 = Arc(
            doc="Flue gas from mixer_lp2 to evap_ip",
            source=self.mixer_lp2.outlet,
            destination=self.evap_ip.shell_inlet,
        )
        self.g24 = Arc(
            doc="Flue gas from evap_ip to econ_ip2",
            source=self.evap_ip.shell_outlet,
            destination=self.econ_ip2.shell_inlet,
        )
        self.g25 = Arc(
            doc="Flue gas from econ_ip2 to econ_hp2",
            source=self.econ_ip2.shell_outlet,
            destination=self.econ_hp2.shell_inlet,
        )
        self.g26 = Arc(
            doc="Flue gas from econ_hp2 to econ_ip1",
            source=self.econ_hp2.shell_outlet,
            destination=self.econ_ip1.shell_inlet,
        )
        self.g27 = Arc(
            doc="Flue gas from econ_ip1 to econ_hp1",
            source=self.econ_ip1.shell_outlet,
            destination=self.econ_hp1.shell_inlet,
        )
        self.g28 = Arc(
            doc="Flue gas from econ_hp1 to evap_lp",
            source=self.econ_hp1.shell_outlet,
            destination=self.evap_lp.shell_inlet,
        )
        self.g29 = Arc(
            doc="Flue gas from evap_lp to econ_lp",
            source=self.evap_lp.shell_outlet,
            destination=self.econ_lp.shell_inlet,
        )
        pyo.TransformationFactory("network.expand_arcs").apply_to(self)

    def _initial_design_variables(self):
        """Set the basic inputs for the unit models including geometry, design
        and operating variables.
        """
        ######### LP Section ###########
        self.econ_lp.tube_di.fix(0.038)
        self.econ_lp.tube_thickness.fix(0.003)
        self.econ_lp.pitch_x.fix(0.09)
        self.econ_lp.pitch_y.fix(0.09)
        self.econ_lp.tube_length.fix(94.08 / 2)
        self.econ_lp.tube_nrow.fix(4)
        self.econ_lp.tube_ncol.fix(78)
        self.econ_lp.nrow_inlet.fix(2)
        self.econ_lp.delta_elevation.fix(1)
        self.econ_lp.tube_r_fouling = 0.000176
        self.econ_lp.shell_r_fouling = 0.00088
        self.econ_lp.fcorrection_htc.fix(1.5)
        self.econ_lp.fcorrection_dp_tube.fix(1.0)
        self.econ_lp.fcorrection_dp_shell.fix(0.52)
        self.splitter1.split_fraction[0, "toIP"].fix(0.20)

        self.pump_ip.efficiency_isentropic.fix(0.80)
        self.pump_hp.efficiency_isentropic.fix(0.80)

        self.evap_lp.area.fix(10558.76)
        self.evap_lp.overall_heat_transfer_coefficient.fix(212)

        self.mixer_soec.soec_makeup.flow_mol.fix(0)
        self.mixer_soec.soec_makeup.pressure.fix(8 * pyo.units.bar)
        self.mixer_soec.soec_makeup.enth_mol.fix(
            iapws95.htpx(P=8 * pyo.units.bar, x=0.2)
        )

        self.sh_lp.tube_di.fix(0.051)
        self.sh_lp.tube_thickness.fix(0.003)
        self.sh_lp.pitch_x.fix(0.11)
        self.sh_lp.pitch_y.fix(0.11)
        self.sh_lp.tube_length.fix(7 * 9)
        self.sh_lp.tube_nrow.fix(30)
        self.sh_lp.tube_ncol.fix(10 * 3)
        self.sh_lp.nrow_inlet.fix(10)
        self.sh_lp.delta_elevation.fix(1)
        self.sh_lp.tube_r_fouling = 0.000176
        self.sh_lp.shell_r_fouling = 0.00088
        self.sh_lp.fcorrection_htc.fix(1.0)
        self.sh_lp.fcorrection_dp_tube.fix(1.0)
        self.sh_lp.fcorrection_dp_shell.fix(0.52)

        ######### IP Section ###########
        self.econ_ip1.tube_di.fix(0.038)
        self.econ_ip1.tube_thickness.fix(0.003)
        self.econ_ip1.pitch_x.fix(0.09)
        self.econ_ip1.pitch_y.fix(0.09)
        self.econ_ip1.tube_length.fix(7 * 14)
        self.econ_ip1.tube_nrow.fix(6)
        self.econ_ip1.tube_ncol.fix(12)
        self.econ_ip1.nrow_inlet.fix(3)
        self.econ_ip1.delta_elevation.fix(1.0)
        self.econ_ip1.tube_r_fouling = 0.000176
        self.econ_ip1.shell_r_fouling = 0.00088
        self.econ_ip1.fcorrection_htc.fix(1.0)
        self.econ_ip1.fcorrection_dp_tube.fix(1.0)
        self.econ_ip1.fcorrection_dp_shell.fix(0.52)

        self.splitter_ip1.split_fraction[0, "toNGPH"].fix(0.4592)

        self.econ_ip2.tube_di.fix(0.051)
        self.econ_ip2.tube_thickness.fix(0.003)
        self.econ_ip2.pitch_x.fix(0.09)
        self.econ_ip2.pitch_y.fix(0.09)
        self.econ_ip2.tube_length.fix(7)
        self.econ_ip2.tube_nrow.fix(15)
        self.econ_ip2.tube_ncol.fix(71)
        self.econ_ip2.nrow_inlet.fix(2)
        self.econ_ip2.delta_elevation.fix(12)
        self.econ_ip2.tube_r_fouling = 0.000176
        self.econ_ip2.shell_r_fouling = 0.00088
        self.econ_ip2.fcorrection_htc.fix(1.0)
        self.econ_ip2.fcorrection_dp_tube.fix(1.0)
        self.econ_ip2.fcorrection_dp_shell.fix(0.52)

        self.evap_ip.area.fix(11000.0)
        self.evap_ip.overall_heat_transfer_coefficient.fix(212)

        self.sh_ip1.tube_di.fix(0.051)
        self.sh_ip1.tube_thickness.fix(0.003)
        self.sh_ip1.pitch_x.fix(0.11)
        self.sh_ip1.pitch_y.fix(0.11)
        self.sh_ip1.tube_length.fix(7 * 4)
        self.sh_ip1.tube_nrow.fix(10)
        self.sh_ip1.tube_ncol.fix(8)
        self.sh_ip1.nrow_inlet.fix(5)
        self.sh_ip1.delta_elevation.fix(1)
        self.sh_ip1.tube_r_fouling = 0.000176
        self.sh_ip1.shell_r_fouling = 0.00088
        self.sh_ip1.fcorrection_htc.fix(1.0)
        self.sh_ip1.fcorrection_dp_tube.fix(1.0)
        self.sh_ip1.fcorrection_dp_shell.fix(0.52)

        self.sh_ip2.tube_di.fix(0.0635)
        self.sh_ip2.tube_thickness.fix(0.003)
        self.sh_ip2.pitch_x.fix(0.11)
        self.sh_ip2.pitch_y.fix(0.11)
        self.sh_ip2.tube_length.fix(7 * 4)
        self.sh_ip2.tube_nrow.fix(16)
        self.sh_ip2.tube_ncol.fix(37)
        self.sh_ip2.nrow_inlet.fix(4)
        self.sh_ip2.delta_elevation.fix(1)
        self.sh_ip2.tube_r_fouling = 0.000176
        self.sh_ip2.shell_r_fouling = 0.00088
        self.sh_ip2.fcorrection_htc.fix(1.0)
        self.sh_ip2.fcorrection_dp_tube.fix(1.0)
        self.sh_ip2.fcorrection_dp_shell.fix(0.52)

        self.sh_ip3.tube_di.fix(0.0635)
        self.sh_ip3.tube_thickness.fix(0.003)
        self.sh_ip3.pitch_x.fix(0.11)
        self.sh_ip3.pitch_y.fix(0.11)
        self.sh_ip3.tube_length.fix(7 * 10)
        self.sh_ip3.tube_nrow.fix(16)
        self.sh_ip3.tube_ncol.fix(37)
        self.sh_ip3.nrow_inlet.fix(4)
        self.sh_ip3.delta_elevation.fix(1)
        self.sh_ip3.tube_r_fouling = 0.000176
        self.sh_ip3.shell_r_fouling = 0.00088
        self.sh_ip3.fcorrection_htc.fix(1.14773)
        self.sh_ip3.fcorrection_dp_tube.fix(1.0)
        self.sh_ip3.fcorrection_dp_shell.fix(0.52)

        ######### HP Section ###########
        self.econ_hp1.tube_di.fix(0.051)
        self.econ_hp1.tube_thickness.fix(0.003)
        self.econ_hp1.pitch_x.fix(0.1)
        self.econ_hp1.pitch_y.fix(0.1)
        self.econ_hp1.tube_length.fix(7 * 10)
        self.econ_hp1.tube_nrow.fix(8)
        self.econ_hp1.tube_ncol.fix(61)
        self.econ_hp1.nrow_inlet.fix(4)
        self.econ_hp1.delta_elevation.fix(1.0)
        self.econ_hp1.tube_r_fouling = 0.000176
        self.econ_hp1.shell_r_fouling = 0.00088
        self.econ_hp1.fcorrection_htc.fix(1.0)
        self.econ_hp1.fcorrection_dp_tube.fix(0.05)
        self.econ_hp1.fcorrection_dp_shell.fix(0.52)

        self.econ_hp2.tube_di.fix(0.051)
        self.econ_hp2.tube_thickness.fix(0.003)
        self.econ_hp2.pitch_x.fix(0.1)
        self.econ_hp2.pitch_y.fix(0.1)
        self.econ_hp2.tube_length.fix(7 * 10)
        self.econ_hp2.tube_nrow.fix(8)
        self.econ_hp2.tube_ncol.fix(61)
        self.econ_hp2.nrow_inlet.fix(4)
        self.econ_hp2.delta_elevation.fix(1.0)
        self.econ_hp2.tube_r_fouling = 0.000176
        self.econ_hp2.shell_r_fouling = 0.00088
        self.econ_hp2.fcorrection_htc.fix(1.0)
        self.econ_hp2.fcorrection_dp_tube.fix(0.05)
        self.econ_hp2.fcorrection_dp_shell.fix(0.52)

        self.econ_hp3.tube_di.fix(0.051)
        self.econ_hp3.tube_thickness.fix(0.003)
        self.econ_hp3.pitch_x.fix(0.1)
        self.econ_hp3.pitch_y.fix(0.1)
        self.econ_hp3.tube_length.fix(7 * 12)
        self.econ_hp3.tube_nrow.fix(8)
        self.econ_hp3.tube_ncol.fix(61)
        self.econ_hp3.nrow_inlet.fix(4)
        self.econ_hp3.delta_elevation.fix(1.0)
        self.econ_hp3.tube_r_fouling = 0.000176
        self.econ_hp3.shell_r_fouling = 0.00088
        self.econ_hp3.fcorrection_htc.fix(1.0)
        self.econ_hp3.fcorrection_dp_tube.fix(0.05)
        self.econ_hp3.fcorrection_dp_shell.fix(0.52)

        self.econ_hp4.tube_di.fix(0.051)
        self.econ_hp4.tube_thickness.fix(0.003)
        self.econ_hp4.pitch_x.fix(0.1)
        self.econ_hp4.pitch_y.fix(0.1)
        self.econ_hp4.tube_length.fix(7 * 10)
        self.econ_hp4.tube_nrow.fix(8)
        self.econ_hp4.tube_ncol.fix(61)
        self.econ_hp4.nrow_inlet.fix(4)
        self.econ_hp4.delta_elevation.fix(1.0)
        self.econ_hp4.tube_r_fouling = 0.000176
        self.econ_hp4.shell_r_fouling = 0.00088
        self.econ_hp4.fcorrection_htc.fix(1.0)
        self.econ_hp4.fcorrection_dp_tube.fix(0.05)
        self.econ_hp4.fcorrection_dp_shell.fix(0.52)

        self.econ_hp5.tube_di.fix(0.051)
        self.econ_hp5.tube_thickness.fix(0.003)
        self.econ_hp5.pitch_x.fix(0.1)
        self.econ_hp5.pitch_y.fix(0.1)
        self.econ_hp5.tube_length.fix(7 * 10)
        self.econ_hp5.tube_nrow.fix(8)
        self.econ_hp5.tube_ncol.fix(61)
        self.econ_hp5.nrow_inlet.fix(4)
        self.econ_hp5.delta_elevation.fix(1.0)
        self.econ_hp5.tube_r_fouling = 0.000176
        self.econ_hp5.shell_r_fouling = 0.00088
        self.econ_hp5.fcorrection_htc.fix(1.0)
        self.econ_hp5.fcorrection_dp_tube.fix(0.05)
        self.econ_hp5.fcorrection_dp_shell.fix(0.52)

        self.evap_hp_valve.deltaP.fix(-7e6)
        self.evap_hp.area.fix(11535.367)
        self.evap_hp.overall_heat_transfer_coefficient.fix(212)

        self.sh_hp1.tube_di.fix(0.0635)
        self.sh_hp1.tube_thickness.fix(0.003)
        self.sh_hp1.pitch_x.fix(0.11)
        self.sh_hp1.pitch_y.fix(0.11)
        self.sh_hp1.tube_length.fix(7 * 10)
        self.sh_hp1.tube_nrow.fix(16)
        self.sh_hp1.tube_ncol.fix(37)
        self.sh_hp1.nrow_inlet.fix(4)
        self.sh_hp1.delta_elevation.fix(1)
        self.sh_hp1.tube_r_fouling = 0.000176
        self.sh_hp1.shell_r_fouling = 0.00088
        self.sh_hp1.fcorrection_htc.fix(0.7)
        self.sh_hp1.fcorrection_dp_tube.fix(1.0)
        self.sh_hp1.fcorrection_dp_shell.fix(0.52)

        self.sh_hp2.tube_di.fix(0.0635)
        self.sh_hp2.tube_thickness.fix(0.003)
        self.sh_hp2.pitch_x.fix(0.11)
        self.sh_hp2.pitch_y.fix(0.11)
        self.sh_hp2.tube_length.fix(7 * 10)
        self.sh_hp2.tube_nrow.fix(16)
        self.sh_hp2.tube_ncol.fix(37)
        self.sh_hp2.nrow_inlet.fix(4)
        self.sh_hp2.delta_elevation.fix(1)
        self.sh_hp2.tube_r_fouling = 0.000176
        self.sh_hp2.shell_r_fouling = 0.00088
        self.sh_hp2.fcorrection_htc.fix(0.7)
        self.sh_hp2.fcorrection_dp_tube.fix(1.0)
        self.sh_hp2.fcorrection_dp_shell.fix(0.52)

        self.sh_hp3.tube_di.fix(0.0635)
        self.sh_hp3.tube_thickness.fix(0.003)
        self.sh_hp3.pitch_x.fix(0.11)
        self.sh_hp3.pitch_y.fix(0.11)
        self.sh_hp3.tube_length.fix(7 * 10)
        self.sh_hp3.tube_nrow.fix(16)
        self.sh_hp3.tube_ncol.fix(37)
        self.sh_hp3.nrow_inlet.fix(4)
        self.sh_hp3.delta_elevation.fix(1)
        self.sh_hp3.tube_r_fouling = 0.000176
        self.sh_hp3.shell_r_fouling = 0.00088
        self.sh_hp3.fcorrection_htc.fix(0.7)
        self.sh_hp3.fcorrection_dp_tube.fix(1.0)
        self.sh_hp3.fcorrection_dp_shell.fix(0.52)

        self.sh_hp4.tube_di.fix(0.0635)
        self.sh_hp4.tube_thickness.fix(0.003)
        self.sh_hp4.pitch_x.fix(0.11)
        self.sh_hp4.pitch_y.fix(0.11)
        self.sh_hp4.tube_length.fix(7 * 10)
        self.sh_hp4.tube_nrow.fix(16)
        self.sh_hp4.tube_ncol.fix(37)
        self.sh_hp4.nrow_inlet.fix(4)
        self.sh_hp4.delta_elevation.fix(1)
        self.sh_hp4.tube_r_fouling = 0.000176
        self.sh_hp4.shell_r_fouling = 0.00088
        self.sh_hp4.fcorrection_htc.fix(0.49584)
        self.sh_hp4.fcorrection_dp_tube.fix(1.0)
        self.sh_hp4.fcorrection_dp_shell.fix(0.52)

    def _set_scaling_factors(self):
        """Set flowsheet scaling factors"""
        hx_list = [  # list of boiler heat exchangers
            self.econ_lp,
            self.sh_lp,
            self.econ_ip1,
            self.econ_ip2,
            self.sh_ip1,
            self.sh_ip2,
            self.sh_ip3,
            self.econ_hp1,
            self.econ_hp2,
            self.econ_hp3,
            self.econ_hp4,
            self.econ_hp5,
            self.sh_hp1,
            self.sh_hp2,
            self.sh_hp3,
            self.sh_hp4,
        ]
        for unit in hx_list:  # set boiler hx scaling factors
            iscale.set_scaling_factor(unit.tube.heat, 1e-6)
            iscale.set_scaling_factor(unit.shell.heat, 1e-6)
            iscale.set_scaling_factor(unit.overall_heat_transfer_coefficient, 1e-2)
            iscale.set_scaling_factor(unit.area, 1e-3)
            iscale.set_scaling_factor(unit.N_Re_tube, 1e-5)
            iscale.set_scaling_factor(unit.N_Nu_tube, 1e-2)
            iscale.set_scaling_factor(unit.N_Re_shell, 1e-4)
            iscale.set_scaling_factor(unit.N_Nu_shell, 1e-2)
            iscale.set_scaling_factor(unit.hconv_tube, 1e-3)
            iscale.set_scaling_factor(unit.hconv_shell_conv, 1e-2)
            iscale.set_scaling_factor(unit.hconv_shell_total, 1e-2)
            iscale.set_scaling_factor(unit.rcond_wall, 1e5)
            if hasattr(unit, "deltaP_tube_friction"):
                iscale.set_scaling_factor(unit.deltaP_tube_friction, 1e-4)
                iscale.set_scaling_factor(unit.friction_factor_tube, 1e3)
                iscale.set_scaling_factor(unit.friction_factor_shell, 1e3)
            if hasattr(unit, "deltaP_tube_uturn"):
                iscale.set_scaling_factor(unit.deltaP_tube_uturn, 1e-2)

        iscale.set_scaling_factor(self.evap_lp.shell.heat, 1e-8)
        iscale.set_scaling_factor(self.evap_lp.tube.heat, 1e-8)
        iscale.set_scaling_factor(self.evap_lp.tube.heat, 1e-8)
        iscale.set_scaling_factor(self.evap_lp.area, 1e-4)
        iscale.set_scaling_factor(self.evap_lp.overall_heat_transfer_coefficient, 1e-2)

        iscale.set_scaling_factor(self.evap_ip.shell.heat, 1e-8)
        iscale.set_scaling_factor(self.evap_ip.tube.heat, 1e-8)
        iscale.set_scaling_factor(self.evap_ip.tube.heat, 1e-8)
        iscale.set_scaling_factor(self.evap_ip.area, 1e-4)
        iscale.set_scaling_factor(self.evap_ip.overall_heat_transfer_coefficient, 1e-2)

        iscale.set_scaling_factor(self.pump_ip.control_volume.work, 1e-7)
        iscale.set_scaling_factor(self.pump_hp.control_volume.work, 1e-8)
        iscale.set_scaling_factor(self.pump_hp.control_volume.deltaP, 1e-9)

        iscale.set_scaling_factor(self.evap_hp.shell.heat, 1e-8)
        iscale.set_scaling_factor(self.evap_hp.tube.heat, 1e-8)
        iscale.set_scaling_factor(self.evap_hp.tube.heat, 1e-8)
        iscale.set_scaling_factor(self.evap_hp.area, 1e-4)
        iscale.set_scaling_factor(self.evap_hp.overall_heat_transfer_coefficient, 1e-2)

        for t in self.config.time:
            iscale.constraint_scaling_transform(
                self.mixer1.mixer1_pressure_eqn[t], 1e-6
            )
            iscale.constraint_scaling_transform(
                self.mixer_soec.mixer_soec_pressure_eqn[t], 1e-6
            )
            iscale.constraint_scaling_transform(
                self.mixer_ip1.mixer_ip1_pressure_eqn[t], 1e-6
            )

    def initialize(
        self,
        outlvl=idaeslog.NOTSET,
        solver=None,
        optarg=None,
        load_from="hrsg_init.json.gz",
        save_to="hrsg_init.json.gz",
    ):
        """Initialize the HRSG flowsheet

        Args:
            outlvl: Logging level for initializtion
            solver (str): solver to user for initializtion
            optarg (dict): solver options
            load_from (str): if file exists and is not None, load initialization
            save_to (str): save initializtion

        Returns:
            None
        """
        init_log = idaeslog.getInitLogger(self.name, outlvl, tag="flowsheet")
        solve_log = idaeslog.getSolveLogger(self.name, outlvl, tag="flowsheet")

        solver_obj = get_solver(solver, optarg)

        init_log.info_high("HRSG Initialization Starting")

        if load_from is not None:
            if os.path.exists(load_from):
                init_log.info_high(f"HRSG load initial from {load_from}")
                # here suffix=False avoids loading scaling factors
                iutil.from_json(
                    self, fname=load_from, wts=iutil.StoreSpec(suffix=False)
                )
                return

        ######### LP Section ###########
        # FLUE GAS Inlet to econ_lp (F = 138406 kgmol/hr, T = 15 C, P=0.1 MPa abs)
        fg_rate = 38446.11  # mol/s  from Baseline report table 5-22
        fg_comp = {
            "H2O": 0.0875,
            "CO2": 0.0408,
            "N2": 0.75,
            "O2": 0.1217,
        }

        def _set_fg_port(port, temperature, pressure, flow=fg_rate, fix=False):
            port.temperature[:].set_value(temperature)
            port.pressure[:].set_value(pressure)
            for c, v in fg_comp.items():
                port.flow_mol_comp[:, c].set_value(flow * v)
            if fix:
                port.fix()

        # Feedwater inlet
        self.econ_lp.tube_inlet.flow_mol[0].fix(9790.55)
        self.econ_lp.tube_inlet.pressure[0].fix(655000)
        self.econ_lp.tube_inlet.enth_mol[0].fix(
            iapws95.htpx(T=357 * pyo.units.K, P=655000 * pyo.units.Pa)
        )

        _set_fg_port(self.econ_lp.shell_inlet, temperature=433, pressure=103421)
        self.econ_lp.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.lp02)

        self.mixer1.Preheater.flow_mol[0].fix(833)
        self.mixer1.Preheater.enth_mol[0].fix(
            iapws95.htpx(T=333.15 * pyo.units.K, P=42 * pyo.units.bar)
        )
        self.mixer1.Preheater.pressure[0].fix(3.509e6)
        self.mixer1.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.lp04)

        _set_fg_port(self.evap_lp.shell_inlet, temperature=543.31, pressure=103421)
        self.evap_lp.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.lp05)

        self.mixer_soec.initialize()
        propagate_state(self.lp13)

        self.drum_lp.initialize()
        propagate_state(self.lp06)
        propagate_state(self.lp10)

        self.splitter1.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.lp08)
        propagate_state(self.lp09)

        self.split_fg_lp.split_fraction[0, "toLP_SH"].fix(0.16779)
        _set_fg_port(
            self.split_fg_lp.inlet, temperature=640.15, pressure=103421, fix=True
        )
        self.split_fg_lp.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.g20)
        propagate_state(self.g22)

        self.sh_lp.initialize(solver=solver, outlvl=outlvl, optarg=optarg)

        self.mixer_lp2.initialize(solver=solver, outlvl=outlvl, optarg=optarg)

        init_log.info("Low pressure system initialization - Completed")

        self.pump_ip.outlet.pressure[0].fix(4.385e6)
        self.pump_ip.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.ip01)

        _set_fg_port(self.econ_ip1.shell_inlet, temperature=579.46, pressure=103421)
        self.econ_ip1.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.ip02)

        self.splitter_ip1.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.ip03)

        _set_fg_port(self.econ_ip2.shell_inlet, temperature=607, pressure=103421)
        self.econ_ip2.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.ip05)

        self.evap_ip.ip_sat_vap_eqn.deactivate()
        _set_fg_port(self.evap_ip.shell_inlet, temperature=630, pressure=103421)
        self.evap_ip.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.ip06)

        _set_fg_port(self.sh_ip1.shell_inlet, temperature=670, pressure=103421)
        self.sh_ip1.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.ip07)

        self.splitter_ip2.inlet.flow_mol[0].fix(7503.7337)
        self.splitter_ip2.inlet.enth_mol[0].fix(
            iapws95.htpx(T=628.03 * pyo.units.K, P=3.737e6 * pyo.units.Pa)
        )
        self.splitter_ip2.inlet.pressure[0].fix(3.737e6)
        self.splitter_ip2.split_fraction[0, "Cold_reheat"].fix(0.9941)
        self.splitter_ip2.split_fraction[0, "toEjector"].fix(0.00074)
        self.splitter_ip2.split_fraction[0, "toDryer"].fix(0.000274)
        self.splitter_ip2.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.ip15)

        self.mixer_ip1.sh_ip1.flow_mol[0].fix()
        self.mixer_ip1.sh_ip1.enth_mol[0].fix()
        self.mixer_ip1.sh_ip1.pressure[0].fix()
        self.mixer_ip1.Cold_reheat.flow_mol[0].fix()
        self.mixer_ip1.Cold_reheat.enth_mol[0].fix()
        self.mixer_ip1.Cold_reheat.pressure[0].fix()
        self.mixer_ip1.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.ip08)

        _set_fg_port(self.sh_ip2.shell_inlet, temperature=802, pressure=103421)
        self.sh_ip2.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.ip09)

        _set_fg_port(self.sh_ip3.shell_inlet, temperature=868, pressure=103421)
        self.sh_ip3.initialize(solver=solver, outlvl=outlvl, optarg=optarg)

        init_log.info("Intermediate pressure system initialization - Completed")

        self.pump_hp.outlet.pressure[0].fix(24.4e6)
        self.pump_hp.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.hp01)

        _set_fg_port(self.econ_hp1.shell_inlet, temperature=566, pressure=103421)
        self.econ_hp1.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.hp02)

        _set_fg_port(self.econ_hp2.shell_inlet, temperature=596, pressure=103421)
        self.econ_hp2.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.hp03)

        _set_fg_port(self.econ_hp3.shell_inlet, temperature=607, pressure=103421)
        self.econ_hp3.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.hp04)

        _set_fg_port(self.econ_hp4.shell_inlet, temperature=624, pressure=103421)
        self.econ_hp4.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.hp05)

        _set_fg_port(self.econ_hp5.shell_inlet, temperature=631, pressure=103421)
        self.econ_hp5.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.hp06)

        self.evap_hp_valve.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.hp06b)

        self.evap_hp.hp_sat_vap_eqn.deactivate()
        _set_fg_port(self.evap_hp.shell_inlet, temperature=730, pressure=103421)
        self.evap_hp.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.hp07)

        _set_fg_port(self.sh_hp1.shell_inlet, temperature=760, pressure=103421)
        self.sh_hp1.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.hp08)

        _set_fg_port(self.sh_hp2.shell_inlet, temperature=806, pressure=103421)
        self.sh_hp2.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.hp09)

        _set_fg_port(self.sh_hp3.shell_inlet, temperature=835, pressure=103421)
        self.sh_hp3.initialize(solver=solver, outlvl=outlvl, optarg=optarg)
        propagate_state(self.hp10)

        _set_fg_port(
            self.sh_hp4.shell_inlet, temperature=898.15, pressure=103421, fix=True
        )
        self.sh_hp4.initialize(solver=solver, outlvl=outlvl, optarg=optarg)

        # unfix inlets that were fixed for initialization
        self.mixer_ip1.sh_ip1.flow_mol[0].unfix()
        self.mixer_ip1.sh_ip1.enth_mol[0].unfix()
        self.mixer_ip1.sh_ip1.pressure[0].unfix()
        self.mixer_ip1.Cold_reheat.flow_mol[0].unfix()
        self.mixer_ip1.Cold_reheat.enth_mol[0].unfix()
        self.mixer_ip1.Cold_reheat.pressure[0].unfix()
        self.split_fg_lp.inlet.flow_mol_comp[:, :].unfix()
        self.split_fg_lp.inlet.pressure[0].unfix()
        self.split_fg_lp.inlet.temperature[0].unfix()
        self.split_fg_lp.inlet.flow_mol_comp[:, :].unfix()
        self.split_fg_lp.inlet.pressure[0].unfix()
        self.split_fg_lp.inlet.temperature[0].unfix()

        gas_streams = [
            self.g12,
            self.g13,
            self.g14,
            self.g15,
            self.g16,
            self.g17,
            self.g18,
            self.g19,
            self.g20,
            self.g26,
            self.g27,
        ]
        for g in gas_streams:
            g.destination.fix()
            g.expanded_block.deactivate()
        res = solver_obj.solve(self, tee=True)
        for g in gas_streams:
            g.destination.unfix()
            g.expanded_block.activate()
        res = solver_obj.solve(self, tee=True)

        self.evap_ip.ip_sat_vap_eqn.activate()
        self.splitter1.split_fraction[0, "toIP"].unfix()

        for g in gas_streams:
            g.destination.fix()
            g.expanded_block.deactivate()
        res = solver_obj.solve(self, tee=True)
        for g in gas_streams:
            g.destination.unfix()
            g.expanded_block.activate()

        res = solver_obj.solve(self, tee=True)

        if save_to is not None:
            iutil.to_json(self, fname=save_to)
            init_log.info_low(f"Initialization saved to {save_to}")
        init_log.info("High pressure system initialization - Completed")

    def _stream_tags(self):
        tag_stm = iutil.ModelTagGroup()
        tag_gas = iutil.ModelTagGroup()
        self.tags_steam_streams = tag_stm
        self.tags_flue_gas_streams = tag_gas
        stream_states = ta.stream_states_dict(
            ta.arcs_to_stream_dict(
                self,
                descend_into=False,
                additional={  # these are streams in or out without an arc
                    "lp01": self.econ_lp.tube_inlet,
                    "lp03": self.mixer1.Preheater,
                    "lp12": self.mixer_soec.soec_makeup,
                    "ip04": self.splitter_ip1.toNGPH,
                    "lp11": self.sh_lp.tube_outlet,
                    "hp11": self.sh_hp4.tube_outlet,
                    "ip10": self.sh_ip3.tube_outlet,
                    "ip11": self.splitter_ip2.inlet,
                    "ip15": self.splitter_ip2.Cold_reheat,
                    "ip13": self.splitter_ip2.toReclaimer,
                    "ip12": self.splitter_ip2.toEjector,
                    "ip14": self.splitter_ip2.toDryer,
                    "g30": self.econ_lp.shell_outlet,
                    "g19": self.econ_hp3.shell_outlet,
                    "g08": self.sh_hp4.shell_inlet,
                },
            )
        )
        for i, s in stream_states.items():  # create the tags for steam quantities
            if isinstance(s, iapws95.Iapws95StateBlockData):
                tag_group = tag_stm
                is_steam = True
            else:
                tag_group = tag_gas
                is_steam = False
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
            if is_steam:
                tag_group[f"{i}_X"] = iutil.ModelTag(
                    doc=f"{i}: vapor fraction",
                    expr=s.phase_frac["Vap"],
                    format_string="{:.3f}",
                    display_units=None,
                )
                tag_group[f"{i}_H"] = iutil.ModelTag(
                    doc=f"{i}: molar enthalpy",
                    expr=s.enth_mol,
                    format_string="{:.3f}",
                    display_units=pyo.units.kJ / pyo.units.mol,
                )
            else:
                for c in s.mole_frac_comp:
                    tag_group[f"{i}_y{c}"] = iutil.ModelTag(
                        doc=f"{i}: mole percent {c}",
                        expr=s.mole_frac_comp[c] * 100,
                        format_string="{:.3f}",
                        display_units="%",
                    )

    pfd_file = "hrsg_template.svg"

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
            s = svg_tag(svg=f, tag_group=self.tags_steam_streams)
        s = svg_tag(svg=s, tag_group=self.tags_flue_gas_streams, outfile=fname)
        if fname is None:
            return s

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
        for tag, stream, col in HrsgFlowsheetData._stream_col_gen(tag_group):
            rows.add(stream)
            cols.add(col)
            tags.append((tag, stream, col))
        df = pd.DataFrame(index=sorted(rows), columns=sorted(cols))
        for tag, stream, col in tags:
            df.at[stream, col] = tag.get_display_value()
        return df

    def steam_streams_dataframe(self):
        """Get stream table for steam streams"""
        return self._stream_table(self.tags_steam_streams)

    def flue_gas_streams_dataframe(self):
        """Get stream table for flue gas streams"""
        return self._stream_table(self.tags_flue_gas_streams)
