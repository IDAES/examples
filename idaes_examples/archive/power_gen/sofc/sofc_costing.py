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

import pandas as pd

import pyomo.environ as pyo
from pyomo.environ import units as pyunits
from pyomo.util.calc_var_value import calculate_variable_from_constraint

import idaes.core.util as iutil
from idaes.core import UnitModelBlock, UnitModelCostingBlock

from idaes.models_extra.power_generation.costing.power_plant_capcost import (
    QGESSCosting,
    QGESSCostingData
)


def cost_custom(blk):
    pass


def get_capital_cost(m):
    CE_index_year = "2018"
    m.fs.costing = QGESSCosting()
    ########################################
    # custom costs from NGFC Pathway study #
    ########################################

    # natural gas desulfurizer
    m.fs.desulfurizer = UnitModelBlock()
    m.fs.desulfurizer.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=cost_custom
    )
    m.fs.desulfurizer.costing.total_plant_cost = pyo.Var(
        initialize=2,
        bounds=(0, 4),
        units=pyunits.MUSD_2018,
        doc='equipment total plant cost in MM$'
    )

    # this correlation is valid between 50,000 - 150,000 acfh at 500 psia
    # we are assuming the natural gas is desulfurized at its pipeline pressure
    # of 500 psia
    # equation gives cost in 2018 dollars
    @m.fs.desulfurizer.costing.Constraint()
    def desulfurizer_total_plant_cost(c):
        pressure_current = m.fs.anode_mix.feed_inlet_state[0].pressure
        pressure_actual = 3447.38*pyunits.kPa
        ng_flow_vol = pyunits.convert(
            m.fs.anode_mix.feed_inlet_state[0].flow_vol *
            (pressure_current/pressure_actual),
            pyunits.ft**3/pyunits.hr)
        return c.total_plant_cost == (16.085*ng_flow_vol + 246934)*1e-6

    # anode heat exchanger
    m.fs.anode_hx.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=cost_custom
    )
    m.fs.anode_hx.costing.total_plant_cost = pyo.Var(
        initialize=0.2,
        bounds=(0, 10),
        units=pyunits.MUSD_2018,
        doc='equipment total plant cost in MM$'
    )

    @m.fs.anode_hx.costing.Constraint()
    def anode_hx_total_plant_cost(c):
        area_ft = pyunits.convert(m.fs.anode_hx.area, pyunits.ft**2)
        return c.total_plant_cost == (81.88*area_ft)*1e-6

    # cathode heat exchanger
    m.fs.cathode_hx.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=cost_custom
    )
    m.fs.cathode_hx.costing.total_plant_cost = pyo.Var(
        initialize=20,
        bounds=(0, 40),
        units=pyunits.MUSD_2018,
        doc='equipment total plant cost in MM$'
    )

    @m.fs.cathode_hx.costing.Constraint()
    def cathode_hx_total_plant_cost(c):
        area = pyunits.convert(m.fs.cathode_hx.area, pyunits.ft**2)
        return c.total_plant_cost == (81.88*area)*1e-6

    # calculations for number of sections
    # stacks contain 100 cell
    # modules contain 64 stacks
    # sections contain 16 modules
    cell_area = 550*pyunits.cm**2
    extra_installed_area = 1.10  # extra stacks to account for degradation

    actual_module_rating = pyunits.convert(
        (cell_area*100*64 * m.fs.sofc.stack_voltage*pyunits.V *
         m.fs.sofc.current_density*pyunits.A/pyunits.m**2),
        pyunits.kW
    )
    n_sections = (
        16*actual_module_rating/(extra_installed_area*m.fs.sofc_power_dc)
    )

    # cathode air blower
    m.fs.air_blower.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=cost_custom
    )
    m.fs.air_blower.costing.total_plant_cost = pyo.Var(
        initialize=2,
        bounds=(0, 4),
        units=pyunits.MUSD_2018,
        doc='equipment total plant cost in MM$'
    )

    @m.fs.air_blower.costing.Constraint()
    def air_blower_total_plant_cost(c):
        acfm = pyunits.convert(
            m.fs.air_blower.control_volume.properties_in[0].flow_vol,
            pyunits.ft**3/pyunits.min
        )
        t = m.fs.air_blower.control_volume.properties_in[0].temperature
        p = m.fs.air_blower.control_volume.properties_in[0].pressure
        scfm = acfm * (273.15*pyunits.K/t) * (p/101.325*pyunits.kPa)
        return c.total_plant_cost == (
            1e-3 * n_sections * 10.9995 *
            pyo.exp(
                0.4692 +
                0.1203*pyo.log(scfm/1000/n_sections) +
                0.0931*pyo.log(scfm/1000/n_sections)**2
                )
            )

    # anode recycle blower
    m.fs.anode_blower.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=cost_custom
    )
    m.fs.anode_blower.costing.total_plant_cost = pyo.Var(
        initialize=1,
        bounds=(0, 2),
        units=pyunits.MUSD_2018,
        doc='equipment total plant cost in MM$'
    )

    @m.fs.anode_blower.costing.Constraint()
    def anode_blower_total_plant_cost(c):
        acfm = pyunits.convert(
            m.fs.anode_blower.control_volume.properties_in[0].flow_vol,
            pyunits.ft**3/pyunits.min
        )
        t = m.fs.anode_blower.control_volume.properties_in[0].temperature
        p = m.fs.anode_blower.control_volume.properties_in[0].pressure
        scfm = acfm * (273.15*pyunits.K/t) * (p/101.325*pyunits.kPa)
        return c.total_plant_cost == (
            1e-3 * n_sections * 10.9995 *
            pyo.exp(
                0.4692 +
                0.1203*pyo.log(scfm/1000/n_sections) +
                0.0931*pyo.log(scfm/1000/n_sections)**2
                )
            )

    # cathode recycle blower
    m.fs.cathode_blower.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=cost_custom
    )
    m.fs.cathode_blower.costing.total_plant_cost = pyo.Var(
        initialize=4,
        bounds=(0, 8),
        units=pyunits.MUSD_2018,
        doc='equipment total plant cost in MM$'
    )

    @m.fs.cathode_blower.costing.Constraint()
    def cathode_blower_total_plant_cost(c):
        acfm = pyunits.convert(
            m.fs.cathode_blower.control_volume.properties_in[0].flow_vol,
            pyunits.ft**3/pyunits.min
        )
        t = m.fs.cathode_blower.control_volume.properties_in[0].temperature
        p = m.fs.cathode_blower.control_volume.properties_in[0].pressure
        scfm = acfm * (273.15*pyunits.K/t) * (p/101.325*pyunits.kPa)
        return c.total_plant_cost == (
            1e-3 * n_sections * 27.499 *
            pyo.exp(
                0.4692 +
                0.1203*pyo.log(scfm/1000/n_sections) +
                0.0931*pyo.log(scfm/1000/n_sections)**2
                )
            )

    # SOFC modules
    m.fs.sofc_modules = UnitModelBlock()
    m.fs.sofc_modules.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=cost_custom
    )
    m.fs.sofc_modules.costing.total_plant_cost = pyo.Var(
        initialize=190,
        bounds=(0, 300),
        units=pyunits.MUSD_2018,
        doc='equipment total plant cost in MM$'
    )

    @m.fs.sofc_modules.costing.Constraint()
    def sofc_module_total_plant_cost(c):
        nominal_module_rating = 1126.4*pyunits.kW
        nominal_module_cost = 345.88*pyunits.USD_2018/pyunits.kW
        actual_module_cost = (
            nominal_module_cost*(nominal_module_rating/actual_module_rating)
        )
        return c.total_plant_cost == 1e-6*(
            extra_installed_area * actual_module_cost * m.fs.sofc_power_ac[0]
            )

    # air separation unit
    m.fs.asu.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=cost_custom
    )
    m.fs.asu.costing.total_plant_cost = pyo.Var(
        initialize=76,
        bounds=(0, 200),
        units=pyunits.MUSD_2018,
        doc='equipment total plant cost in MM$'
    )

    @m.fs.asu.costing.Constraint()
    def asu_total_plant_cost(c):
        O2_flow_mass = pyunits.convert(
            m.fs.ASU_O2_outlet.outlet.flow_mol[0] * 32*pyunits.g/pyunits.mol,
            pyunits.ton/pyunits.day
        )
        ref_cost = 326*pyunits.MUSD_2018
        ref_param = 13079*pyunits.ton/pyunits.day
        return c.total_plant_cost == (
            ref_cost*(O2_flow_mass/ref_param)**0.7 *
            1.0969 * 1.1 * 1.034 * 585.1/566.2
            )

    # oxycombustor
    m.fs.oxycombustor.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=cost_custom
    )
    m.fs.oxycombustor.costing.total_plant_cost = pyo.Var(
        initialize=20,
        bounds=(0, 40),
        units=pyunits.MUSD_2018,
        doc='equipment total plant cost in MM$'
    )

    @m.fs.oxycombustor.costing.Constraint()
    def oxycombustor_total_plant_cost(c):
        oxy_heat = pyunits.convert(
            2 * m.fs.oxycombustor.rate_reaction_extent[0, "h2_cmb"] *
            241.9*pyunits.kJ/pyunits.mol +
            2 * m.fs.oxycombustor.rate_reaction_extent[0, "co_cmb"] *
            283*pyunits.kJ/pyunits.mol +
            m.fs.oxycombustor.rate_reaction_extent[0, "ch4_cmb"] *
            802.7*pyunits.kJ/pyunits.mol,
            pyunits.MBtu/pyunits.hr)
        return c.total_plant_cost == (
            40*(oxy_heat)**0.82 * 585.1/325 * 1.3 * 1e-3
            )

    # CO2 purification unit
    m.fs.cpu_cost = UnitModelBlock()
    m.fs.cpu_cost.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=cost_custom
    )
    m.fs.cpu_cost.costing.total_plant_cost = pyo.Var(
        initialize=82,
        bounds=(0, 160),
        units=pyunits.MUSD_2018,
        doc='equipment total plant cost in MM$'
    )

    @m.fs.cpu_cost.costing.Constraint()
    def cpu_total_plant_cost(c):
        cpu_load = pyunits.convert(
            m.fs.cpu.work[0],
            pyunits.MW
        )
        cpu_flow = pyunits.convert(
            m.fs.cpu.pureco2.flow_mol[0] * 0.0224*pyunits.m**3/pyunits.mol,
            pyunits.m**3/pyunits.hr
        )
        ref_tpc = 82.465*pyunits.MUSD_2018
        ref_load = 23.1*pyunits.MW
        ref_flow = 90941*pyunits.m**3/pyunits.hr
        return c.total_plant_cost == (
            0.5*ref_tpc*(cpu_load/ref_load)**0.7 +
            0.5*ref_tpc*(cpu_flow/ref_flow)**0.65)

    #######################################################
    # capital costs from fossil energy baseline estimates #
    #######################################################

    # feedwater systems
    # scales on boiler feed water circulation rate in lb/hr
    m.fs.feedwater_system = UnitModelBlock()
    m.fs.feedwater_system.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=QGESSCostingData.get_PP_costing,
        costing_method_arguments={
            "cost_accounts": ["3.1", "3.3", "8.4"],
            "scaled_param": m.fs.feedwater_flow[0],
            "tech": 6,
            "ccs": "B",
            "CE_index_year": CE_index_year,
        }
    )
    # water makeup systems
    # scales on raw water withdrawal in gpm
    m.fs.makeup_water_system = UnitModelBlock()
    m.fs.makeup_water_system.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=QGESSCostingData.get_PP_costing,
        costing_method_arguments={
            "cost_accounts": ["3.2", "3.4", "3.5", "9.5", "14.6"],
            "scaled_param": m.fs.raw_water_withdrawal[0],
            "tech": 6,
            "ccs": "B",
            "CE_index_year": CE_index_year,
        }
    )
    # waste water treatment
    m.fs.waste_water_system = UnitModelBlock()
    m.fs.waste_water_system.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=QGESSCostingData.get_PP_costing,
        costing_method_arguments={
            "cost_accounts": ["3.7"],
            "scaled_param": m.fs.process_water_discharge[0],
            "tech": 6,
            "ccs": "B",
            "CE_index_year": CE_index_year,
        }
    )
    # natural gas pipeline, start-up system, and misc. equipment
    # scales on natural gas flowrate in lb/hr
    m.fs.gas_systems = UnitModelBlock()
    m.fs.gas_systems.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=QGESSCostingData.get_PP_costing,
        costing_method_arguments={
            "cost_accounts": ["3.6", "3.9"],
            "scaled_param": m.fs.natural_gas_flow_mass[0],
            "tech": 6,
            "ccs": "B",
            "CE_index_year": CE_index_year,
        }
    )
    # HRSG and ductwork
    m.fs.hrsg_and_ducts = UnitModelBlock()
    m.fs.hrsg_and_ducts.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=QGESSCostingData.get_PP_costing,
        costing_method_arguments={
            "cost_accounts": ["7.1", "7.2"],
            "scaled_param": m.fs.steam_cycle_heat_duty[0],
            "tech": 6,
            "ccs": "B",
            "CE_index_year": CE_index_year,
        }
    )
    # smokestack
    m.fs.smokestack = UnitModelBlock()
    m.fs.smokestack.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=QGESSCostingData.get_PP_costing,
        costing_method_arguments={
            "cost_accounts": ["7.3", "7.4", "7.5"],
            "scaled_param": m.fs.smokestack_flow_vol[0],
            "tech": 6,
            "ccs": "B",
            "CE_index_year": CE_index_year,
        }
    )
    # steam turbine and generator
    m.fs.steam_turbine = UnitModelBlock()
    m.fs.steam_turbine.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=QGESSCostingData.get_PP_costing,
        costing_method_arguments={
            "cost_accounts": ["8.1", "8.2", "8.5", "14.3"],
            "scaled_param": pyunits.convert(m.fs.steam_cycle_power[0],
                                            pyunits.kW),
            "tech": 6,
            "ccs": "B",
            "CE_index_year": CE_index_year,
        }
    )
    # steam cycle condenser
    m.fs.hrsg_condenser = UnitModelBlock()
    m.fs.hrsg_condenser.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=QGESSCostingData.get_PP_costing,
        costing_method_arguments={
            "cost_accounts": ["8.3"],
            "scaled_param": m.fs.condenser_duty[0],
            "tech": 6,
            "ccs": "B",
            "CE_index_year": CE_index_year,
        }
    )
    # cooling tower
    m.fs.cooling_tower = UnitModelBlock()
    m.fs.cooling_tower.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=QGESSCostingData.get_PP_costing,
        costing_method_arguments={
            "cost_accounts": ["9.1"],
            "scaled_param": m.fs.cooling_water_duty[0],
            "tech": 6,
            "ccs": "B",
            "CE_index_year": CE_index_year,
        }
    )
    # cooling water system
    m.fs.cooling_water_system = UnitModelBlock()
    m.fs.cooling_water_system.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=QGESSCostingData.get_PP_costing,
        costing_method_arguments={
            "cost_accounts": ["9.2", "9.3", "9.4", "9.6", "9.7", "14.5"],
            "scaled_param": m.fs.cooling_water_flow[0],
            "tech": 6,
            "ccs": "B",
            "CE_index_year": CE_index_year,
        }
    )
    # accessory electric equipment
    m.fs.accessory_electric_systems = UnitModelBlock()
    m.fs.accessory_electric_systems.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=QGESSCostingData.get_PP_costing,
        costing_method_arguments={
            "cost_accounts": ["11.2", "11.3", "11.4", "11.5", "11.6"],
            "scaled_param": m.fs.auxiliary_load[0],
            "tech": 6,
            "ccs": "B",
            "CE_index_year": CE_index_year,
        }
    )
    # generator and standby equipment
    m.fs.generator = UnitModelBlock()
    m.fs.generator.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=QGESSCostingData.get_PP_costing,
        costing_method_arguments={
            "cost_accounts": ["11.1", "11.7", "11.9"],
            "scaled_param": m.fs.gross_power[0],
            "tech": 6,
            "ccs": "B",
            "CE_index_year": CE_index_year,
        }
    )
    # transformers
    m.fs.transformers = UnitModelBlock()
    m.fs.transformers.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=QGESSCostingData.get_PP_costing,
        costing_method_arguments={
            "cost_accounts": ["11.8"],
            "scaled_param": 1.05*m.fs.gross_power[0],
            "tech": 6,
            "ccs": "B",
            "CE_index_year": CE_index_year,
        }
    )
    # instrumentation and control
    m.fs.ic_systems = UnitModelBlock()
    m.fs.ic_systems.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=QGESSCostingData.get_PP_costing,
        costing_method_arguments={
            "cost_accounts": ["12.3", "12.5", "12.6", "12.7", "12.8", "12.9"],
            "scaled_param": m.fs.auxiliary_load[0],
            "tech": 6,
            "ccs": "B",
            "CE_index_year": CE_index_year,
        }
    )
    # improvements to site and buildings
    m.fs.improvements_and_buildings = UnitModelBlock()
    m.fs.improvements_and_buildings.costing = UnitModelCostingBlock(
        flowsheet_costing_block=m.fs.costing,
        costing_method=QGESSCostingData.get_PP_costing,
        costing_method_arguments={
            "cost_accounts": [
                "13.1", "13.2", "13.3", "14.4", "14.7", "14.8", "14.9", "14.10"
            ],
            "scaled_param": m.fs.gross_power[0],
            "tech": 6,
            "ccs": "B",
            "CE_index_year": CE_index_year,
        }
    )

    m.fs.costing.get_total_TPC(CE_index_year)

    m.fs.costing.total_overnight_cost = pyo.Var(
        initialize=900,
        bounds=(0, 2000),
        units=pyunits.MUSD_2018
    )
    m.fs.costing.total_as_spent_cost = pyo.Var(
        initialize=995,
        bounds=(0, 2000),
        units=pyunits.MUSD_2018
    )
    m.fs.costing.annualized_tasc = pyo.Var(
        initialize=70,
        bounds=(0, 200),
        units=pyunits.MUSD_2018/pyunits.yr
    )

    @m.fs.costing.Constraint()
    def total_overnight_cost_eq(c):
        return c.total_overnight_cost == 1.21*c.total_TPC

    @m.fs.costing.Constraint()
    def total_as_spent_cost_eq(c):
        return c.total_as_spent_cost == 1.093*c.total_overnight_cost

    @m.fs.costing.Constraint()
    def annualized_tasc_eq(c):
        return c.annualized_tasc == 0.0707*c.total_as_spent_cost

    initialize_capital_cost(m)

    # adding some expressions for grouping capital costs when reporting results
    @m.fs.costing.Expression()
    def sofc_bop_cost(b):
        return (
            m.fs.desulfurizer.costing.total_plant_cost +
            m.fs.anode_blower.costing.total_plant_cost +
            m.fs.anode_hx.costing.total_plant_cost +
            m.fs.air_blower.costing.total_plant_cost +
            m.fs.cathode_blower.costing.total_plant_cost +
            m.fs.cathode_hx.costing.total_plant_cost
        )

    @m.fs.costing.Expression()
    def feedwater_bop_cost(b):
        return (
            m.fs.feedwater_system.costing.total_plant_cost["3.1"] +
            m.fs.makeup_water_system.costing.total_plant_cost["3.2"] +
            m.fs.feedwater_system.costing.total_plant_cost["3.3"] +
            m.fs.makeup_water_system.costing.total_plant_cost["3.4"] +
            m.fs.makeup_water_system.costing.total_plant_cost["3.5"] +
            m.fs.gas_systems.costing.total_plant_cost["3.6"] +
            m.fs.waste_water_system.costing.total_plant_cost["3.7"] +
            m.fs.gas_systems.costing.total_plant_cost["3.9"]
        )

    @m.fs.costing.Expression()
    def hrsg_ductwork_and_stack_cost(b):
        return (
            m.fs.hrsg_and_ducts.costing.total_plant_cost["7.1"] +
            m.fs.hrsg_and_ducts.costing.total_plant_cost["7.2"] +
            m.fs.smokestack.costing.total_plant_cost["7.3"] +
            m.fs.smokestack.costing.total_plant_cost["7.4"] +
            m.fs.smokestack.costing.total_plant_cost["7.5"]
        )

    @m.fs.costing.Expression()
    def steam_turbine_cost(b):
        return (
            m.fs.steam_turbine.costing.total_plant_cost["8.1"] +
            m.fs.steam_turbine.costing.total_plant_cost["8.2"] +
            m.fs.hrsg_condenser.costing.total_plant_cost["8.3"] +
            m.fs.feedwater_system.costing.total_plant_cost["8.4"] +
            m.fs.steam_turbine.costing.total_plant_cost["8.5"]
        )

    @m.fs.costing.Expression()
    def cooling_water_system_cost(b):
        return (
            m.fs.cooling_tower.costing.total_plant_cost["9.1"] +
            m.fs.cooling_water_system.costing.total_plant_cost["9.2"] +
            m.fs.cooling_water_system.costing.total_plant_cost["9.3"] +
            m.fs.cooling_water_system.costing.total_plant_cost["9.4"] +
            m.fs.makeup_water_system.costing.total_plant_cost["9.5"] +
            m.fs.cooling_water_system.costing.total_plant_cost["9.6"] +
            m.fs.cooling_water_system.costing.total_plant_cost["9.7"]
        )

    @m.fs.costing.Expression()
    def accessory_electric_plant_cost(b):
        return (
            m.fs.generator.costing.total_plant_cost["11.1"] +
            m.fs.accessory_electric_systems.costing.total_plant_cost["11.2"] +
            m.fs.accessory_electric_systems.costing.total_plant_cost["11.3"] +
            m.fs.accessory_electric_systems.costing.total_plant_cost["11.4"] +
            m.fs.accessory_electric_systems.costing.total_plant_cost["11.5"] +
            m.fs.accessory_electric_systems.costing.total_plant_cost["11.6"] +
            m.fs.generator.costing.total_plant_cost["11.7"] +
            m.fs.transformers.costing.total_plant_cost["11.8"] +
            m.fs.generator.costing.total_plant_cost["11.9"]
        )

    @m.fs.costing.Expression()
    def instrumentation_and_control_cost(b):
        return (
            m.fs.ic_systems.costing.total_plant_cost["12.3"] +
            m.fs.ic_systems.costing.total_plant_cost["12.5"] +
            m.fs.ic_systems.costing.total_plant_cost["12.6"] +
            m.fs.ic_systems.costing.total_plant_cost["12.7"] +
            m.fs.ic_systems.costing.total_plant_cost["12.8"] +
            m.fs.ic_systems.costing.total_plant_cost["12.9"]
        )

    @m.fs.costing.Expression()
    def improvements_to_site_cost(b):
        return (
            m.fs.improvements_and_buildings.costing.total_plant_cost["13.1"] +
            m.fs.improvements_and_buildings.costing.total_plant_cost["13.2"] +
            m.fs.improvements_and_buildings.costing.total_plant_cost["13.3"]
        )

    @m.fs.costing.Expression()
    def buildings_and_structures_cost(b):
        return (
            m.fs.steam_turbine.costing.total_plant_cost["14.3"] +
            m.fs.improvements_and_buildings.costing.total_plant_cost["14.4"] +
            m.fs.cooling_water_system.costing.total_plant_cost["14.5"] +
            m.fs.makeup_water_system.costing.total_plant_cost["14.6"] +
            m.fs.improvements_and_buildings.costing.total_plant_cost["14.7"] +
            m.fs.improvements_and_buildings.costing.total_plant_cost["14.8"] +
            m.fs.improvements_and_buildings.costing.total_plant_cost["14.9"] +
            m.fs.improvements_and_buildings.costing.total_plant_cost["14.10"]
        )


