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

__author__ = "John Eslick"

import os
from pathlib import Path
import csv

import pandas as pd

import pyomo.environ as pyo
from pyomo.network import Arc
from pyomo.common.fileutils import this_file_dir

from idaes.core import FlowsheetBlockData, declare_process_block_class
from idaes.models.properties.modular_properties.base.generic_property import (
    GenericParameterBlock,
)
from idaes.models.properties.modular_properties.base.generic_reaction import (
    GenericReactionParameterBlock,
)
import idaes.models.unit_models as um  # um = unit models
import idaes.core.util as iutil
from idaes.core.util.initialization import propagate_state
import idaes.core.util.tables as tables
import idaes.core.util.scaling as iscale
from idaes.core.solvers import get_solver
from idaes.models_extra.power_generation.properties.natural_gas_PR import (
    get_prop,
    get_rxn,
)
from idaes.models.properties import iapws95
import idaes.logger as idaeslog
from idaes.core.util.tags import svg_tag


@declare_process_block_class(
    "GasTurbineFlowsheet",
    doc=(
        "The gas turbine flowsheet is base on NETL report 'Cost and Performance "
        "Baseline for Fossil Energy Plants Volume 1: Bituminous Coal and Natural "
        "Gas to Electricity.' Sept 2019, Case B31B. This flowsheet is intended for "
        "off-design steady state simulations."
    ),
)
class GasTurbineFlowsheetData(FlowsheetBlockData):
    def build(self):
        super().build()
        self._add_properties()
        self._add_models()
        self._add_performance_curves_gts1()
        self._add_performance_curves_gts2()
        self._add_performance_curves_gts3()
        self._add_constraints()
        self._add_arcs()
        self._set_initial_inputs()
        self._add_tags()
        self._set_scaling()

    def _add_properties(
        self,
        air_species={"CO2", "Ar", "H2O", "O2", "N2"},
        cmb_species={"CH4", "C2H6", "C3H8", "C4H10", "O2", "H2O", "CO2", "N2", "Ar"},
        flue_species={"O2", "H2O", "CO2", "N2", "Ar"},
        rxns={  # reaction and key component
            "ch4_cmb": "CH4",
            "c2h6_cmb": "C2H6",
            "c3h8_cmb": "C3H8",
            "c4h10_cmb": "C4H10",
        },
    ):
        """Add property parameter blocks"""
        self.air_species = air_species
        self.cmb_species = cmb_species
        self.flue_species = flue_species
        self.rxns = rxns
        # Here three differnt type of property blocks are used, so that we can
        # avoid components with zero flow, which can cause problems with
        # certain property calculations (entropy for example). Three types of
        # gas streams are Air, combstion mixture, and flue gas.  Fortunately
        # natural gas has some air compoents in it so the combustion property
        # parameters can be used for natural gas and natural gas mixed with air.
        self.prop_water = iapws95.Iapws95ParameterBlock()
        self.air_prop_params = GenericParameterBlock(
            **get_prop(air_species, ["Vap"]),
            doc="Air property parameters",
        )
        self.cmb_prop_params = GenericParameterBlock(
            **get_prop(cmb_species, ["Vap"]),
            doc="Natural gas or Natural gas + Air property parameters",
        )
        self.flue_prop_params = GenericParameterBlock(
            **get_prop(flue_species, ["Vap"]),
            doc="Flue gas property parameters",
        )
        # Combustion reaction package
        self.gas_combustion = GenericReactionParameterBlock(
            **get_rxn(self.cmb_prop_params, self.rxns),
            doc="Reaction parameters package",
        )

    def _add_models(self):
        self.feed_air1 = um.Feed(
            doc="Air feed block", property_package=self.air_prop_params
        )
        self.feed_fuel1 = um.Feed(
            doc="Fuel feed block", property_package=self.cmb_prop_params
        )
        self.exhaust_1 = um.Product(
            doc="Exhaust product block",
            property_package=self.flue_prop_params,
        )
        self.vsv = um.Valve(
            doc="Valve to approximatly variable inlet guide vanes",
            valve_function_callback=um.ValveFunctionType.linear,
            property_package=self.air_prop_params,
        )
        self.cmp1 = um.Compressor(
            doc="Gas turbine air compression section",
            property_package=self.air_prop_params,
            support_isentropic_performance_curves=True,
        )
        self.splt1 = um.Separator(
            doc="Blade cooling air splitter",
            property_package=self.air_prop_params,
            outlet_list=["air04", "air05", "air07", "air09"],
        )
        self.valve01 = um.Valve(
            doc="Stage 1 blade cooling air valve",
            valve_function_callback=um.ValveFunctionType.linear,
            property_package=self.air_prop_params,
        )
        self.valve02 = um.Valve(
            doc="Stage 2 blade cooling air valve",
            valve_function_callback=um.ValveFunctionType.linear,
            property_package=self.air_prop_params,
        )
        self.valve03 = um.Valve(
            doc="Stage 2 blade cooling air valve",
            valve_function_callback=um.ValveFunctionType.linear,
            property_package=self.air_prop_params,
        )
        self.inject_translator = um.Translator(
            doc="Translator for air to combustion mixture properties",
            inlet_property_package=self.air_prop_params,
            outlet_property_package=self.cmb_prop_params,
            outlet_state_defined=False,
        )
        self.ng_preheat = um.HeatExchanger(
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": self.prop_water},
            tube={"property_package": self.cmb_prop_params},
        )
        self.inject1 = um.Mixer(
            doc="Fuel injection mixer (mix air and natural gas)",
            property_package=self.cmb_prop_params,
            inlet_list=["gas", "air"],
            momentum_mixing_type=um.MomentumMixingType.none,
        )
        self.translator1 = um.Translator(
            doc="Translate stage 1 blade cooling air properties to flue gas",
            inlet_property_package=self.air_prop_params,
            outlet_property_package=self.flue_prop_params,
            outlet_state_defined=False,
        )
        self.mx1 = um.Mixer(
            doc="Stage 1 blade cooling air mixer",
            property_package=self.flue_prop_params,
            inlet_list=["gas", "air"],
            momentum_mixing_type=um.MomentumMixingType.equality,
        )
        self.translator2 = um.Translator(
            doc="Translate stage 2 blade cooling air properties to flue gas",
            inlet_property_package=self.air_prop_params,
            outlet_property_package=self.flue_prop_params,
            outlet_state_defined=False,
        )
        self.mx2 = um.Mixer(
            doc="Stage 2 blade cooling air mixer",
            property_package=self.flue_prop_params,
            inlet_list=["gas", "air"],
            momentum_mixing_type=um.MomentumMixingType.equality,
        )
        self.translator3 = um.Translator(
            doc="Translate stage 3 blade cooling air properties to flue gas",
            inlet_property_package=self.air_prop_params,
            outlet_property_package=self.flue_prop_params,
            outlet_state_defined=False,
        )
        self.mx3 = um.Mixer(
            doc="Stage 3 blade cooling air mixer",
            property_package=self.flue_prop_params,
            inlet_list=["gas", "air"],
            momentum_mixing_type=um.MomentumMixingType.equality,
        )
        # Combustor, for now assuming complete reactions and no NOx
        self.cmb1 = um.StoichiometricReactor(
            doc="Combustor",
            property_package=self.cmb_prop_params,
            reaction_package=self.gas_combustion,
            has_pressure_change=True,
        )
        self.flue_translator = um.Translator(
            doc="Translate combustion mixture properties to flue gas",
            inlet_property_package=self.cmb_prop_params,
            outlet_property_package=self.flue_prop_params,
            outlet_state_defined=False,
        )
        self.gts1 = um.Turbine(
            doc="Gas turbine stage 1",
            property_package=self.flue_prop_params,
            support_isentropic_performance_curves=True,
        )
        self.gts2 = um.Turbine(
            doc="Gas turbine stage 2",
            property_package=self.flue_prop_params,
            support_isentropic_performance_curves=True,
        )
        self.gts3 = um.Turbine(
            doc="Gas turbine stage 3",
            property_package=self.flue_prop_params,
            support_isentropic_performance_curves=True,
        )

    def _add_performance_curves_gts1(self, flow_scale=0.896):
        """Add isentropic head and efficiency curves for gas turbine stage 1"""

        @self.gts1.performance_curve.Constraint(
            self.time,
            doc="Gas turbine stage 1 isentropic efficiency curve",
        )
        def eff_isen_eqn(b, t):
            f = flow_scale * b.parent_block().control_volume.properties_in[t].flow_vol
            return b.parent_block().efficiency_isentropic[t] == 1.02 * (
                1.4469e-14 * f**5
                - 6.3333e-11 * f**4
                + 6.6179e-08 * f**3
                - 3.1728e-05 * f**2
                + 7.7846e-03 * f
                + 1.0724e-01
            )

        @self.gts1.performance_curve.Constraint(
            self.time,
            doc="Gas turbine stage 1 isentropic head curve",
        )
        def head_isen_eqn(b, t):
            f = pyo.log(
                flow_scale * b.parent_block().control_volume.properties_in[t].flow_vol
            )
            return b.head_isentropic[t] == -(
                -2085.1 * f**3 + 38433 * f**2 - 150764 * f + 422313
            )

    def _add_performance_curves_gts2(self, flow_scale=0.896):
        """Add isentropic head and efficiency curves for gas turbine stage 2"""

        @self.gts2.performance_curve.Constraint(
            self.time, doc="Gas turbine stage 2 isentropic efficiency curve"
        )
        def eff_isen_eqn(b, t):
            f = flow_scale * b.parent_block().control_volume.properties_in[t].flow_vol
            return b.parent_block().efficiency_isentropic[t] == 1.02 * (
                2.6599e-16 * f**5
                - 2.5894e-12 * f**4
                + 6.0174e-09 * f**3
                - 6.4156e-06 * f**2
                + 3.5005e-03 * f
                + 1.0724e-01
            )

        @self.gts2.performance_curve.Constraint(
            self.time, doc="Gas turbine stage 2 isentropic head curve"
        )
        def head_isen_eqn(b, t):
            f = pyo.log(
                flow_scale * b.parent_block().control_volume.properties_in[t].flow_vol
            )
            return b.head_isentropic[t] == -(
                -1676.3 * f**3 + 34916 * f**2 - 173801 * f + 456957
            )

    def _add_performance_curves_gts3(self, flow_scale=0.896):
        """Add isentropic head and efficiency curves for gas turbine stage 3"""

        @self.gts3.performance_curve.Constraint(
            self.time,
            doc="Gas turbine stage 3 isentropic efficiency curve",
        )
        def eff_isen_eqn(b, t):
            f = flow_scale * b.parent_block().control_volume.properties_in[t].flow_vol
            return b.parent_block().efficiency_isentropic[t] == 1.02 * (
                5.8407e-18 * f**5
                - 1.2203e-13 * f**4
                + 6.0863e-10 * f**3
                - 1.3927e-06 * f**2
                + 1.6310e-03 * f
                + 1.0724e-01
            )

        @self.gts3.performance_curve.Constraint(
            self.time,
            doc="Gas turbine stage 3 isentropic head curve",
        )
        def head_isen_eqn(b, t):
            f = pyo.log(
                flow_scale * b.parent_block().control_volume.properties_in[t].flow_vol
            )
            return b.head_isentropic[t] == -(
                -1373.6 * f**3 + 31759 * f**2 - 188528 * f + 500520
            )

    def _add_constraints(self):
        """Add addtional flowsheet constraints and expressions"""
        self.cmbout_o2_mol_frac = pyo.Var(
            self.time, initialize=0.1157, doc="Combustor outlet O2 mole fraction."
        )

        # Just use pressure drop in the air inlet valve instead of using the
        # opening. This will slightly simplify the model.
        self.vsv.pressure_flow_equation.deactivate()

        # O2 fraction in combustor constraint (to set var)
        @self.Constraint(self.time)
        def o2_flow(b, t):
            return (
                self.cmb1.control_volume.properties_out[t].mole_frac_comp["O2"]
                == self.cmbout_o2_mol_frac[t]
            )

        # Fuel injector pressure is the air pressure, lumps in the gas valve
        @self.inject1.Constraint(self.time)
        def mxpress_eqn(b, t):
            return b.mixed_state[t].pressure == b.air_state[t].pressure

        # The pressure drop in the cumbustor is just a fixed 5%.
        @self.cmb1.Constraint(self.time)
        def pressure_drop_eqn(b, t):
            return (
                0.95
                == b.control_volume.properties_out[t].pressure
                / b.control_volume.properties_in[t].pressure
            )

        # Complete combustion, use key components and 100% conversion
        @self.cmb1.Constraint(self.time, self.rxns.keys())
        def reaction_extent(b, t, r):
            key = self.rxns[r]
            prp = b.control_volume.properties_in[t]
            stc = self.gas_combustion.rate_reaction_stoichiometry[r, "Vap", key]
            extent = b.rate_reaction_extent[t, r]
            return extent == -prp.flow_mol * prp.mole_frac_comp[key] / stc

        # Calculate the total gas turnine gross power output.
        @self.Expression(self.time)
        def gt_power_expr(b, t):
            return (
                self.cmp1.control_volume.work[t]
                + self.gts1.control_volume.work[t]
                + self.gts2.control_volume.work[t]
                + self.gts3.control_volume.work[t]
            )

        # Add a varable and constraint for gross power.  This allows fixing power
        # for simulations where a specific power output is desired.
        self.gt_power = pyo.Var(self.time, units=pyo.units.W)

        @self.Constraint(self.time)
        def gt_power_eqn(b, t):
            return b.gt_power[t] == b.gt_power_expr[t]

        # Rules for translator blocks
        def rule_flow_mol_comp(blk, t, j):
            return (
                blk.properties_in[t].flow_mol_comp[j]
                == blk.properties_out[t].flow_mol_comp[j]
            )

        def rule_temperature(blk, t):
            return blk.properties_in[t].temperature == blk.properties_out[t].temperature

        def rule_pressure(blk, t):
            return blk.properties_in[t].pressure == blk.properties_out[t].pressure

        def rule_zero_flow(blk, t, j):
            return blk.properties_out[t].flow_mol_comp[j] == 0

        translators = {
            self.inject_translator,
            self.translator1,
            self.translator2,
            self.translator3,
            self.flue_translator,
        }

        for blk in translators:
            blk.temperature_eqn = pyo.Constraint(self.time, rule=rule_temperature)
            blk.pressure_eqn = pyo.Constraint(self.time, rule=rule_pressure)
            for t in self.config.time:
                iscale.constraint_scaling_transform(blk.temperature_eqn[t], 1e-2)
                iscale.constraint_scaling_transform(blk.pressure_eqn[t], 1e-6)

        self.inject_translator.flow_mole_comp_eqn = pyo.Constraint(
            self.time, self.air_species, rule=rule_flow_mol_comp
        )
        for i, c in self.inject_translator.flow_mole_comp_eqn.items():
            iscale.constraint_scaling_transform(c, 1e-3)

        self.inject_translator.zero_flow_eqn = pyo.Constraint(
            self.time, self.cmb_species - self.air_species, rule=rule_zero_flow
        )

        for blk in {self.translator1, self.translator2, self.translator3}:
            blk.flow_mole_comp_eqn = pyo.Constraint(
                self.time, self.air_species, rule=rule_flow_mol_comp
            )
            blk.zero_flow_eqn = pyo.Constraint(
                self.time, self.flue_species - self.air_species, rule=rule_zero_flow
            )
            for i, c in blk.flow_mole_comp_eqn.items():
                iscale.constraint_scaling_transform(c, 1e-3)

        self.flue_translator.flow_mole_comp_eqn = pyo.Constraint(
            self.time, self.flue_species, rule=rule_flow_mol_comp
        )

        for i, c in self.flue_translator.flow_mole_comp_eqn.items():
            iscale.constraint_scaling_transform(c, 1e-3)

    def _add_arcs(self):
        """Connect process unit models with arcs"""
        self.fuel01 = Arc(
            source=self.feed_fuel1.outlet,
            destination=self.ng_preheat.tube_inlet,
            doc="Fuel feed block to fuel preheater",
        )
        self.fuel02 = Arc(
            source=self.ng_preheat.tube_outlet,
            destination=self.inject1.gas,
            doc="Fuel preheater to fuel injector",
        )
        self.air01 = Arc(
            source=self.feed_air1.outlet,
            destination=self.vsv.inlet,
            doc="Air inlet block to air inlet valve",
        )
        self.air02 = Arc(
            source=self.vsv.outlet,
            destination=self.cmp1.inlet,
            doc="Air valve to air compressor inlet",
        )
        self.air03 = Arc(
            source=self.cmp1.outlet,
            destination=self.splt1.inlet,
            doc="Air compressor outlet to blade cooling air splitter",
        )
        self.air04a = Arc(
            source=self.splt1.air04,
            destination=self.inject_translator.inlet,
            doc="Blade cooling air splitter to combustor translator",
        )
        self.air04b = Arc(
            source=self.inject_translator.outlet,
            destination=self.inject1.air,
            doc="Combustion air translator to fuel mixer",
        )
        self.air05 = Arc(
            source=self.splt1.air05,
            destination=self.valve01.inlet,
            doc="Stage 1 blade cooling air splitter to valve",
        )
        self.air06a = Arc(
            source=self.valve01.outlet, destination=self.translator1.inlet
        )
        self.air06b = Arc(source=self.translator1.outlet, destination=self.mx1.air)
        self.air07 = Arc(
            source=self.splt1.air07,
            destination=self.valve02.inlet,
            doc="Stage 2 blade cooling air splitter to valve",
        )
        self.air08a = Arc(
            source=self.valve02.outlet, destination=self.translator2.inlet
        )
        self.air08b = Arc(source=self.translator2.outlet, destination=self.mx2.air)
        self.air09 = Arc(
            source=self.splt1.air09,
            destination=self.valve03.inlet,
            doc="Stage 3 blade cooling air splitter to valve",
        )
        self.air10a = Arc(
            source=self.valve03.outlet, destination=self.translator3.inlet
        )
        self.air10b = Arc(source=self.translator3.outlet, destination=self.mx3.air)
        self.g01 = Arc(source=self.inject1.outlet, destination=self.cmb1.inlet)
        self.g02a = Arc(source=self.cmb1.outlet, destination=self.flue_translator.inlet)
        self.g02b = Arc(source=self.flue_translator.outlet, destination=self.gts1.inlet)
        self.g03 = Arc(source=self.gts1.outlet, destination=self.mx1.gas)
        self.g04 = Arc(source=self.mx1.outlet, destination=self.gts2.inlet)
        self.g05 = Arc(source=self.gts2.outlet, destination=self.mx2.gas)
        self.g06 = Arc(source=self.mx2.outlet, destination=self.gts3.inlet)
        self.g07 = Arc(source=self.gts3.outlet, destination=self.mx3.gas)
        self.g08 = Arc(source=self.mx3.outlet, destination=self.exhaust_1.inlet)
        # Create arc constraints
        pyo.TransformationFactory("network.expand_arcs").apply_to(self)

    def _set_initial_inputs(self):
        air_comp = {
            "CH4": 0.0,
            "C2H6": 0.0,
            "C3H8": 0.0,
            "C4H10": 0.0,
            "O2": 0.2074,
            "H2O": 0.0099,
            "CO2": 0.0003,
            "N2": 0.7732,
            "Ar": 0.0092,
        }
        ng_comp = {
            "CH4": 0.931,
            "C2H6": 0.0320,
            "C3H8": 0.007,
            "C4H10": 0.004,
            "O2": 1e-19,
            "H2O": 1e-19,
            "CO2": 0.01,
            "N2": 0.0160,
            "Ar": 1e-19,
        }

        self.vsv.deltaP.fix(-100)
        self.cmp1.efficiency_isentropic.fix(0.81)
        self.cmp1.ratioP.fix(19.075)
        # blabe cooling air valves use expected flow to calculate valve flow
        # coefficients, so here set expected flow and after init the opening will
        # be the fixed var.
        self.valve01.control_volume.properties_in[0].flow_mol.fix(2315)
        self.valve02.control_volume.properties_in[0].flow_mol.fix(509)
        self.valve03.control_volume.properties_in[0].flow_mol.fix(354)
        self.valve01.valve_opening.unfix()
        self.valve02.valve_opening.unfix()
        self.valve03.valve_opening.unfix()
        # Feed streams
        # Air at compressor inlet
        self.feed_air1.flow_mol[:] = 34875.9
        self.feed_air1.temperature.fix(288.15)
        self.feed_air1.pressure.fix(101047)
        for i, v in air_comp.items():
            self.feed_air1.mole_frac_comp[:, i].fix(v)
        # Gas at fuel injection
        self.feed_fuel1.flow_mol.fix(1348.8)
        self.feed_fuel1.temperature.fix(310.928)
        self.feed_fuel1.pressure.fix(3.10264e6)
        for i, v in ng_comp.items():
            self.feed_fuel1.mole_frac_comp[:, i].fix(v)

        self.ng_preheat.area.fix(5000)
        self.ng_preheat.overall_heat_transfer_coefficient.fix(100)
        self.ng_preheat.shell_inlet.flow_mol.fix(850)
        self.ng_preheat.shell_inlet.pressure.fix(4.2e6)
        self.ng_preheat.shell_inlet.enth_mol.fix(14e3)

    def _add_tags(self):
        tag_group = iutil.ModelTagGroup()
        self.tags_streams = tag_group
        stream_states = tables.stream_states_dict(
            tables.arcs_to_stream_dict(
                self,
                descend_into=False,
                additional={
                    "st01": self.ng_preheat.shell_inlet,
                    "st02": self.ng_preheat.shell_outlet,
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
                format_string="{:.1f}",
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
                for c in s.mole_frac_comp:
                    tag_group[f"{i}_y{c}"] = iutil.ModelTag(
                        doc=f"{i}: mole percent {c}",
                        expr=s.mole_frac_comp[c] * 100,
                        format_string="{:.3f}",
                        display_units="%",
                    )
            except AttributeError:  # it's steam
                tag_group[f"{i}_yH2O"] = iutil.ModelTag(
                    doc=f"{i}: mole percent {c}",
                    expr=100,
                    format_string="{:.3f}",
                    display_units="%",
                )
        tag_group = iutil.ModelTagGroup()
        self.tags_output = tag_group
        tag_group["valve01_opening"] = iutil.ModelTag(
            doc=f"Blade cooling air valve01 opening",
            expr=self.valve01.valve_opening[0] * 100,
            format_string="{:.1f}",
            display_units="%",
        )
        tag_group["valve02_opening"] = iutil.ModelTag(
            doc=f"Blade cooling air valve02 opening",
            expr=self.valve02.valve_opening[0] * 100,
            format_string="{:.1f}",
            display_units="%",
        )
        tag_group["valve03_opening"] = iutil.ModelTag(
            doc=f"Blade cooling air valve03 opening",
            expr=self.valve03.valve_opening[0] * 100,
            format_string="{:.1f}",
            display_units="%",
        )
        tag_group["cmp1_head_isen"] = iutil.ModelTag(
            doc=f"Compressor isentropic head.",
            expr=self.cmp1.performance_curve.head_isentropic[0],
            format_string="{:.2f}",
            display_units=pyo.units.kJ / pyo.units.kg,
        )
        tag_group["gts1_head_isen"] = iutil.ModelTag(
            doc=f"Gas turbine stage 1 isentropic head.",
            expr=self.gts1.performance_curve.head_isentropic[0],
            format_string="{:.2f}",
            display_units=pyo.units.kJ / pyo.units.kg,
        )
        tag_group["gts2_head_isen"] = iutil.ModelTag(
            doc=f"Gas turbine stage 2 isentropic head.",
            expr=self.gts2.performance_curve.head_isentropic[0],
            format_string="{:.2f}",
            display_units=pyo.units.kJ / pyo.units.kg,
        )
        tag_group["gts3_head_isen"] = iutil.ModelTag(
            doc=f"Gas turbine stage 3 isentropic head.",
            expr=self.gts3.performance_curve.head_isentropic[0],
            format_string="{:.2f}",
            display_units=pyo.units.kJ / pyo.units.kg,
        )
        tag_group["cmp1_eff_isen"] = iutil.ModelTag(
            doc=f"Compressor isentropic efficiency.",
            expr=100 * self.cmp1.efficiency_isentropic[0],
            format_string="{:.2f}",
            display_units="%",
        )
        tag_group["gts1_eff_isen"] = iutil.ModelTag(
            doc=f"Gas turbine stage 1 isentropic efficiency.",
            expr=100 * self.gts1.efficiency_isentropic[0],
            format_string="{:.2f}",
            display_units="%",
        )
        tag_group["gts2_eff_isen"] = iutil.ModelTag(
            doc=f"Gas turbine stage 2 isentropic efficiency.",
            expr=100 * self.gts2.efficiency_isentropic[0],
            format_string="{:.2f}",
            display_units="%",
        )
        tag_group["gts3_eff_isen"] = iutil.ModelTag(
            doc=f"Gas turbine stage 3 isentropic efficiency.",
            expr=100 * self.gts3.efficiency_isentropic[0],
            format_string="{:.2f}",
            display_units="%",
        )
        tag_group["cmp1_power"] = iutil.ModelTag(
            doc=f"Compressor power",
            expr=self.cmp1.control_volume.work[0],
            format_string="{:.2f}",
            display_units=pyo.units.MW,
        )
        tag_group["gts1_power"] = iutil.ModelTag(
            doc=f"GT stage 1 power",
            expr=self.gts1.control_volume.work[0],
            format_string="{:.2f}",
            display_units=pyo.units.MW,
        )
        tag_group["gts2_power"] = iutil.ModelTag(
            doc=f"GT stage 2 power",
            expr=self.gts2.control_volume.work[0],
            format_string="{:.2f}",
            display_units=pyo.units.MW,
        )
        tag_group["gts3_power"] = iutil.ModelTag(
            doc=f"GT stage 3 power",
            expr=self.gts3.control_volume.work[0],
            format_string="{:.2f}",
            display_units=pyo.units.MW,
        )
        tag_group["gt_total_power"] = iutil.ModelTag(
            doc=f"Total gas turbine power output",
            expr=-self.gt_power[0],
            format_string="{:.2f}",
            display_units=pyo.units.MW,
        )

    def _set_scaling(self):
        prop_packages = {
            self.air_prop_params,
            self.cmb_prop_params,
            self.flue_prop_params,
        }
        _mf_scale = {
            "Ar": 100,
            "O2": 100,
            "H2S": 1000,
            "SO2": 1000,
            "H2": 1000,
            "CO": 1000,
            "C2H4": 1000,
            "C2H6": 1000,
            "C3H8": 1000,
            "C4H10": 1000,
            "CO2": 1000,
        }
        for pp in prop_packages:
            pp.set_default_scaling("mole_frac_comp", 10)
            pp.set_default_scaling("mole_frac_phase_comp", 10)
            for c, s in _mf_scale.items():
                if c in pp.component_list:
                    pp.set_default_scaling("mole_frac_comp", s, index=c)
                    pp.set_default_scaling("mole_frac_phase_comp", s, index=("Vap", c))
            pp.set_default_scaling("enth_mol_phase", 1e-3, index="Vap")
        for i in ["air05", "air07", "air09"]:
            iscale.set_scaling_factor(self.splt1.split_fraction[0.0, i], 100)

        iscale.set_scaling_factor(self.valve01.control_volume.work, 1e-8)
        iscale.set_scaling_factor(self.valve02.control_volume.work, 1e-8)
        iscale.set_scaling_factor(self.valve03.control_volume.work, 1e-8)
        iscale.set_scaling_factor(self.vsv.control_volume.work, 1e-8)
        iscale.set_scaling_factor(self.cmp1.control_volume.work, 1e-8)
        iscale.set_scaling_factor(self.gts1.control_volume.work, 1e-8)
        iscale.set_scaling_factor(self.gts2.control_volume.work, 1e-8)
        iscale.set_scaling_factor(self.gts3.control_volume.work, 1e-8)
        iscale.set_scaling_factor(
            self.gts1.control_volume.properties_in[0].flow_mol, 1e-5
        )
        iscale.set_scaling_factor(
            self.gts2.control_volume.properties_in[0].flow_mol, 1e-5
        )
        iscale.set_scaling_factor(
            self.gts3.control_volume.properties_in[0].flow_mol, 1e-5
        )
        iscale.set_scaling_factor(
            self.gts1.control_volume.properties_out[0].flow_mol, 1e-5
        )
        iscale.set_scaling_factor(
            self.gts2.control_volume.properties_out[0].flow_mol, 1e-5
        )
        iscale.set_scaling_factor(
            self.gts3.control_volume.properties_out[0].flow_mol, 1e-5
        )

        for i, v in self.cmb1.control_volume.rate_reaction_extent.items():
            if i[1] == "ch4_cmb":
                iscale.set_scaling_factor(v, 1e-2)
            else:
                iscale.set_scaling_factor(v, 1)
        for i, c in self.cmb1.reaction_extent.items():
            iscale.constraint_scaling_transform(c, 1e-2)
        for i, v in self.cmb1.control_volume.rate_reaction_generation.items():
            if i[2] in ["O2", "CO2", "CH4", "H2O"]:
                iscale.set_scaling_factor(v, 0.001)
            else:
                iscale.set_scaling_factor(v, 0.1)
        for v in self.cmp1.deltaP.values():
            iscale.set_scaling_factor(v, 1e-6)
        for v in self.gts1.deltaP.values():
            iscale.set_scaling_factor(v, 1e-6)
        for v in self.gts2.deltaP.values():
            iscale.set_scaling_factor(v, 1e-6)
        for v in self.gts3.deltaP.values():
            iscale.set_scaling_factor(v, 1e-6)
        for v in self.valve01.deltaP.values():
            iscale.set_scaling_factor(v, 1e-6)
        for v in self.valve02.deltaP.values():
            iscale.set_scaling_factor(v, 1e-6)
        for v in self.valve03.deltaP.values():
            iscale.set_scaling_factor(v, 1e-6)
        for v in self.gt_power.values():
            iscale.set_scaling_factor(v, 1e-8)
        for c in self.o2_flow.values():
            iscale.constraint_scaling_transform(c, 10)
        for c in self.gt_power_eqn.values():
            iscale.constraint_scaling_transform(c, 1e-8)
        for c in self.mx1.enthalpy_mixing_equations.values():
            iscale.constraint_scaling_transform(c, 1e-8)
        for c in self.mx2.enthalpy_mixing_equations.values():
            iscale.constraint_scaling_transform(c, 1e-8)
        for c in self.mx3.enthalpy_mixing_equations.values():
            iscale.constraint_scaling_transform(c, 1e-8)
        for c in self.inject1.enthalpy_mixing_equations.values():
            iscale.constraint_scaling_transform(c, 1e-8)
        for c in self.gts1.performance_curve.head_isen_eqn.values():
            iscale.constraint_scaling_transform(c, 1e-5)
        for c in self.gts1.performance_curve.eff_isen_eqn.values():
            iscale.constraint_scaling_transform(c, 2)
        for c in self.gts2.performance_curve.head_isen_eqn.values():
            iscale.constraint_scaling_transform(c, 1e-5)
        for c in self.gts2.performance_curve.eff_isen_eqn.values():
            iscale.constraint_scaling_transform(c, 2)
        for c in self.gts3.performance_curve.head_isen_eqn.values():
            iscale.constraint_scaling_transform(c, 1e-5)
        for c in self.gts3.performance_curve.eff_isen_eqn.values():
            iscale.constraint_scaling_transform(c, 2)
        for c in self.inject1.mxpress_eqn.values():
            iscale.constraint_scaling_transform(c, 1e-5)
        iscale.set_scaling_factor(self.ng_preheat.shell.heat, 1e-5)
        iscale.set_scaling_factor(self.ng_preheat.tube.heat, 1e-5)
        iscale.set_scaling_factor(
            self.ng_preheat.overall_heat_transfer_coefficient, 1e-2
        )
        iscale.set_scaling_factor(self.ng_preheat.area, 1e-3)

    def initialize(
        self,
        outlvl=idaeslog.NOTSET,
        solver=None,
        optarg=None,
        load_from="gas_turbine_init.json.gz",
        save_to="gas_turbine_init.json.gz",
    ):
        """Initialize the gas turbine flowsheet

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

        if load_from is not None:
            if os.path.exists(load_from):
                init_log.info_high(f"GT load initial from {load_from}")
                # here suffix=False avoids loading scaling factors
                iutil.from_json(
                    self, fname=load_from, wts=iutil.StoreSpec(suffix=False)
                )
                return

        init_log.info_high("Gas Turbine Initialization Starting")
        solver_obj = get_solver(solver, optarg)

        self.cmbout_o2_mol_frac.fix()

        # feeds
        self.feed_air1.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        self.feed_fuel1.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        # compressor
        propagate_state(self.air01)
        self.vsv.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.air02)
        self.cmp1.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        # splitter
        propagate_state(self.air03)
        self.splt1.split_fraction[0, "air05"].fix(0.0916985 * 0.73)
        self.splt1.split_fraction[0, "air07"].fix(0.0916985 * 0.27 * 0.59)
        self.splt1.split_fraction[0, "air09"].fix(0.0916985 * 0.27 * 0.41)
        self.splt1.initialize()
        self.splt1.split_fraction[0, "air05"].unfix()
        self.splt1.split_fraction[0, "air07"].unfix()
        self.splt1.split_fraction[0, "air09"].unfix()
        # inject
        propagate_state(self.air04a)
        self.inject_translator.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.air04b)
        propagate_state(self.fuel01)
        self.ng_preheat.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.fuel02)
        self.inject1.mixed_state[0].pressure = pyo.value(self.inject1.air.pressure[0])
        self.inject1.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        # combustor
        propagate_state(self.g01)
        self.cmb1.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        # gas turbine stage 1
        propagate_state(self.g02a)
        self.flue_translator.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.g02b)
        self.gts1.ratioP[0] = 0.7
        self.gts1.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        # blade cooling air valve01, and calculate a flow coefficent
        propagate_state(self.air05)
        self.valve01.Cv = 2
        self.valve01.Cv.unfix()
        self.valve01.valve_opening.fix(0.85)
        self.valve01.control_volume.properties_out[0].pressure.fix(
            pyo.value(self.gts1.control_volume.properties_out[0].pressure)
        )
        self.valve01.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        self.valve01.control_volume.properties_out[0].pressure.unfix()
        self.valve01.Cv.fix()
        self.valve01.valve_opening.unfix()
        # mixer 1
        propagate_state(self.air06a)
        self.translator1.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.air06b)
        propagate_state(self.g03)
        self.mx1.mixed_state[0].pressure = pyo.value(self.mx1.gas.pressure[0])
        self.mx1.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        # gas turbine stage 2
        propagate_state(self.g04)
        self.gts2.ratioP[0] = 0.7
        self.gts2.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        # blade cooling air valve02, and calculate a flow coefficent
        propagate_state(self.air07)
        self.valve02.Cv = 2
        self.valve02.Cv.unfix()
        self.valve02.valve_opening.fix(0.85)
        self.valve02.control_volume.properties_out[0].pressure.fix(
            pyo.value(self.gts2.control_volume.properties_out[0].pressure)
        )
        self.valve02.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        self.valve02.control_volume.properties_out[0].pressure.unfix()
        self.valve02.Cv.fix()
        self.valve02.valve_opening.unfix()
        # mixer 2
        propagate_state(self.air08a)
        self.translator2.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.air08b)
        propagate_state(self.g05)
        self.mx2.mixed_state[0].pressure = pyo.value(self.mx2.gas.pressure[0])
        self.mx2.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        # gas turbine stage 3
        propagate_state(self.g06)
        self.gts3.ratioP[0] = 0.7
        self.gts3.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        # blade cooling air valve03, and calculate a flow coefficent
        propagate_state(self.air09)
        self.valve03.Cv = 2
        self.valve03.Cv.unfix()
        self.valve03.valve_opening.fix(0.85)
        self.valve03.control_volume.properties_out[0].pressure.fix(
            pyo.value(self.gts3.control_volume.properties_out[0].pressure)
        )
        self.valve03.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        self.valve03.control_volume.properties_out[0].pressure.unfix()
        self.valve03.Cv.fix()
        self.valve03.valve_opening.unfix()
        # mixer 3
        propagate_state(self.air10a)
        self.translator3.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        propagate_state(self.air10b)
        propagate_state(self.g07)
        self.mx3.mixed_state[0].pressure = pyo.value(self.mx3.gas.pressure[0])
        self.mx3.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        # product blocks
        propagate_state(self.g08)
        self.exhaust_1.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        # Solve
        # iscale.constraint_autoscale_large_jac(m)
        solver_obj.solve(self, tee=True)

        # Run with a specific power output in pressure-driven flow mode
        self.feed_fuel1.flow_mol.unfix()
        # For initialization, flow was specified and and valve opening calculated
        self.valve01.control_volume.properties_in[0].flow_mol.unfix()
        self.valve02.control_volume.properties_in[0].flow_mol.unfix()
        self.valve03.control_volume.properties_in[0].flow_mol.unfix()
        # deltaP will be whatever is needed to satisfy the power requirment
        self.vsv.deltaP.unfix()
        # The compressor efficiency is a little high since it doesn't include
        # throttling in the valve use to approximate VSV.
        self.cmp1.efficiency_isentropic.fix(0.92)
        self.cmp1.ratioP.fix(17.5)  # lowering this ratio, just means less pressure
        # drop in the VSV valve, decresing throttle loss
        # Exhaust pressure will be a bit over ATM due to HRSG. This will come from
        # HRSG model when coupled to form NGCC model
        self.exhaust_1.pressure.fix(1.1e5)
        # Don't know how much blade cooling air is needed for off desing case, but
        # full load flows were based on WVU model.  For now just leave valves at
        # fixed opening.
        self.valve01.valve_opening.fix()
        self.valve02.valve_opening.fix()
        self.valve03.valve_opening.fix()
        # Feeds
        # Air at compressor inlet
        self.feed_air1.temperature.fix(288.15)
        self.feed_air1.pressure.fix(103421)
        # Gas at fuel injection
        self.feed_fuel1.temperature.fix(299.817)
        self.feed_fuel1.pressure.fix(3.10264e6)
        # It looks like the O2 or air/fuel ratio is actually determined to roughly
        # get a constant exhaust temperature.  In a real gas turbine there are
        # probably a lot of complex factors, but here we fix the exhaust temp.
        self.cmbout_o2_mol_frac.unfix()
        self.exhaust_1.temperature.fix(898)

        # Fix the gross power output
        self.gt_power[0].fix(-477e6)  # Watts negative because is power out
        # Solve
        solver_obj.solve(self, tee=True)

        if save_to is not None:
            iutil.to_json(self)
            if save_to is not None:
                iutil.to_json(self, fname=save_to)
                init_log.info_high(f"Initialization saved to {save_to}")

    @staticmethod
    def _stream_col_gen(tag_group):
        """Generate a stream table heading from a group of stream tags"""
        for tag in tag_group.values():
            spltstr = tag.doc.split(":")
            stream = spltstr[0].strip()
            col = f"{spltstr[1].strip()} ({tag.get_unit_str()})"
            yield tag, stream, col

    @staticmethod
    def _stream_table(tag_group):
        """Generate a stream table from a group of stream tags"""
        rows = set()
        cols = set()
        tags = []
        for tag, stream, col in GasTurbineFlowsheetData._stream_col_gen(tag_group):
            rows.add(stream)
            cols.add(col)
            tags.append((tag, stream, col))
        df = pd.DataFrame(index=sorted(rows), columns=sorted(cols))
        for tag, stream, col in tags:
            df.at[stream, col] = tag.get_display_value()
        return df

    def streams_dataframe(self):
        """Get a stream table as a Pandas DataFrame"""
        return self._stream_table(self.tags_streams)

    pfd_file = "gas_turbine_template.svg"

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
        s = svg_tag(svg=s, tag_group=self.tags_output, outfile=fname)
        if fname is None:
            return s
