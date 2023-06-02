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

import re
import os
from pathlib import Path

import pandas as pd

import pyomo.environ as pyo
from pyomo.network import Arc
from pyomo.common.fileutils import this_file_dir

import idaes
from idaes.core.solvers import use_idaes_solver_configuration_defaults, get_solver
from idaes.core import FlowsheetBlockData, declare_process_block_class
from idaes.core.util.model_statistics import degrees_of_freedom
import idaes.models_extra.power_generation.unit_models.helm as helm
import idaes.models.unit_models as gum
from idaes.models.properties import iapws95
import idaes.core.util.initialization as iinit
import idaes.core.util.scaling as iscale
import idaes.core.util.tables as tables
from idaes.core.util.tags import svg_tag
import idaes.core.util as iutil
from idaes.core.util.initialization import propagate_state
import idaes.logger as idaeslog


@declare_process_block_class(
    "SteamTurbineFlowsheet",
    doc=(
        "The steam turbine flowsheet is base on NETL report 'Cost and Performance "
        "Baseline for Fossil Energy Plants Volume 1: Bituminous Coal and Natural "
        "Gas to Electricity.' Sept 2019, Case B31B."
    ),
)
class SteamTurbineFlowsheetData(FlowsheetBlockData):
    def build(self):
        super().build()
        self.prop_water = iapws95.Iapws95ParameterBlock()
        self._add_models()
        self._add_constraints()
        self._add_arcs()
        self._set_initial_inputs()
        self._add_tags()
        self._set_scaling()

    def _add_models(self):
        self.steam_turbine = helm.HelmTurbineMultistage(
            doc="Steam turbine",
            property_package=self.prop_water,
            num_parallel_inlet_stages=1,
            num_hp=7,  # full load ave P ratio about 0.8238 with inlet
            num_ip=10,  # full load ave P ratio about 0.8264
            num_lp=11,  # full load ave P ratio about 0.7194 with outlet
            hp_disconnect=[7],  # disconnected for reheater
            ip_disconnect=[10],  # disconnected for HRSG LP steam mix
        )
        self.steam_turbine_lp_mix = helm.HelmMixer(
            doc="Mix LP steam from HRSG into turbine LP steam.",
            property_package=self.prop_water,
            momentum_mixing_type=helm.MomentumMixingType.none,
            inlet_list=["turbine", "hrsg"],
        )
        self.steam_turbine_lp_split = helm.HelmSplitter(
            doc="Split off carbon capture steam.",
            property_package=self.prop_water,
            outlet_list=["turbine", "reboiler", "soec"],
        )
        self.dummy_reheat = gum.Heater(
            doc="Dummy reheater, can be deactivated to couple with HRSG.",
            property_package=self.prop_water,
        )
        self.main_condenser = helm.HelmNtuCondenser(
            doc="Main steam turbine condenser.",
            shell={
                "has_pressure_change": False,
                "property_package": self.prop_water,
            },
            tube={
                "has_pressure_change": False,
                "property_package": self.prop_water,
            },
        )
        self.hotwell = helm.HelmMixer(
            doc="Hotwell is a mixer to add makeup water.",
            momentum_mixing_type=helm.MomentumMixingType.none,
            inlet_list=["condensate", "makeup"],
            property_package=self.prop_water,
        )
        self.cond_pump = helm.HelmIsentropicCompressor(
            doc="Hotwell condensate pump", property_package=self.prop_water
        )
        self.return_mix = helm.HelmMixer(
            doc="Mixer for steam streams returning to HRSG.",
            property_package=self.prop_water,
            momentum_mixing_type=helm.MomentumMixingType.none,
            inlet_list=["pump", "reboiler", "dryer", "reclaimer"],
        )
        self.reboiler = gum.Heater(
            doc="Carbon capture system reboiler",
            property_package=self.prop_water,
        )

    def _add_constraints(self):
        # The mixer for LP steam from Turbine and HRSG is assumed to be at turbine P
        @self.steam_turbine_lp_mix.Constraint(self.time)
        def lp_mixer_pressure_constraint(b, t):
            return (
                1e-6 * b.turbine_state[t].pressure == 1e-6 * b.mixed_state[t].pressure
            )

        self.dummy_reheat.temperature_out = pyo.Var(self.time, initialize=850)

        @self.dummy_reheat.Constraint(self.time)
        def temperature_eqn(b, t):
            return (
                b.temperature_out[t] == b.control_volume.properties_out[t].temperature
            )

        self.dummy_reheat.temperature_out.fix(858)

        # The hotwell is assumed to be at the same pressure as the condenser.
        @self.hotwell.Constraint(self.time)
        def hotwell_pressure_constraint(b, t):
            return (
                1e-6 * b.condensate_state[t].pressure
                == 1e-6 * b.mixed_state[t].pressure
            )

        @self.return_mix.Constraint(self.time)
        def return_mixer_pressure_constraint(b, t):
            return 1e-6 * b.pump_state[t].pressure == 1e-6 * b.mixed_state[t].pressure

        # A few more variables and constraints
        self.hp_steam_temperature = pyo.Var(self.time, initialize=855)
        self.hot_reheat_temperature = pyo.Var(self.time, initialize=855)

        @self.Constraint(self.time)
        def main_steam_temperature_eqn(b, t):
            return (
                b.hp_steam_temperature[t]
                == b.steam_turbine.inlet_split.mixed_state[t].temperature
            )

        @self.Constraint(self.time)
        def reheat_steam_temperature_eqn(b, t):
            return (
                b.hot_reheat_temperature[t]
                == b.steam_turbine.ip_stages[1]
                .control_volume.properties_out[t]
                .temperature
            )

        @self.reboiler.Constraint(self.time)
        def reboiler_condense_eqn(b, t):
            return (
                b.control_volume.properties_out[t].enth_mol
                == b.control_volume.properties_out[t].enth_mol_sat_phase["Liq"] - 100
            )

    def _add_arcs(self):
        self.t02_dummy = Arc(
            doc="steam turbine to dummy reheater",
            source=self.steam_turbine.hp_stages[7].outlet,
            destination=self.dummy_reheat.inlet,
        )
        self.t03_dummy = Arc(
            doc="dummy reheater to steam turbine",
            source=self.dummy_reheat.outlet,
            destination=self.steam_turbine.ip_stages[1].inlet,
        )
        self.t04 = Arc(
            doc="steam turbine to LP steam mixer",
            source=self.steam_turbine.ip_stages[10].outlet,
            destination=self.steam_turbine_lp_mix.turbine,
        )
        self.t16 = Arc(
            doc="LP steam mixer to splitter for carbon capture steam",
            source=self.steam_turbine_lp_mix.outlet,
            destination=self.steam_turbine_lp_split.inlet,
        )
        self.t06 = Arc(
            doc="LP steam splitter to turbine",
            source=self.steam_turbine_lp_split.turbine,
            destination=self.steam_turbine.lp_stages[1].inlet,
        )

        self.t07 = Arc(
            doc="Steam turbine to condenser",
            source=self.steam_turbine.outlet_stage.outlet,
            destination=self.main_condenser.shell_inlet,
        )
        self.t08 = Arc(
            doc="Condenser to hotwell",
            source=self.main_condenser.shell_outlet,
            destination=self.hotwell.condensate,
        )
        self.t09 = Arc(
            doc="Hotwell to condensate pump",
            source=self.hotwell.outlet,
            destination=self.cond_pump.inlet,
        )
        self.t10 = Arc(
            doc="condnesate pump to the return steam mixer",
            source=self.cond_pump.outlet,
            destination=self.return_mix.pump,
        )
        self.t13 = Arc(
            source=self.reboiler.outlet, destination=self.return_mix.reboiler
        )
        self.t17 = Arc(
            source=self.steam_turbine_lp_split.reboiler, destination=self.reboiler.inlet
        )
        pyo.TransformationFactory("network.expand_arcs").apply_to(self)

    def _set_initial_inputs(self):
        # set some inputs and get ready to initialize
        # Set the inlet of the turbine
        p = 16.5e6
        hin = pyo.value(iapws95.htpx(T=857 * pyo.units.K, P=p * pyo.units.Pa))
        self.steam_turbine.inlet_split.inlet.enth_mol[0].fix(hin)
        self.steam_turbine.inlet_split.inlet.flow_mol[0].fix(7.4e3)
        self.steam_turbine.inlet_split.inlet.pressure[0].fix(p)
        # set conditions for disconnected IP section, will take flow from HP
        p = 3.5e6
        hin = pyo.value(iapws95.htpx(T=855 * pyo.units.K, P=p * pyo.units.Pa))
        self.steam_turbine.ip_stages[1].inlet.flow_mol[0].value = 6.5064e3
        self.steam_turbine.ip_stages[1].inlet.enth_mol[0].value = hin
        self.steam_turbine.ip_stages[1].inlet.pressure[0].value = p
        # set conditions for disconnected LP section, will take flow from HP
        p = 0.6e6
        hin = pyo.value(iapws95.htpx(T=573 * pyo.units.K, P=p * pyo.units.Pa))
        self.steam_turbine.lp_stages[1].inlet.flow_mol[0].value = 9.1e3
        self.steam_turbine.lp_stages[1].inlet.enth_mol[0].value = hin
        self.steam_turbine.lp_stages[1].inlet.pressure[0].value = p
        # use same conditions for lp steam from HRSG, but also specify flow
        hin = pyo.value(iapws95.htpx(T=601 * pyo.units.K, P=p * pyo.units.Pa))
        self.steam_turbine_lp_mix.hrsg.enth_mol.fix(hin)
        self.steam_turbine_lp_mix.hrsg.pressure.fix(p)
        self.steam_turbine_lp_mix.hrsg.flow_mol.fix(3000)

        self.steam_turbine_lp_split.split_fraction[0, "soec"].fix(1e-5)
        self.steam_turbine_lp_split.reboiler.flow_mol.fix(4000.0)

        for i, s in self.steam_turbine.hp_stages.items():
            s.ratioP[:] = 0.8238
            s.efficiency_isentropic[:] = 0.92
            iscale.set_scaling_factor(s.control_volume.work, 1e-6)
        for i, s in self.steam_turbine.ip_stages.items():
            s.ratioP[:] = 0.8264
            s.efficiency_isentropic[:] = 0.91
            iscale.set_scaling_factor(s.control_volume.work, 1e-6)
        for i, s in self.steam_turbine.lp_stages.items():
            s.ratioP[:] = 0.754
            s.efficiency_isentropic[:] = 0.90
            iscale.set_scaling_factor(s.control_volume.work, 1e-6)

        self.steam_turbine.outlet_stage.eff_dry.fix(0.90)
        self.steam_turbine.outlet_stage.design_exhaust_flow_vol.fix(1860)
        # Unfix the main steam flow for pressure driven flow
        self.steam_turbine.inlet_split.inlet.flow_mol.unfix()
        self.steam_turbine.outlet_stage.control_volume.properties_out[0].pressure.fix(
            0.01e6
        )
        # equal outlet pressure from the throttle valves
        self.steam_turbine.inlet_mix.use_equal_pressure_constraint()
        # setup the parallel inlet stages
        for i, s in self.steam_turbine.inlet_stage.items():
            iscale.set_scaling_factor(s.control_volume.work, 1e-6)
            s.ratioP[0] = 0.82
            self.steam_turbine.throttle_valve[i].Cv.fix()
            self.steam_turbine.throttle_valve[i].valve_opening.fix(0.85)
        iscale.set_scaling_factor(
            self.steam_turbine.outlet_stage.control_volume.work, 1e-6
        )

        self.main_condenser.tube_inlet.flow_mol.fix(2e5)
        self.main_condenser.tube_inlet.enth_mol.fix(1800)
        self.main_condenser.tube_inlet.pressure.fix(5e5)
        self.main_condenser.area.fix(5000)
        self.main_condenser.overall_heat_transfer_coefficient.fix(15000)

        self.hotwell.makeup.flow_mol[:].fix(1)
        self.hotwell.makeup.enth_mol.fix(2500)
        self.hotwell.makeup.pressure.fix(101325)
        self.cond_pump.efficiency_isentropic.fix(0.80)
        self.cond_pump.control_volume.properties_out[0].pressure.fix(655000)

        p = 2e6
        hin = pyo.value(iapws95.htpx(T=487 * pyo.units.K, P=p * pyo.units.Pa))
        self.return_mix.reclaimer.enth_mol[0].fix(hin)
        self.return_mix.reclaimer.flow_mol[0].fix(0.036)
        self.return_mix.reclaimer.pressure[0].fix(p)
        p = 1.6e6
        hin = pyo.value(iapws95.htpx(T=476 * pyo.units.K, P=p * pyo.units.Pa))
        self.return_mix.dryer.enth_mol[0].fix(hin)
        self.return_mix.dryer.flow_mol[0].fix(0.0019)
        self.return_mix.dryer.pressure[0].fix(p)

    def _set_scaling(self):
        iscale.set_scaling_factor(self.dummy_reheat.control_volume.heat, 1e-6)
        iscale.set_scaling_factor(self.main_condenser.shell.heat, 1e-6)
        iscale.set_scaling_factor(self.main_condenser.tube.heat, 1e-6)
        iscale.set_scaling_factor(self.cond_pump.control_volume.work, 1e-6)
        iscale.set_scaling_factor(
            self.steam_turbine.throttle_valve[1].control_volume.deltaP, 1e-3
        )
        iscale.set_scaling_factor(
            self.steam_turbine.outlet_stage.control_volume.properties_out[0.0].pressure,
            1e-3,
        )
        iscale.set_scaling_factor(
            self.steam_turbine.outlet_stage.control_volume.properties_out[0.0].pressure,
            1e-3,
        )
        iscale.set_scaling_factor(self.reboiler.control_volume.heat, 1e-7)

    def initialize(
        self,
        outlvl=idaeslog.NOTSET,
        solver=None,
        optarg=None,
        load_from="steam_turbine_init.json.gz",
        save_to="steam_turbine_init.json.gz",
    ):
        """Initialize the steam turbine flowsheet

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

        init_log.info_high("Steam Turbine Initialization Starting")
        solver_obj = get_solver(solver, optarg)

        if load_from is not None:
            if os.path.exists(load_from):
                init_log.info_high(f"ST load initial from {load_from}")
                # here suffix=False avoids loading scaling factors
                iutil.from_json(
                    self, fname=load_from, wts=iutil.StoreSpec(suffix=False)
                )
                return

        # This initializtion will use the inlet stage pressure ratios to
        # calculate flow coefficients for the inlet stages and the steam flow to
        # calculate the flow coefficient for the outlet stage.
        # fix the IP and LP inlets since they are disconnected
        self.steam_turbine.ip_stages[1].inlet.fix()
        self.steam_turbine.lp_stages[1].inlet.fix()
        self.steam_turbine.initialize(
            outlvl=outlvl,
            solver=solver,
            optarg=optarg,
            copy_disconnected_flow=False,
            calculate_inlet_cf=True,
            calculate_outlet_cf=True,
        )
        self.steam_turbine.ip_stages[1].inlet.unfix()
        self.steam_turbine.lp_stages[1].inlet.unfix()

        iinit.propagate_state(arc=self.t02_dummy)
        self.dummy_reheat.initialize(outlvl=outlvl, solver=solver, optarg=optarg)

        iinit.propagate_state(arc=self.t03_dummy)
        iinit.propagate_state(arc=self.t04)
        self.steam_turbine_lp_mix.initialize(
            outlvl=outlvl, solver=solver, optarg=optarg
        )

        iinit.propagate_state(self.t16)
        self.steam_turbine_lp_split.initialize(
            outlvl=outlvl, solver=solver, optarg=optarg
        )

        iinit.propagate_state(self.t17)
        self.reboiler.initialize(outlvl=outlvl, solver=solver, optarg=optarg)
        iinit.propagate_state(self.t13)

        iinit.propagate_state(arc=self.t06)
        iinit.propagate_state(arc=self.t07)
        self.main_condenser.initialize(
            outlvl=outlvl, solver=solver, optarg=optarg, unfix="pressure"
        )

        iinit.propagate_state(arc=self.t08)
        self.hotwell.initialize(outlvl=outlvl, solver=solver, optarg=optarg)

        iinit.propagate_state(arc=self.t09)
        self.cond_pump.initialize(outlvl=outlvl, solver=solver, optarg=optarg)

        # Unfix the turbine outlet pressure, determined by the condenser model
        self.steam_turbine.outlet_stage.control_volume.properties_out[
            0
        ].pressure.unfix()

        with idaeslog.solver_log(solve_log, idaeslog.DEBUG) as slc:
            res = solver_obj.solve(self, tee=slc.tee)
        if not pyo.check_optimal_termination(res):
            raise InitializationError(f"steam turbine failed to initialize.")

        # Adjust flow coefficient for steam extraction
        self.steam_turbine.outlet_stage.flow_coeff.fix(0.09)

        with idaeslog.solver_log(solve_log, idaeslog.DEBUG) as slc:
            res = solver_obj.solve(self, tee=slc.tee)
        if not pyo.check_optimal_termination(res):
            raise InitializationError(f"steam turbine failed to initialize.")

        if save_to is not None:
            iutil.to_json(self)
            if save_to is not None:
                iutil.to_json(self, fname=save_to)
                init_log.info_high(f"Initialization saved to {save_to}")
        init_log.info("Steam turbine flowsheet initialization complete.")

    def _add_tags(self):
        tag_group = iutil.ModelTagGroup()
        self.tags_steam_streams = tag_group
        stream_states = tables.stream_states_dict(
            tables.arcs_to_stream_dict(
                self,
                additional={  # streams that are half in HRSG, and may not have arcs
                    "t01": self.steam_turbine.inlet_split.inlet,
                    "t02": self.steam_turbine.hp_stages[7].outlet,
                    "t03": self.steam_turbine.ip_stages[1].inlet,
                    "t05": self.steam_turbine_lp_mix.hrsg,
                    "t11": self.return_mix.outlet,
                    "t12": self.hotwell.makeup,
                    "t13": self.return_mix.reboiler,
                    "t14": self.return_mix.dryer,
                    "t15": self.return_mix.reclaimer,
                    "t17": self.steam_turbine_lp_split.reboiler,
                    "t18": self.steam_turbine_lp_split.soec,
                    "cw01": self.main_condenser.tube_inlet,
                    "cw02": self.main_condenser.tube_outlet,
                },
                descend_into=False,
            )
        )
        for i, s in stream_states.items():
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
        # Tag some important model quntities
        self.tags = iutil.ModelTagGroup()
        self.tags["power"] = iutil.ModelTag(
            doc=f"Steam turbine electric power output",
            expr=self.steam_turbine.power[0],
            format_string="{:.2f}",
            display_units=pyo.units.MW,
        )

    pfd_file = "steam_turbine_template.svg"

    def write_pfd(self, fname=None):
        """Add model results to the flowsheet template.  If fname is specified,
        this saves the resulting svg to a file.  If fname is not specified, it
        returns the svg string.
        Args:
            fname: Name of file to save svg.  If None, return the svg string
            file_dir: If True, look for PFD file in the same directory as this module; otherwise in the
                      current working directory (e.g., next to the Jupyter Notebook).
        Returns: (None or Str)
        """
        input_file = Path.cwd() / self.pfd_file
        with open(input_file, "r") as f:
            s = svg_tag(svg=f, tag_group=self.tags_steam_streams, outfile=fname)
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
        for tag, stream, col in SteamTurbineFlowsheetData._stream_col_gen(tag_group):
            rows.add(stream)
            cols.add(col)
            tags.append((tag, stream, col))
        df = pd.DataFrame(index=sorted(rows), columns=sorted(cols))
        for tag, stream, col in tags:
            df.at[stream, col] = tag.get_display_value()
        return df

    def steam_streams_dataframe(self):
        return self._stream_table(self.tags_steam_streams)