def initialize_capital_cost(m):
    variables = [
        m.fs.desulfurizer.costing.total_plant_cost,
        m.fs.anode_hx.costing.total_plant_cost,
        m.fs.sofc_modules.costing.total_plant_cost,
        m.fs.anode_blower.costing.total_plant_cost,
        m.fs.air_blower.costing.total_plant_cost,
        m.fs.cathode_hx.costing.total_plant_cost,
        m.fs.cathode_blower.costing.total_plant_cost,
        m.fs.asu.costing.total_plant_cost,
        m.fs.oxycombustor.costing.total_plant_cost,
        m.fs.cpu_cost.costing.total_plant_cost,
    ]

    constraints = [
        m.fs.desulfurizer.costing.desulfurizer_total_plant_cost,
        m.fs.anode_hx.costing.anode_hx_total_plant_cost,
        m.fs.sofc_modules.costing.sofc_module_total_plant_cost,
        m.fs.anode_blower.costing.anode_blower_total_plant_cost,
        m.fs.air_blower.costing.air_blower_total_plant_cost,
        m.fs.cathode_hx.costing.cathode_hx_total_plant_cost,
        m.fs.cathode_blower.costing.cathode_blower_total_plant_cost,
        m.fs.asu.costing.asu_total_plant_cost,
        m.fs.oxycombustor.costing.oxycombustor_total_plant_cost,
        m.fs.cpu_cost.costing.cpu_total_plant_cost,
    ]

    for v, c in zip(variables, constraints):
        for i in v.keys():
            calculate_variable_from_constraint(v[i], c[i])

    QGESSCostingData.costing_initialization(m.fs.costing)

    calculate_variable_from_constraint(
        m.fs.costing.total_TPC,
        m.fs.costing.total_TPC_eq
    )
    calculate_variable_from_constraint(
        m.fs.costing.total_overnight_cost,
        m.fs.costing.total_overnight_cost_eq
    )
    calculate_variable_from_constraint(
        m.fs.costing.total_as_spent_cost,
        m.fs.costing.total_as_spent_cost_eq
    )

    calculate_variable_from_constraint(
        m.fs.costing.annualized_tasc,
        m.fs.costing.annualized_tasc_eq
    )


