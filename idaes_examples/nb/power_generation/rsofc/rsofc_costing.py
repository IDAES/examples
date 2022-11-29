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
Costing methods for the soec and sofc operating modes of the reversible sofc

"""
__author__ = "Chinedu Okoli", "Alex Noring"

import pyomo.environ as pyo
from pyomo.util.calc_var_value import calculate_variable_from_constraint

from idaes.models_extra.power_generation.costing.power_plant_capcost import (
    QGESSCosting,
    QGESSCostingData,
)
from idaes.models.costing.SSLW import(
    SSLWCosting,
    SSLWCostingData,
    HXType)
from idaes.core import FlowsheetBlock, UnitModelBlock, UnitModelCostingBlock


def add_total_plant_cost(b, installation_labor=1.25, eng_fee=1.2,
                         project_contingency=1.15, process_contingency=1.15,
                         CE_index_units=pyo.units.MUSD_2018):

    @b.costing.Expression()
    def total_plant_cost(c):
        return (pyo.units.convert(c.capital_cost, CE_index_units) *
                installation_labor * eng_fee *
                (project_contingency + process_contingency))


def get_rsofc_sofc_capital_cost(fs, CE_index_year):

    # TPC of 650 MW NG based sofc plant
    # SOEC-only cap costs for water-side equipment and H2 compr. will be added
    # NGFC_TPC = 752.55  # MM$

    CE_index_units = getattr(pyo.units, "MUSD_"+CE_index_year)  # millions of USD in base year

    fs.NGFC_TPC = pyo.Var(initialize=752.55, units=CE_index_units,
                            doc="total plant cost in $MM")

    # build cost constraints
    fs.costing.build_process_costs(
        total_plant_cost=fs.NGFC_TPC,
        net_power=None,
        fixed_OM=False,
        variable_OM=False,
        resources=None,
        rates=None,
        prices=None,
        fuel="natural_gas",
        CE_index_year=CE_index_year,
    )

    # costing initialization
    QGESSCostingData.costing_initialization(fs.costing)

    calculate_variable_from_constraint(
        fs.costing.total_TPC,
        fs.costing.total_TPC_eq)


def get_rsofc_soec_capital_cost(fs, CE_index_year):

    # TPC of 650 MW NG based sofc plant
    # SOEC-only cap costs for water-side equipment and H2 compr. will be added
    # For rsofc_soec mode - O2 and ng preheater costs are captured in NGFC_TPC
    # Water treatment and CO2 processing capcosts included in NGFC_TPC

    CE_index_units = getattr(pyo.units, "MUSD_"+CE_index_year)  # millions of USD in base year

    # U-tube HXs - bhx1, oxygen_preheater, and ng_preheater
    # costed with IDAES generic heat exchanger correlation
    for hx in [fs.bhx1, fs.bhx2, fs.oxygen_preheater, fs.ng_preheater]:
        hx.costing = UnitModelCostingBlock(
            flowsheet_costing_block=fs.costing,
            costing_method=SSLWCostingData.cost_heat_exchanger,
            costing_method_arguments={
                "hx_type": HXType.Utube,
            },
        )
        add_total_plant_cost(hx)

    # changing this to electric heater costing
    fs.fuel_recycle_heater.costing = UnitModelCostingBlock(
        flowsheet_costing_block=fs.costing,
        costing_method=SSLWCostingData.cost_fired_heater,
        costing_method_arguments={
            "integer",
        },
    )

    @fs.fuel_recycle_heater.costing.Expression()
    def total_plant_cost(b):
        U = 100 * pyo.units.W / pyo.units.m ** 2 / pyo.units.K
        DT = 50 * pyo.units.K
        area = fs.fuel_recycle_heater.heat_duty[0] / U / DT
        # Add factor of two to pathways cost to account for corrosion-resistant materials for trim heaters
        return pyo.units.convert(
            2*81.88 * pyo.value(
                pyo.units.convert(area, pyo.units.ft**2)
                ) *
            pyo.units.USD_2018,
            CE_index_units)

    # adding cost for air_preheater_2
    fs.air_preheater_2.costing = UnitModelCostingBlock(
        flowsheet_costing_block=fs.costing,
        costing_method=SSLWCostingData.cost_fired_heater,
        costing_method_arguments={
            "integer",
        },
    )

    @fs.air_preheater_2.costing.Expression()
    def total_plant_cost(b):
        return pyo.units.convert(
            2*81.88 * pyo.value(
                pyo.units.convert(fs.air_preheater_2.area, pyo.units.ft**2)
                ) *
            pyo.units.USD_2018,
            CE_index_units)

    # H2 compressor
    fs.hcmp01.costing = UnitModelCostingBlock(
        flowsheet_costing_block=fs.costing,
        costing_method=SSLWCostingData.cost_compressor,
        costing_method_arguments={
            "integer": True,
        },
    )

    h2_comp_process_param = pyo.units.convert(
        fs.hcmp01.control_volume.properties_out[0].flow_mass,
        pyo.units.lb / pyo.units.hr,
    )

    @fs.hcmp01.costing.Constraint()
    def total_plant_cost(c):
        # This is for 4 stages.  The original was for 2 hence the multiplication by 2
        ref_cost = 11.408  # MM$ 2018
        ref_param = 44369 * pyo.units.lb / pyo.units.hr
        alpha = 0.7
        return pyo.units.convert(
            2 * ref_cost * (h2_comp_process_param / ref_param) ** alpha,
            CE_index_units
        )

    # build cost constraints
    fs.costing.build_process_costs(
        net_power=None,
        fixed_OM=False,
        variable_OM=False,
        resources=None,
        rates=None,
        prices=None,
        fuel="natural_gas",
        CE_index_year=CE_index_year,
    )

    # costing initialization
    QGESSCostingData.costing_initialization(fs.costing)

    calculate_variable_from_constraint(
        fs.costing.total_TPC,
        fs.costing.total_TPC_eq)


def lock_rsofc_soec_capital_cost(fs):
    for b in fs.generic_costing_units + fs.custom_costing_units:
        for v in b.costing.total_plant_cost.values():
            print("TPC of generic units")
            print(b)
            v.display()
            v.set_value(pyo.value(v))
        b.costing.deactivate()
    fs.costing.deactivate()
    fs.costing.total_TPC.fix()


def lock_rsofc_sofc_capital_cost(fs):
    fs.costing.deactivate()
    fs.costing.total_TPC.fix()


def get_rsofc_sofc_fixed_OM_costing(
    fs, design_rsofc_netpower=650 * pyo.units.MW, fixed_TPC=None,
    CE_index_year="2018",
):

    # Deleting this Var/Constraint pair so non-zero TPC value is used
    fs.costing.del_component(fs.costing.total_TPC)
    fs.costing.del_component(fs.costing.total_TPC_eq)

    # fixed O&M costs

    CE_index_units = getattr(pyo.units, "MUSD_"+CE_index_year)  # millions of USD in base year

    fs.fixed_TPC = pyo.Var(initialize=fixed_TPC, units=CE_index_units,
                             doc="total plant cost in $MM")
    fs.net_power = pyo.Var(initialize=design_rsofc_netpower,
                             units=pyo.units.MW)
    # build cost constraints
    fs.costing.build_process_costs(
        total_plant_cost=fs.fixed_TPC,
        net_power=fs.net_power,
        labor_rate=38.50,
        labor_burden=30,
        operators_per_shift=6,
        tech=6,
        fixed_OM=True,
        variable_OM=False,
        resources=None,
        rates=None,
        prices=None,
        fuel="natural_gas",
        CE_index_year=CE_index_year,
    )

    @fs.costing.Constraint()
    def stack_replacement_cost(costing):
        # stack replacement cost
        stack_replacement_cost = 13.26  # $MM/yr
        return costing.other_fixed_costs == stack_replacement_cost

    fs.costing.other_fixed_costs.unfix()

    # initialize fixed costs
    calculate_variable_from_constraint(
        fs.costing.other_fixed_costs, fs.costing.stack_replacement_cost
    )
    QGESSCostingData.initialize_fixed_OM_costs(fs.costing)


def get_rsofc_soec_fixed_OM_costing(
    fs, design_rsofc_netpower=650 * pyo.units.MW, fixed_TPC=None,
    CE_index_year="2018",
):
    # fixed O&M costs

    CE_index_units = getattr(pyo.units, "MUSD_"+CE_index_year)  # millions of USD in base year

    fs.fixed_TPC = pyo.Var(initialize=fixed_TPC, units=CE_index_units,
                             doc="total plant cost in $MM")
    fs.net_power = pyo.Var(initialize=design_rsofc_netpower,
                             units=pyo.units.MW)
    # build cost constraints
    fs.costing.build_process_costs(
        total_plant_cost=fs.fixed_TPC,
        net_power=fs.net_power,
        labor_rate=38.50,
        labor_burden=30,
        operators_per_shift=6,
        tech=6,
        fixed_OM=True,
        variable_OM=False,
        resources=None,
        rates=None,
        prices=None,
        fuel="natural_gas",
        CE_index_year=CE_index_year,
    )

    QGESSCostingData.initialize_fixed_OM_costs(fs.costing)


def get_rsofc_soec_variable_OM_costing(fs, CE_index_year="2018"):
    # variable O&M costs
    # electricity
    @fs.Expression(fs.time)
    def plant_load(fs, t):
        return fs.net_power[t]  # net power

    # natural gas
    @fs.Expression(fs.time)
    def NG_energy_rate(fs, t):
        NG_HHV = 908839.23 * pyo.units.J / pyo.units.mol
        return fs.ng_preheater.tube_inlet.flow_mol[t] * NG_HHV

    # water
    @fs.Expression(fs.time)
    def water_withdrawal(fs, t):  # cm^3/s
        molar_mass = 18.015 * pyo.units.g / pyo.units.mol
        density = 0.997 * pyo.units.g / pyo.units.cm ** 3
        return (
            molar_mass
            / density
            * (
                fs.aux_boiler_feed_pump.inlet.flow_mol[t]
                - fs.bhx1.shell_outlet.flow_mol[t]
                * fs.bhx1.shell_outlet.mole_frac_comp[t, "H2O"]
            )
        )

    # water treatment
    @fs.Expression(fs.time)
    def water_treatment_use(fs, t):
        use_rate = 0.00297886 * pyo.units.lb / pyo.units.gal
        return fs.water_withdrawal[t] * use_rate

    resources = ["electricity", "natural_gas", "water", "water_treatment_chemicals"]
    rates = [
        fs.plant_load,
        fs.NG_energy_rate,
        fs.water_withdrawal,
        fs.water_treatment_use,
    ]
    prices = {"electricity": 30 * pyo.units.USD_2018 / pyo.units.MWh}

    print(pyo.units.convert(fs.h2_product_rate_mass[0], pyo.units.g / pyo.units.s))
    fs.h2_product_rate_mass.display()
    # build cost constraints
    fs.costing.get_variable_OM_costs(
        resources=resources,
        rates=rates,
        prices=prices,
        CE_index_year=CE_index_year,
    )

    # initialize variable costs
    QGESSCostingData.initialize_variable_OM_costs(fs.costing)


def get_rsofc_sofc_variable_OM_costing(fs, CE_index_year="2018"):
    # variable O&M costs
    # Natural Gas Fuel
    NG_HHV = 908839.23 * pyo.units.J / pyo.units.mol

    @fs.Expression(fs.time)
    def NG_energy_rate(fs, t):
        return fs.anode_mix.feed_inlet.flow_mol[t] * NG_HHV

    # Water
    fs.condensate_flowrate = pyo.Var(
        fs.time, initialize=1e-3, units=pyo.units.lb / pyo.units.s
    )

    # scaled based on BB Case 31A steam turbine power
    @fs.Constraint(fs.time)
    def condensate_flowrate_constraint(fs, t):
        ref_flowrate = 388.586 * pyo.units.lb / pyo.units.s
        ref_power = 262.8 * pyo.units.MW
        return (
            fs.condensate_flowrate[t]
            == ref_flowrate * fs.steam_cycle_power[t] / ref_power
        )

    fs.BFW_circulation_rate = pyo.Var(
        fs.time, initialize=1e-3, units=pyo.units.lb / pyo.units.s
    )

    @fs.Constraint(fs.time)
    def BFW_circulation_rate_constraint(fs, t):
        return fs.BFW_circulation_rate[t] == fs.condensate_flowrate[t]

    fs.BFW_makeup_flow = pyo.Var(
        fs.time, initialize=1e-3, units=pyo.units.lb / pyo.units.s
    )

    @fs.Constraint(fs.time)
    def BFW_makeup_flow_constraint(fs, t):
        return fs.BFW_makeup_flow[t] == 0.01 * fs.BFW_circulation_rate[t]

    fs.evaporation_losses = pyo.Var(
        fs.time, initialize=1e-3, units=pyo.units.lb / pyo.units.s
    )

    @fs.Constraint(fs.time)
    def evaporation_losses_constraint(fs, t):
        return fs.evaporation_losses[t] == 0.016 * fs.cooling_water_flowrate[t]

    fs.blowdown_losses = pyo.Var(
        fs.time, initialize=1e-3, units=pyo.units.lb / pyo.units.s
    )

    @fs.Constraint(fs.time)
    def blowdown_losses_constraint(fs, t):
        cycles_of_concentration = 4
        return fs.blowdown_losses[t] == fs.evaporation_losses[t] / (
            cycles_of_concentration - 1
        )

    fs.total_wet_losses = pyo.Var(
        fs.time, initialize=1e-3, units=pyo.units.lb / pyo.units.s
    )

    @fs.Constraint(fs.time)
    def wet_losses_constraint(fs, t):
        return fs.total_wet_losses[t] == (
            fs.evaporation_losses[t] + fs.blowdown_losses[t]
        )

    fs.water_demand = pyo.Var(
        fs.time, initialize=1e-3, units=pyo.units.lb / pyo.units.s
    )

    @fs.Constraint(fs.time)
    def water_demand_constraint(fs, t):
        return fs.water_demand[t] == (fs.BFW_makeup_flow[t] + fs.total_wet_losses[t])

    fs.water_recycle = pyo.Var(
        fs.time, initialize=1e-3, units=pyo.units.lb / pyo.units.s
    )

    @fs.Constraint(fs.time)
    def water_recycle_constraint(fs, t):
        molar_mass = 18 * pyo.units.g / pyo.units.mol
        CPU_water = pyo.units.convert(
            fs.CPU.water.flow_mol[t] * molar_mass, pyo.units.lb / pyo.units.s
        )
        flash_water = pyo.units.convert(
            fs.flash.liq_outlet.flow_mol[t] * molar_mass, pyo.units.lb / pyo.units.s
        )
        return fs.water_recycle[t] == CPU_water + flash_water

    fs.raw_water_withdrawal = pyo.Var(
        fs.time, initialize=1e-3, units=pyo.units.lb / pyo.units.s
    )

    @fs.Constraint(fs.time)
    def raw_water_withdrawal_constraint(fs, t):
        return fs.raw_water_withdrawal[t] == (fs.water_demand[t] - fs.water_recycle[t])

    fs.process_water_discharge = pyo.Var(
        fs.time, initialize=9, units=pyo.units.lb / pyo.units.s
    )

    @fs.Constraint(fs.time)
    def water_discharge_constraint(fs, t):
        return fs.process_water_discharge[t] == 0.9 * fs.blowdown_losses[t]

    fs.raw_water_consumption = pyo.Var(
        fs.time, initialize=1e-3, units=pyo.units.lb / pyo.units.s
    )

    @fs.Constraint(fs.time)
    def raw_water_consumption_constraint(fs, t):
        return fs.raw_water_consumption[t] == (
            fs.raw_water_withdrawal[t] - fs.process_water_discharge[t]
        )

    # MU & WT Chem
    @fs.Expression(fs.time)
    def waste_treatment_use(fs, t):
        use_rate = 0.00297886 * pyo.units.lb / pyo.units.gal
        density = 8.34 * pyo.units.lb / pyo.units.gal
        return fs.water_demand[t] / density * use_rate

    # NG desulfur TDA Adsorbent
    @fs.Expression(fs.time)
    def desulfur_adsorbent_use(fs, t):
        NG_sulfur_ppm = 5 / 1e6
        sulfur_MW = 32 * pyo.units.g / pyo.units.mol
        sulfur_capacity = 0.03
        return (
            fs.anode_mix.feed_inlet.flow_mol[t]
            * NG_sulfur_ppm
            * sulfur_MW
            / sulfur_capacity
        )

    # Methanation Catalyst
    @fs.Expression(fs.time)
    def methanation_catalyst_use(fs, t):
        syngas_flow = pyo.units.convert(
            fs.anode_mix.feed_inlet_state[0].flow_mass, pyo.units.lb / pyo.units.hr
        )
        return (
            3.2
            * syngas_flow
            / 611167
            * pyo.units.m ** 3
            / pyo.units.day
            * pyo.units.hr
            / pyo.units.lb
        )

    resources = [
        "natural gas",
        "water treatment chemicals",
        "desulfur adsorbent",
        "methanation catalyst",
    ]

    rates = [
        fs.NG_energy_rate,
        fs.waste_treatment_use,
        fs.desulfur_adsorbent_use,
        fs.methanation_catalyst_use,
    ]

    prices = {
        "desulfur adsorbent": 6.0297 * pyo.units.USD_2018 / pyo.units.lb,
        "methanation catalyst": 601.765 * pyo.units.USD_2018 / pyo.units.m ** 3,
    }

    fs.costing.get_variable_OM_costs(fs, fs.net_power, resources, rates, prices,
                                       CE_index_year=CE_index_year)

    # initialize variable costs
    QGESSCostingData.initialize_variable_OM_costs(fs.costing)


def display_rsofc_costing(fs):
    print("Capital cost: ${:.0f}M".format(pyo.value(fs.costing.total_TPC)))
    print(
        "Fixed O&M cost: ${:.1f}M/yr".format(
            pyo.value(fs.costing.total_fixed_OM_cost)
        )
    )
    print(
        "Electricity cost: ${:.2f}/kg H2".format(
            pyo.value(fs.costing.variable_operating_costs[0, "electricity"]
                      * fs.net_power[0] / fs.h2_product_rate_mass[0])
        )
    )
    print(
        "Fuel cost: ${:.2f}/kg H2".format(
            pyo.value(fs.costing.variable_operating_costs[0, "natural_gas"]
                      * fs.net_power[0] / fs.h2_product_rate_mass[0])
        )
    )
    print(
        "Total variable O&M cost: ${:.2f}/kg H2".format(
            pyo.value(fs.costing.total_variable_OM_cost[0]
                      * fs.net_power[0] / fs.h2_product_rate_mass[0])
        )
    )
