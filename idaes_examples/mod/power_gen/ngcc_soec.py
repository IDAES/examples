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
import copy
import pyomo.environ as pyo
from pyomo.network import Arc
import idaes.models.unit_models as um  # um = unit models
from idaes.core import FlowsheetBlockData, declare_process_block_class
import idaes.core.util.scaling as iscale
import idaes.logger as idaeslog
from . import (ngcc, soec)
import idaes.core.util as iutil
from idaes.core.solvers import get_solver
from idaes.core.util.initialization import propagate_state


@declare_process_block_class(
    "NgccSoecFlowsheet",
    doc=(
        "This flowsheet combines an NGCC and SOEC that uses steam from the HRSG."
        "This is a design point only model."
    ),
)
class NgccSoecFlowsheetData(FlowsheetBlockData):
    def build(self):
        super().build()
        self._add_flowsheets()
        self._add_arcs()
        self._add_constraints()
        self._add_tags()

    def _add_flowsheets(self):
        self.ngcc = ngcc.NgccFlowsheet(dynamic=self.config.dynamic, time=self.time, time_units=self.config.time_units)
        self.soec = soec.SoecFlowsheet(dynamic=self.config.dynamic, time=self.time, time_units=self.config.time_units)

    def _add_arcs(self):
        self.c01 = Arc(
            source=self.ngcc.st.steam_turbine_lp_split.soec,
            destination=self.soec.feed_hx01.tube_inlet,
        )
        self.c02 = Arc(
            source=self.soec.makeup_mix.outlet,
            destination=self.ngcc.hrsg.mixer_soec.soec_makeup,
        )
        pyo.TransformationFactory("network.expand_arcs").apply_to(self)

    def _add_constraints(self):
        @self.Constraint(self.config.time)
        def sweep_pressure_eqn(b, t):
            return (
                b.soec.sweep_compressor.control_volume.properties_out[t].pressure
                == b.soec.feed_hx01.tube.properties_in[t].pressure
            )

    def _add_tags(self):
        tag_group = iutil.ModelTagGroup()
        self.tags_output = tag_group
        for k, tag in self.ngcc.tags_output.items():
            if k == "net_power":
                k = "ngcc_net_power"
            tag_group[k] = copy.copy(tag)
        for k, tag in self.soec.tags_output.items():
            tag_group[k] = copy.copy(tag)
        tag_group["net_power"] = iutil.ModelTag(
            doc="Net power output",
            expr=-self.ngcc.net_power[0] - self.soec.total_electric_power[0],
            format_string="{:.3f}",
            display_units=pyo.units.MW,
        )
        tag_group["sweep_out_frac"] = iutil.ModelTag(
            doc="Sweep recycle out fraction",
            expr=self.soec.sweep_recycle_split.split_fraction[0, "out"] * 100,
            format_string="{:.3f}",
            display_units="%",
        )
        tag_group["steam_out_frac"] = iutil.ModelTag(
            doc="Sweep recycle out fraction",
            expr=self.soec.feed_recycle_split.split_fraction[0, "out"] * 100,
            format_string="{:.3f}",
            display_units="%",
        )
        tag_group["heater_1_frac"] = iutil.ModelTag(
            doc="Makeup water split to heater 1",
            expr=self.soec.water_split.split_fraction[0, "outlet1"] * 100,
            format_string="{:.3f}",
            display_units="%",
        )
        tag_group["sweep_inlet_flow"] = iutil.ModelTag(
            doc="Sweep inlet flow",
            expr=self.soec.sweep_compressor.inlet.flow_mol[0],
            format_string="{:.3f}",
            display_units=pyo.units.mol / pyo.units.s,
        )
        tag_group["sweep_trim_temperature"] = iutil.ModelTag(
            doc="Sweep trim heater temperature",
            expr=self.soec.sweep_heater.control_volume.properties_out[0].temperature,
            format_string="{:.3f}",
            display_units=pyo.units.K,
        )
        tag_group["steam_trim_temperature"] = iutil.ModelTag(
            doc="Sweep trim heater temperature",
            expr=self.soec.feed_heater.control_volume.properties_out[0].temperature,
            format_string="{:.3f}",
            display_units=pyo.units.K,
        )

    def initialize(
        self,
        outlvl=idaeslog.NOTSET,
        solver=None,
        optarg=None,
        load_from="ngcc_soec_init.json.gz",
        save_to="ngcc_soec_init.json.gz",
    ):

        init_log = idaeslog.getInitLogger(self.name, outlvl, tag="flowsheet")
        solve_log = idaeslog.getSolveLogger(self.name, outlvl, tag="flowsheet")

        if load_from is not None:
            if os.path.exists(load_from):
                init_log.info(f"NGCC/SOEC design load initial from {load_from}")
                # here suffix=False avoids loading scaling factors
                iutil.from_json(
                    self, fname=load_from, wts=iutil.StoreSpec(suffix=False)
                )
                return
        solver_obj = get_solver(solver, optarg)
        self.ngcc.initialize(
            outlvl=outlvl,
            solver=solver,
            optarg=optarg,
            load_from="ngcc_init.json.gz",
            save_to="ngcc_init.json.gz",
        )
        self.soec.initialize(
            outlvl=outlvl,
            solver=solver,
            optarg=optarg,
            load_from="soec_init.json.gz",
            save_to="soec_init.json.gz",
        )
        self.soec.sweep_compressor.control_volume.properties_out[:].pressure.unfix()
        self.c01.expanded_block.deactivate()
        self.c02.expanded_block.deactivate()
        self.ngcc.hrsg.mixer_soec.soec_makeup.fix()
        self.soec.feed_hx01.tube_inlet.fix()
        self.soec.water_pump.inlet.flow_mol.fix()
        solver_obj.solve(self, tee=True)

        self.ngcc.st.steam_turbine_lp_split.split_fraction[0, "soec"].unfix()
        self.ngcc.st.steam_turbine_lp_split.soec.flow_mol.fix(3360)
        propagate_state(self.c02)
        solver_obj.solve(self, tee=True)

        propagate_state(self.c01)
        propagate_state(self.c02)
        solver_obj.solve(self, tee=True)

        self.ngcc.hrsg.mixer_soec.soec_makeup.unfix()
        self.soec.feed_hx01.tube_inlet.unfix()
        self.soec.feed_hx01.tube_inlet.flow_mol.unfix()
        self.soec.water_pump.inlet.flow_mol.fix(3360)
        self.c01.expanded_block.activate()
        self.c02.expanded_block.activate()
        solver_obj.solve(self, tee=True)

        # switch to 97% capture and set GT power to 477 for full load
        self.ngcc.net_power_mw.unfix()
        self.ngcc.gt.gt_power.fix(-477e6)
        self.ngcc.cap_specific_reboiler_duty.fix(2.4e6)
        self.ngcc.cap_fraction.fix(0.97)
        self.soec.cmp01.ratioP.fix(2.28)
        self.soec.cmp02.ratioP.fix(2.28)
        self.soec.cmp03.ratioP.fix(2.28)
        self.soec.cmp04.ratioP.unfix()
        self.soec.cmp04.control_volume.properties_out[:].pressure.fix(
            65 * pyo.units.bar
        )
        solver_obj.solve(self, tee=True)

        self.ngcc.st.steam_turbine_lp_split.soec.flow_mol.unfix()
        self.soec.hydrogen_product_rate.fix(5.0)
        self.soec.soec_single_pass_water_conversion.unfix()
        self.soec.soec_module.potential_cell.fix()
        self.soec.sweep_turbine.control_volume.properties_out[0].temperature.unfix()
        self.soec.sweep_turbine.control_volume.properties_out[0].pressure.fix(
            1.01 * pyo.units.bar
        )
        solver_obj.solve(self, tee=True)

        if save_to is not None:
            iutil.to_json(self)
            if save_to is not None:
                iutil.to_json(self, fname=save_to)
                init_log.info(f"Initialization saved to {save_to}")