def get_fixed_costs(m):
    m.fs.costing.get_fixed_OM_costs(
        net_power=None,
        nameplate_capacity=650,
        capacity_factor=0.85,
        labor_rate=38.50,
        labor_burden=30,
        operators_per_shift=6,
        tech=6,
        fixed_TPC=None,
        CE_index_year="2018",
    )

    m.fs.costing.stack_replacement_cost = pyo.Var(
        initialize=1,
        bounds=(0, 100),
        units=pyunits.USD_2018/pyunits.year
    )

    @m.fs.costing.Constraint()
    def stack_replacement_cost_eq(c):
        replacement_cost = 25.14*pyunits.USD_2018/pyunits.kW/pyunits.year
        return c.stack_replacement_cost == (
            1e-6*replacement_cost*m.fs.sofc_power_ac[0]
        )

    @m.fs.costing.Constraint()
    def other_fixed_costs_eq(c):
        return c.other_fixed_costs == (
            c.stack_replacement_cost + c.maintenance_material_cost
        )

    m.fs.costing.other_fixed_costs.unfix()

    initialize_fixed_costs(m)


def initialize_fixed_costs(m):
    calculate_variable_from_constraint(
        m.fs.costing.maintenance_material_cost,
        m.fs.costing.maintenance_material_cost_rule,
    )
    calculate_variable_from_constraint(
        m.fs.costing.stack_replacement_cost,
        m.fs.costing.stack_replacement_cost_eq,
    )
    calculate_variable_from_constraint(
        m.fs.costing.other_fixed_costs,
        m.fs.costing.other_fixed_costs_eq,
    )
    m.fs.costing.initialize_fixed_OM_costs()


def get_variable_costs(m):
    if not hasattr(m.fs, "costing"):
        m.fs.costing = QGESSCosting()

    consumables = [
        "natural gas",
        "water",
        "water treatment chemicals",
        "desulfur adsorbent",
        "prereformer catalyst"
    ]

    # Calculate consumable use rates
    @m.fs.Expression(m.fs.time)
    def natural_gas_energy_rate(fs, t):
        NG_HHV = 908839.23*pyunits.J/pyunits.mol
        return m.fs.anode_mix.feed_inlet.flow_mol[t]*NG_HHV

    @m.fs.Expression(m.fs.time)
    def waste_treatment_chem_rate(fs, t):
        use_rate = 0.00297886*pyunits.lb/pyunits.gal
        return fs.raw_water_withdrawal[t]*use_rate

    @m.fs.Expression(m.fs.time)
    def desulfur_adsorbent_rate(fs, t):
        NG_sulfur_ppm = 5/1e6
        sulfur_MW = 32*pyunits.g/pyunits.mol
        sulfur_capacity = 0.03
        return (m.fs.anode_mix.feed_inlet.flow_mol[t] *
                NG_sulfur_ppm * sulfur_MW / sulfur_capacity)

    @m.fs.Expression(m.fs.time)
    def prereformer_catalyst_rate(fs, t):
        syngas_flow = pyunits.convert(
            m.fs.anode_mix.feed_inlet_state[0].flow_mass, pyunits.lb/pyunits.hr)
        return (3.2*syngas_flow/611167 *
                pyunits.m**3/pyunits.day*pyunits.hr/pyunits.lb)

    rates = [
        m.fs.natural_gas_energy_rate,
        m.fs.raw_water_withdrawal,
        m.fs.waste_treatment_chem_rate,
        m.fs.desulfur_adsorbent_rate,
        m.fs.prereformer_catalyst_rate
    ]

    prices = {
        "natural gas": 4.42*pyunits.USD_2018/pyunits.MBtu,
        "water": 1.90e-3*pyunits.USD_2018/pyunits.gallon,
        "water treatment chemicals": 550*pyunits.USD_2018/pyunits.ton,
        "desulfur adsorbent": 6.0297*pyunits.USD_2018/pyunits.lb,
        "prereformer catalyst": 601.765*pyunits.USD_2018/pyunits.m**3
    }

    m.fs.costing.get_variable_OM_costs(
        resources=consumables,
        rates=rates,
        prices=prices,
        CE_index_year="2018",
        capacity_factor=0.85,
    )
    # since maintenance material cost is being included as a fixed cost it
    # needs to be subtracted from the variable costs
    if hasattr(m.fs.costing, "maintenance_material_cost"):
        @m.fs.costing.Constraint()
        def other_variable_costs_eq(c):
            return c.other_variable_costs[0] == -1*c.maintenance_material_cost

        m.fs.costing.other_variable_costs.unfix()

    initialize_variable_costs(m)


def initialize_variable_costs(m):
    if hasattr(m.fs.costing, "maintenance_material_cost"):
        calculate_variable_from_constraint(
            m.fs.costing.other_variable_costs[0],
            m.fs.costing.other_variable_costs_eq,
        )
    m.fs.costing.initialize_variable_OM_costs()


def add_capital_cost_tags(m):
    tag_group = iutil.ModelTagGroup()
    m._tags_capex = tag_group
    tag_group["desulfurizer_tpc"] = iutil.ModelTag(
        expr=m.fs.desulfurizer.costing.total_plant_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["anode_hx_tpc"] = iutil.ModelTag(
        expr=m.fs.anode_hx.costing.total_plant_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["sofc_tpc"] = iutil.ModelTag(
        expr=m.fs.sofc.costing.total_plant_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["anode_blower_tpc"] = iutil.ModelTag(
        expr=m.fs.anode_blower.costing.total_plant_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["air_blower_tpc"] = iutil.ModelTag(
        expr=m.fs.air_blower.costing.total_plant_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["cathode_hx_tpc"] = iutil.ModelTag(
        expr=m.fs.cathode_hx.costing.total_plant_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["cathode_blower_tpc"] = iutil.ModelTag(
        expr=m.fs.cathode_blower.costing.total_plant_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["asu_tpc"] = iutil.ModelTag(
        expr=m.fs.ASU.costing.total_plant_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["cpu_tpc"] = iutil.ModelTag(
        expr=m.fs.cpu.costing.total_plant_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["oxycombustor_tpc"] = iutil.ModelTag(
        expr=m.fs.oxycombustor.costing.total_plant_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["Feedwater & misc. BOP cost"] = iutil.ModelTag(
        expr=m.fs.costing.feedwater_and_miscellaneous_bop_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["HRSG, ductwork, and stack cost"] = iutil.ModelTag(
        expr=m.fs.costing.hrsg_ductwork_and_stack_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["Steam turbine cost"] = iutil.ModelTag(
        expr=m.fs.costing.steam_turbine_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["Cooling water system cost"] = iutil.ModelTag(
        expr=m.fs.costing.cooling_water_system_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["Accessory plant electric cost"] = iutil.ModelTag(
        expr=m.fs.costing.accessory_electric_plant_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["Instrumentation and control cost"] = iutil.ModelTag(
        expr=m.fs.costing.instrumentation_and_control_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["Improvements to site cost"] = iutil.ModelTag(
        expr=m.fs.costing.improvements_to_site_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )
    tag_group["Buildings and structures cost"] = iutil.ModelTag(
        expr=m.fs.costing.buildings_and_structures_cost*1e3,
        format_string="{:.0f}",
        display_units="$1000",
    )

    df = pd.DataFrame(columns=m._tags_capex.table_heading())
    df.loc[m._tags_capex["desulfurizer_tpc"].value] = m._tags_capex.table_row(numeric=True)
    df.to_csv("sofc_capex.csv")

