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
# Utility functions for the CO2 Adsorption Desorption cycle with NETL_32D sorbent example

# Author: Chinedu Okoli

# Last modified by Author: 10/13/2022
# Last modified by Editor (Brandon Paul): 1/4/2023


# Import Python libraries
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# Import pyomo methods
from pyomo.environ import value
from pyomo.dae import ContinuousSet, Integral


def heat_computation(
    m, tj_ads, tj_des, adsorption_temperature, desorption_temperature
):
    """
    These functions calculate heat transfer behavior across the temporal and
    spatial domains for the adsorption, desorption, preheating, and precooling
    stages.
    """
    ###########################################################################
    #  Cooling duty required during adsorption
    ###########################################################################
    solid_phase = m.fs_ads.FB.config.solid_phase_config
    m.fs_ads.FB.time_set = ContinuousSet(
        initialize=tj_ads.time,
        doc="time domain",
    )
    time_elements_ads = m.fs_ads.FB.time_set.get_finite_elements()
    tf_ads = m.fs_ads.FB.time_set.last()

    flow_mol_ads = {}
    temperature_solid_ads = {}
    temperature_gas_ads = {}
    reaction_rate_ads = {}

    for t in time_elements_ads:
        for x in m.fs_ads.FB.length_domain:
            flow_mol_ads[t, x] = tj_ads.get_vec(
                m.fs_ads.FB.gas_phase.properties[tf_ads, x].flow_mol
            )[time_elements_ads.index(t)]
            temperature_solid_ads[t, x] = tj_ads.get_vec(
                m.fs_ads.FB.solid_properties[tf_ads, x].temperature
            )[time_elements_ads.index(t)]
            temperature_gas_ads[t, x] = tj_ads.get_vec(
                m.fs_ads.FB.gas_phase.properties[tf_ads, x].temperature
            )[time_elements_ads.index(t)]

            for r in solid_phase.reaction_package.rate_reaction_idx:
                reaction_rate_ads[t, x, r] = tj_ads.get_vec(
                    m.fs_ads.FB.solid_reactions[tf_ads, x].reaction_rate[r]
                )[time_elements_ads.index(t)]

    def q_adsorb_per_time(b, t, x):
        heat_ads = b.solid_phase_area[0, 0] * sum(
            reaction_rate_ads[t, x, r] * b.solid_reactions[0, 0]._params.dh_rxn[r]
            for r in solid_phase.reaction_package.rate_reaction_idx
        )
        Q = heat_ads
        return Q

    m.fs_ads.FB.q_adsorb_per_time = Integral(
        m.fs_ads.FB.time_set,
        m.fs_ads.FB.length_domain,
        wrt=m.fs_ads.FB.length_domain,
        rule=q_adsorb_per_time,
        doc="Adsorption cooling duty per time, J/s",
    )

    def q_adsorb_total(b, t):
        return b.q_adsorb_per_time[t]

    m.fs_ads.FB.q_adsorb_total = Integral(
        m.fs_ads.FB.time_set,
        wrt=m.fs_ads.FB.time_set,
        rule=q_adsorb_total,
        doc="Total adsorption cooling duty, J",
    )

    ###########################################################################
    #  Heating duty required during desorption
    ###########################################################################
    solid_phase = m.fs_des.FB.config.solid_phase_config
    m.fs_des.FB.time_set = ContinuousSet(
        initialize=tj_des.time,
        doc="time domain",
    )
    time_elements_des = m.fs_des.FB.time_set.get_finite_elements()
    tf_des = m.fs_des.FB.time_set.last()

    flow_mol_des = {}
    temperature_solid_des = {}
    temperature_gas_des = {}
    reaction_rate_des = {}
    for t in time_elements_des:
        for x in m.fs_des.FB.length_domain:
            flow_mol_des[t, x] = tj_des.get_vec(
                m.fs_des.FB.gas_phase.properties[tf_des, x].flow_mol
            )[time_elements_des.index(t)]
            temperature_solid_des[t, x] = tj_des.get_vec(
                m.fs_des.FB.solid_properties[tf_des, x].temperature
            )[time_elements_des.index(t)]
            temperature_gas_des[t, x] = tj_des.get_vec(
                m.fs_des.FB.gas_phase.properties[tf_des, x].temperature
            )[time_elements_des.index(t)]

            for r in solid_phase.reaction_package.rate_reaction_idx:
                reaction_rate_des[t, x, r] = tj_des.get_vec(
                    m.fs_des.FB.solid_reactions[tf_des, x].reaction_rate[r]
                )[time_elements_des.index(t)]

    def q_desorb_per_time(b, t, x):
        heat_des = b.solid_phase_area[0, 0] * sum(
            reaction_rate_des[t, x, r] * b.solid_reactions[0, 0]._params.dh_rxn[r]
            for r in solid_phase.reaction_package.rate_reaction_idx
        )
        Q = heat_des

        return Q

    m.fs_des.FB.q_desorb_per_time = Integral(
        m.fs_des.FB.time_set,
        m.fs_des.FB.length_domain,
        wrt=m.fs_des.FB.length_domain,
        rule=q_desorb_per_time,
        doc="Desorption heating duty per time, J/s",
    )

    def q_desorb_total(b, t):
        return b.q_desorb_per_time[t]

    m.fs_des.FB.q_desorb_total = Integral(
        m.fs_des.FB.time_set,
        wrt=m.fs_des.FB.time_set,
        rule=q_desorb_total,
        doc="Total desorption heating duty, J",
    )

    ###########################################################################
    #  Precooling duty
    ###########################################################################
    @m.fs_ads.Expression(doc="Pre-cooling duty, J")
    def q_precooling(fs):
        return (
            fs.FB.solid_properties[0, 0].dens_mass_particle
            * fs.FB.solid_phase_area[0, 0]
            * fs.FB.bed_height
            * fs.FB.solid_properties[0, 0].cp_mass
            * (adsorption_temperature - desorption_temperature)
        )

    ###########################################################################
    #  Preheating duty
    ###########################################################################
    @m.fs_des.Expression(doc="Pre-heating duty, J")
    def q_preheating(fs):
        return (
            fs.FB.solid_properties[0, 0].dens_mass_particle
            * fs.FB.solid_phase_area[0, 0]
            * fs.FB.bed_height
            * fs.FB.solid_properties[0, 0].cp_mass
            * (adsorption_temperature - desorption_temperature)
        )


def performance_results(m, tj_ads, tj_des):
    """
    These functions calculate adsorption and desorption performance in the beds
    by determining a number of quantities including component concentrations
    in the solid and gas phases, thermal energy results and productivity in
    terms of the adsorbed/desorbed components.
    """
    # Create dictionaries of relevant trajectory data for performance calculations
    time_elements_ads = tj_ads.time  # m.fs_ads.FB.time_set.get_finite_elements()
    time_elements_des = tj_des.time  # m.fs_des.FB.time_set.get_finite_elements()
    t0_ads = time_elements_ads[0]  # m.fs_ads.FB.time_set.first()
    tf_ads = time_elements_ads[-1]  # m.fs_ads.FB.time_set.last()
    tf_des = time_elements_des[-1]  # m.fs_des.FB.time_set.last()

    gas_outlet_flow_mol_ads = {}
    gas_inlet_flow_mol_ads = {}
    gas_outlet_mole_frac_CO2_ads = {}
    gas_inlet_mole_frac_CO2_ads = {}

    gas_outlet_flow_mol_des = {}
    gas_inlet_flow_mol_des = {}
    gas_outlet_mole_frac_CO2_des = {}
    gas_inlet_mole_frac_CO2_des = {}

    for t in time_elements_ads:
        gas_outlet_flow_mol_ads[t] = tj_ads.get_vec(
            m.fs_ads.FB.gas_outlet.flow_mol[tf_ads]
        )[time_elements_ads.index(t)]
        gas_inlet_flow_mol_ads[t] = tj_ads.get_vec(
            m.fs_ads.FB.gas_inlet.flow_mol[tf_ads]
        )[time_elements_ads.index(t)]
        gas_outlet_mole_frac_CO2_ads[t] = tj_ads.get_vec(
            m.fs_ads.FB.gas_outlet.mole_frac_comp[tf_ads, "CO2"]
        )[time_elements_ads.index(t)]
        gas_inlet_mole_frac_CO2_ads[t] = tj_ads.get_vec(
            m.fs_ads.FB.gas_inlet.mole_frac_comp[tf_ads, "CO2"]
        )[time_elements_ads.index(t)]

    for t in time_elements_des:
        gas_outlet_flow_mol_des[t] = tj_des.get_vec(
            m.fs_des.FB.gas_outlet.flow_mol[tf_des]
        )[time_elements_des.index(t)]
        gas_inlet_flow_mol_des[t] = tj_des.get_vec(
            m.fs_des.FB.gas_inlet.flow_mol[tf_des]
        )[time_elements_des.index(t)]
        gas_outlet_mole_frac_CO2_des[t] = tj_des.get_vec(
            m.fs_des.FB.gas_outlet.mole_frac_comp[tf_des, "CO2"]
        )[time_elements_des.index(t)]
        gas_inlet_mole_frac_CO2_des[t] = tj_des.get_vec(
            m.fs_des.FB.gas_inlet.mole_frac_comp[tf_des, "CO2"]
        )[time_elements_des.index(t)]

    specie_concentration_Car_ads = {}
    specie_concentration_Car_des = {}
    specie_concentration_H2O_ads = {}
    specie_concentration_H2O_des = {}
    solid_density_ads = {}
    solid_density_des = {}
    mass_fraction_Car_ads = {}
    mass_fraction_Car_des = {}
    mass_fraction_H2O_ads = {}
    mass_fraction_H2O_des = {}

    for t in time_elements_ads:
        for x in m.fs_ads.FB.length_domain:
            specie_concentration_Car_ads[t, x] = tj_ads.get_vec(
                m.fs_ads.FB.solid_reactions[tf_ads, x].specie_concentration["Car"]
            )[time_elements_ads.index(t)]
            solid_density_ads[t, x] = tj_ads.get_vec(
                m.fs_ads.FB.solid_properties[tf_ads, x].dens_mass_particle
            )[time_elements_ads.index(t)]
            mass_fraction_Car_ads[t, x] = tj_ads.get_vec(
                m.fs_ads.FB.solid_properties[tf_ads, x].mass_frac_comp["Car"]
            )[time_elements_ads.index(t)]
            specie_concentration_H2O_ads[t, x] = tj_ads.get_vec(
                m.fs_ads.FB.solid_reactions[tf_ads, x].specie_concentration["H2O_s"]
            )[time_elements_ads.index(t)]
            mass_fraction_H2O_ads[t, x] = tj_ads.get_vec(
                m.fs_ads.FB.solid_properties[tf_ads, x].mass_frac_comp["H2O_s"]
            )[time_elements_ads.index(t)]

    for t in time_elements_des:
        for x in m.fs_des.FB.length_domain:
            specie_concentration_Car_des[t, x] = tj_des.get_vec(
                m.fs_des.FB.solid_reactions[tf_des, x].specie_concentration["Car"]
            )[time_elements_des.index(t)]
            solid_density_des[t, x] = tj_des.get_vec(
                m.fs_des.FB.solid_properties[tf_des, x].dens_mass_particle
            )[time_elements_des.index(t)]
            mass_fraction_Car_des[t, x] = tj_des.get_vec(
                m.fs_des.FB.solid_properties[tf_des, x].mass_frac_comp["Car"]
            )[time_elements_des.index(t)]
            specie_concentration_H2O_des[t, x] = tj_des.get_vec(
                m.fs_des.FB.solid_reactions[tf_des, x].specie_concentration["H2O_s"]
            )[time_elements_des.index(t)]
            mass_fraction_H2O_des[t, x] = tj_des.get_vec(
                m.fs_des.FB.solid_properties[tf_des, x].mass_frac_comp["H2O_s"]
            )[time_elements_des.index(t)]

    ###########################################################################
    #  CO2 captured in one cycle per bed
    ###########################################################################
    def carbamate_at_initial_adsorption_time(b, x):
        mole_adsorbed = (
            specie_concentration_Car_ads[t0_ads, x]
            * b.solid_phase_area[t0_ads, x]
            * b.solid_properties[t0_ads, x]._params.dens_mass_particle_param
        )
        return mole_adsorbed

    m.fs_ads.FB.carbamate_at_initial_adsorption_time = Integral(
        m.fs_ads.FB.length_domain,
        wrt=m.fs_ads.FB.length_domain,
        rule=carbamate_at_initial_adsorption_time,
        doc="Carbamate amount at initial adsorption time, mole",
    )

    def carbamate_at_final_adsorption_time(b, x):
        mole_adsorbed = (
            specie_concentration_Car_ads[tf_ads, x]
            * b.solid_phase_area[tf_ads, x]
            * b.solid_properties[tf_ads, x]._params.dens_mass_particle_param
        )
        return mole_adsorbed

    m.fs_ads.FB.carbamate_at_final_adsorption_time = Integral(
        m.fs_ads.FB.length_domain,
        wrt=m.fs_ads.FB.length_domain,
        rule=carbamate_at_final_adsorption_time,
        doc="Carbamate amount at final adsorption time, mole",
    )

    def carbamate_at_final_adsorption_time_kg(b, x):
        kg_adsorbed = (
            mass_fraction_Car_ads[tf_ads, x]
            * solid_density_ads[tf_ads, x]
            * b.solid_phase_area[tf_ads, x]
        )
        return kg_adsorbed

    m.fs_ads.FB.carbamate_at_final_adsorption_time_kg = Integral(
        m.fs_ads.FB.length_domain,
        wrt=m.fs_ads.FB.length_domain,
        rule=carbamate_at_final_adsorption_time_kg,
        doc="Carbamate amount at final adsorption time, kg",
    )

    def carbamate_at_initial_desorption_time(b, x):
        mole_desorbed = (
            specie_concentration_Car_des[0, x]
            * b.solid_phase_area[0, x]
            * b.solid_properties[0, x]._params.dens_mass_particle_param
        )
        return mole_desorbed

    m.fs_des.FB.carbamate_at_initial_desorption_time = Integral(
        m.fs_des.FB.length_domain,
        wrt=m.fs_des.FB.length_domain,
        rule=carbamate_at_initial_desorption_time,
        doc="Carbamate amount at initial desorption time, mole",
    )

    def carbamate_at_final_desorption_time(b, x):
        mole_desorbed = (
            specie_concentration_Car_des[tf_des, x]
            * b.solid_phase_area[tf_des, x]
            * b.solid_properties[tf_des, x]._params.dens_mass_particle_param
        )
        return mole_desorbed

    m.fs_des.FB.carbamate_at_final_desorption_time = Integral(
        m.fs_des.FB.length_domain,
        wrt=m.fs_des.FB.length_domain,
        rule=carbamate_at_final_desorption_time,
        doc="Carbamate amount at final desorption time, mole",
    )

    ###########################################################################
    #  H2O captured in one cycle per bed
    ###########################################################################
    def H2O_at_initial_adsorption_time(b, x):
        mole_adsorbed = (
            specie_concentration_H2O_ads[t0_ads, x]
            * b.solid_phase_area[t0_ads, x]
            * b.solid_properties[t0_ads, x]._params.dens_mass_particle_param
        )
        return mole_adsorbed

    m.fs_ads.FB.H2O_at_initial_adsorption_time = Integral(
        m.fs_ads.FB.length_domain,
        wrt=m.fs_ads.FB.length_domain,
        rule=H2O_at_initial_adsorption_time,
        doc="H2O amount at initial adsorption time, mole",
    )

    def H2O_at_final_adsorption_time(b, x):
        mole_adsorbed = (
            specie_concentration_H2O_ads[tf_ads, x]
            * b.solid_phase_area[tf_ads, x]
            * b.solid_properties[tf_ads, x]._params.dens_mass_particle_param
        )
        return mole_adsorbed

    m.fs_ads.FB.H2O_at_final_adsorption_time = Integral(
        m.fs_ads.FB.length_domain,
        wrt=m.fs_ads.FB.length_domain,
        rule=H2O_at_final_adsorption_time,
        doc="H2O amount at final adsorption time, mole",
    )

    def H2O_at_final_adsorption_time_kg(b, x):
        kg_adsorbed = (
            mass_fraction_H2O_ads[tf_ads, x]
            * solid_density_ads[tf_ads, x]
            * b.solid_phase_area[tf_ads, x]
        )
        return kg_adsorbed

    m.fs_ads.FB.H2O_at_final_adsorption_time_kg = Integral(
        m.fs_ads.FB.length_domain,
        wrt=m.fs_ads.FB.length_domain,
        rule=H2O_at_final_adsorption_time_kg,
        doc="H2O amount at final adsorption time, kg",
    )

    def H2O_at_initial_desorption_time(b, x):
        mole_desorbed = (
            specie_concentration_H2O_des[0, x]
            * b.solid_phase_area[0, x]
            * b.solid_properties[0, x]._params.dens_mass_particle_param
        )
        return mole_desorbed

    m.fs_des.FB.H2O_at_initial_desorption_time = Integral(
        m.fs_des.FB.length_domain,
        wrt=m.fs_des.FB.length_domain,
        rule=H2O_at_initial_desorption_time,
        doc="H2O amount at initial desorption time, mole",
    )

    def H2O_at_final_desorption_time(b, x):
        mole_desorbed = (
            specie_concentration_H2O_des[tf_des, x]
            * b.solid_phase_area[tf_des, x]
            * b.solid_properties[tf_des, x]._params.dens_mass_particle_param
        )
        return mole_desorbed

    m.fs_des.FB.H2O_at_final_desorption_time = Integral(
        m.fs_des.FB.length_domain,
        wrt=m.fs_des.FB.length_domain,
        rule=H2O_at_final_desorption_time,
        doc="H2O amount at final desorption time, mole",
    )

    ###########################################################################
    #  Performance calculations
    ###########################################################################
    @m.Expression(doc="CO2 recovery, [-]")
    def co2_recovery_per_cycle(m):
        return (
            m.fs_des.FB.carbamate_at_initial_desorption_time
            - m.fs_des.FB.carbamate_at_final_desorption_time
        ) / (
            m.fs_ads.FB.carbamate_at_final_adsorption_time
            - m.fs_ads.FB.carbamate_at_initial_adsorption_time
        )

    def co2_gas_mol_desorbed_per_cycle(b, t):
        return (
            gas_outlet_flow_mol_des[t] * gas_outlet_mole_frac_CO2_des[t]
            - gas_inlet_flow_mol_des[t] * gas_inlet_mole_frac_CO2_des[t]
        )

    m.fs_des.FB.co2_gas_mol_desorbed_per_cycle = Integral(
        m.fs_des.FB.time_set,
        wrt=m.fs_des.FB.time_set,
        rule=co2_gas_mol_desorbed_per_cycle,
        doc="CO2 gas mol desorbed per cycle, mol/cycle",
    )

    def co2_input_per_cycle(b, t):
        return (
            b.gas_phase.properties[0, 0]._params.mw_comp["CO2"]
            * gas_inlet_flow_mol_ads[t]
            * gas_inlet_mole_frac_CO2_ads[t]
        )

    m.fs_ads.FB.co2_input_per_cycle = Integral(
        m.fs_ads.FB.time_set,
        wrt=m.fs_ads.FB.time_set,
        rule=co2_input_per_cycle,
        doc="CO2 input processed per cycle, kg/cycle",
    )

    @m.Expression(doc="CO2 mol adsorbed per cycle, mol/cycle")
    def co2_mol_adsorbed_per_cycle(m):
        return (
            m.fs_ads.FB.carbamate_at_final_adsorption_time
            - m.fs_ads.FB.carbamate_at_initial_adsorption_time
        )

    @m.Expression(doc="CO2 mol desorbed per cycle, mol/cycle")
    def co2_mol_desorbed_per_cycle(m):
        return (
            m.fs_des.FB.carbamate_at_initial_desorption_time
            - m.fs_des.FB.carbamate_at_final_desorption_time
        )

    @m.Expression(doc="CO2 desorbed per cycle, kg/cycle")
    def co2_desorbed_per_cycle(m):
        return m.fs_des.FB.gas_phase.properties[0, 0]._params.mw_comp["CO2"] * (
            m.fs_des.FB.carbamate_at_initial_desorption_time
            - m.fs_des.FB.carbamate_at_final_desorption_time
        )

    @m.Expression(doc="CO2 adsorbed per cycle, kg/cycle")
    def co2_adsorbed_per_cycle(b):
        return b.fs_ads.FB.gas_phase.properties[0, 0]._params.mw_comp["CO2"] * (
            b.fs_ads.FB.carbamate_at_final_adsorption_time
            - b.fs_ads.FB.carbamate_at_initial_adsorption_time
        )

    def co2_released_per_cycle(b, t):
        return (
            b.gas_phase.properties[0, 0]._params.mw_comp["CO2"]
            * gas_outlet_flow_mol_ads[t]
            * gas_outlet_mole_frac_CO2_ads[t]
        )

    m.fs_ads.FB.co2_released_per_cycle = Integral(
        m.fs_ads.FB.time_set,
        wrt=m.fs_ads.FB.time_set,
        rule=co2_released_per_cycle,
        doc="CO2 released to atmosphere per cycle, kg/cycle",
    )

    @m.Expression(doc="H2O adsorbed per cycle, mol/cycle")
    def h2o_mol_adsorbed_per_cycle(m):
        return (
            m.fs_ads.FB.H2O_at_final_adsorption_time
            - m.fs_ads.FB.H2O_at_initial_adsorption_time
        )

    @m.Expression(doc="H2O desorbed per cycle, mol/cycle")
    def h2o_mol_desorbed_per_cycle(m):
        return (
            m.fs_des.FB.H2O_at_final_desorption_time
            - m.fs_des.FB.H2O_at_final_desorption_time
        )

    def total_gas_desorbed_per_cycle(b, t):
        return gas_outlet_flow_mol_des[t]

    m.fs_des.FB.total_gas_desorbed_per_cycle = Integral(
        m.fs_des.FB.time_set,
        wrt=m.fs_des.FB.time_set,
        rule=total_gas_desorbed_per_cycle,
        doc="Total gas desorbed per cycle, mol/cycle",
    )

    @m.Expression(doc="CO2 purity, [-]")
    def average_co2_purity_per_cycle(m):
        return (
            m.fs_des.FB.co2_gas_mol_desorbed_per_cycle
            / m.fs_des.FB.total_gas_desorbed_per_cycle
        )

    @m.Expression(doc="Average CO2 released to atmosphere, kg/s")
    def average_co2_released_per_cycle(m):
        return m.fs_ads.FB.co2_released_per_cycle / m.fs_ads.time.last()

    @m.Expression(doc="Cycle time, h")
    def cycle_time(m):
        # TODO - time for heating and cooling should be added even though small
        # 3600 seconds per hour
        return (m.fs_des.time.last() + m.fs_ads.time.last()) / 3600

    @m.Expression(doc="Cycles per year, cycles/year")
    def cycles_per_year(m):
        # TODO - time for heating and cooling should be added even though small
        # 8760 hours per year (assumes 100 % capacity factor)
        return 8760 / m.cycle_time

    @m.Expression(doc="CO2 captured per year, tonne/year")
    def co2_captured_per_year(m):
        # TODO - time for heating and cooling should be added even though small
        # 1e-3 tonne/kg conversion factor
        return (
            1e-3
            * m.fs_des.FB.gas_phase.properties[0, 0]._params.mw_comp["CO2"]
            * (
                m.fs_des.FB.carbamate_at_initial_desorption_time
                - m.fs_des.FB.carbamate_at_final_desorption_time
            )
        ) * m.cycles_per_year

    @m.Expression(doc="Productivity, kg CO2/tonne/h")
    def productivity(m):
        # 1e-6 tonne/kg is the conversion factor
        # cycle_time has units of h
        mass_adsorbent = 1e-6 * (
            m.fs_des.FB.solid_properties[0, 0].dens_mass_particle
            * m.fs_des.FB.solid_phase_area[0, 0]
            * m.fs_des.FB.bed_height
        )
        return (
            m.fs_des.FB.gas_phase.properties[0, 0]._params.mw_comp["CO2"]
            * (
                m.fs_des.FB.carbamate_at_initial_desorption_time
                - m.fs_des.FB.carbamate_at_final_desorption_time
            )
            / m.cycle_time
            / (mass_adsorbent)
        )

    @m.Expression(doc="Heat adsorbed total, J")
    def heat_adsorbed_total(b):
        heat_adsorbed_total = (
            b.h2o_mol_adsorbed_per_cycle
            * b.fs_ads.FB.solid_reactions[0, 0]._params.dh_rxn["R1"]
            + b.co2_mol_adsorbed_per_cycle
            * b.fs_ads.FB.solid_reactions[0, 0]._params.dh_rxn["R2"]
        )
        return heat_adsorbed_total

    @m.Expression(doc="Heat desorbed total, J")
    def heat_desorbed_total(b):
        # sign change of -1 is used to show that gas flow is in opposite
        # direction to adsorption flow
        heat_desorbed_total = -1 * (
            b.h2o_mol_desorbed_per_cycle
            * b.fs_des.FB.solid_reactions[0, 0]._params.dh_rxn["R1"]
            + b.co2_mol_desorbed_per_cycle
            * b.fs_des.FB.solid_reactions[0, 0]._params.dh_rxn["R2"]
        )
        return heat_desorbed_total

    @m.Expression(doc="Average heating duty, MW")
    def average_heating_duty(m):
        # 1e-6 MW/W is the conversion factor
        return (
            1e-6
            * (m.fs_des.q_preheating + m.heat_desorbed_total)
            / m.fs_des.time.last()
        )

    @m.Expression(doc="Average cooling duty, MW")
    def average_cooling_duty(m):
        # 1e-6 MW/W is the conversion factor
        return (
            1e-6
            * (m.fs_ads.q_precooling + m.heat_adsorbed_total)
            / m.fs_ads.time.last()
        )

    @m.Expression(doc="Specific thermal energy input, MJ/kg CO2")
    # Heat duty input needed for processes
    def specific_thermal_energy(m):
        # 1e-6 MJ/J is the conversion factor
        return (
            1e-6
            * (m.fs_des.q_preheating + m.heat_desorbed_total)
            / m.co2_desorbed_per_cycle
        )


def _var_dict(m, adsorption_temperature, desorption_temperature):
    """
    This function internally translate model results into a results dictionary.
    """

    var_dict = {}

    var_dict["Adsorption temperature [K]"] = adsorption_temperature
    var_dict["Desorption temperature [K]"] = desorption_temperature
    var_dict["Column diameter [m]"] = m.fs_ads.FB.bed_diameter
    var_dict["Column length [m]"] = m.fs_ads.FB.bed_height
    var_dict["CO2 mole fraction at feed [%]"] = (
        m.fs_ads.FB.gas_inlet.mole_frac_comp[0, "CO2"] * 100
    )
    var_dict["Feed flow rate [mol/s]"] = m.fs_ads.FB.gas_inlet.flow_mol[0]
    var_dict["Feed velocity [m/s]"] = m.fs_ads.FB.gas_inlet_velocity
    var_dict["Minimum fluidization velocity [m/s]"] = m.fs_ads.FB.solid_properties[
        0, 0
    ]._params.velocity_mf
    var_dict["Time of adsorption step [h]"] = m.fs_ads.time.last() / 3600
    var_dict["Time of desorption step [h]"] = m.fs_des.time.last() / 3600
    var_dict["Cycle time [h]"] = m.cycle_time

    var_dict["CO2 input per cycle [kg/bed/cycle]"] = m.fs_ads.FB.co2_input_per_cycle
    var_dict[
        "CO2 released per cycle [kg/bed/cycle]"
    ] = m.fs_ads.FB.co2_released_per_cycle
    var_dict["CO2 adsorbed per cycle [kg/bed/cycle]"] = m.co2_adsorbed_per_cycle
    var_dict["CO2 desorbed per cycle [kg/bed/cycle]"] = m.co2_desorbed_per_cycle

    var_dict["Purity [-]"] = m.average_co2_purity_per_cycle
    var_dict["Recovery [-]"] = m.co2_recovery_per_cycle
    var_dict["Productivity [kg CO2/ton/h]"] = m.productivity
    var_dict["Specific energy [MJ/kg CO2]"] = m.specific_thermal_energy
    var_dict["Heat duty per bed [MW]"] = m.average_heating_duty
    var_dict["Cooling duty per bed [MW]"] = m.average_cooling_duty
    var_dict["CO2 adsorbed per cycle CO2 balance [kg/bed/cycle]"] = value(
        m.fs_ads.FB.co2_input_per_cycle - m.fs_ads.FB.co2_released_per_cycle
    )
    var_dict[
        "CO2 adsorbed per cycle carbamate balance [kg/bed/cycle]"
    ] = m.co2_adsorbed_per_cycle
    var_dict["CO2 desorbed per cycle CO2 balance [kg/bed/cycle]"] = 0.044 * value(
        m.fs_des.FB.co2_gas_mol_desorbed_per_cycle
    )
    var_dict[
        "CO2 desorbed per cycle carbamate balance [kg/bed/cycle]"
    ] = m.co2_desorbed_per_cycle

    var_dict["Cycles per year"] = m.cycles_per_year

    var_dict[
        "Total CO2 captured per year per bed[tonne/year/bed]"
    ] = m.co2_captured_per_year

    var_dict["Amount of CO2 to atmosphere [kg/s]"] = m.average_co2_released_per_cycle

    return var_dict


def results_summary(m, adsorption_temperature, desorption_temperature):
    """
    This function reports the results dictionary.
    """

    var_dict = _var_dict(m, adsorption_temperature, desorption_temperature)

    print("\nReport fixed bed adsorption/desorption\n")
    for (
        k,
        v,
    ) in var_dict.items():
        print(f"{k}: {value(v):.4f}")
    print("")


def plot_results_temporal(fs, tji):
    """
    This function generates temporal results plots with spatial contours.
    """
    tf = fs.time.last()
    t_lower_plot = 200  # smallest time step (sec) to show in plot results

    Solid_temp = {}

    length_domain_set = fs.FB.length_domain.get_finite_elements()
    length_range = range(len(length_domain_set))
    spatial_points = 5  # Number of spatial points to show besides x=0, and x=1
    domain_divisor = (len(length_domain_set) - 1) / spatial_points
    length_list = [
        length_domain_set[x]
        for x in length_range
        if x % domain_divisor == 0 or length_domain_set[x] == 1
    ]

    time_index = 0
    Solid_temp = {}
    for t in tji.time:
        if t == 0 or t > t_lower_plot:
            Solid_temp[t] = []
            for x in length_list:
                # Solid temperature
                Solid_temp[t].append(
                    value(
                        tji.get_vec(fs.FB.solid_properties[tf, x].temperature)[
                            time_index
                        ]
                    )
                )
        time_index += 1

    time_index = 0
    Gas_temp = {}
    for t in tji.time:
        if t == 0 or t > t_lower_plot:
            Gas_temp[t] = []
            for x in length_list:
                # Gas temperature
                Gas_temp[t].append(
                    value(
                        tji.get_vec(fs.FB.gas_phase.properties[tf, x].temperature)[
                            time_index
                        ]
                    )
                )
        time_index += 1

    time_index = 0
    Bed_pressure = {}
    for t in tji.time:
        if t == 0 or t > t_lower_plot:
            Bed_pressure[t] = []
            for x in length_list:
                # Fuel conversion
                Bed_pressure[t].append(
                    value(
                        tji.get_vec(fs.FB.gas_phase.properties[tf, x].pressure)[
                            time_index
                        ]
                    )
                )
        time_index += 1

    time_index = 0
    Car_frac = {}
    for t in tji.time:
        if t == 0 or t > t_lower_plot:
            Car_frac[t] = []
            for x in length_list:
                # Carbamate mass fraction
                Car_frac[t].append(
                    value(
                        tji.get_vec(
                            fs.FB.solid_properties[tf, x].mass_frac_comp["Car"]
                        )[time_index]
                    )
                )
        time_index += 1

    time_index = 0
    Car_conc = {}
    for t in tji.time:
        if t == 0 or t > t_lower_plot:
            Car_conc[t] = []
            for x in length_list:
                # Carbamate concentration - equivalent to CO2 adsorbed mol/kg_solid
                Car_conc[t].append(
                    value(
                        tji.get_vec(
                            fs.FB.solid_reactions[tf, x].specie_concentration["Car"]
                        )[time_index]
                    )
                )
        time_index += 1

    time_index = 0
    H2O_s_frac = {}
    for t in tji.time:
        if t == 0 or t > t_lower_plot:
            H2O_s_frac[t] = []
            for x in length_list:
                # H2O(s) mass fraction
                H2O_s_frac[t].append(
                    value(
                        tji.get_vec(
                            fs.FB.solid_properties[tf, x].mass_frac_comp["H2O_s"]
                        )[time_index]
                    )
                )
        time_index += 1

    time_index = 0
    H2O_s_conc = {}
    for t in tji.time:
        if t == 0 or t > t_lower_plot:
            H2O_s_conc[t] = []
            for x in length_list:
                # H2O(s) concentration - equivalent to H2O adsorbed mol/kg_solid
                H2O_s_conc[t].append(
                    value(
                        tji.get_vec(
                            fs.FB.solid_reactions[tf, x].specie_concentration["H2O_s"]
                        )[time_index]
                    )
                )
        time_index += 1

    time_index = 0
    CO2_frac = {}
    for t in tji.time:
        if t == 0 or t > t_lower_plot:
            CO2_frac[t] = []
            for x in length_list:
                # CO2 mole fraction
                CO2_frac[t].append(
                    value(
                        tji.get_vec(
                            fs.FB.gas_phase.properties[tf, x].mole_frac_comp["CO2"]
                        )[time_index]
                    )
                )
        time_index += 1

    time_index = 0
    H2O_frac = {}
    for t in tji.time:
        if t == 0 or t > t_lower_plot:
            H2O_frac[t] = []
            for x in length_list:
                # H2O mole fraction
                H2O_frac[t].append(
                    value(
                        tji.get_vec(
                            fs.FB.gas_phase.properties[tf, x].mole_frac_comp["H2O"]
                        )[time_index]
                    )
                )
        time_index += 1

    time_index = 0
    CO2_flow = {}
    for t in tji.time:
        if t == 0 or t > t_lower_plot:
            CO2_flow[t] = []
            for x in length_list:
                # CO2 gas flowrate
                CO2_flow[t].append(
                    value(
                        tji.get_vec(fs.FB.gas_phase.properties[tf, x].flow_mol)[
                            time_index
                        ]
                        * tji.get_vec(
                            fs.FB.gas_phase.properties[tf, x].mole_frac_comp["CO2"]
                        )[time_index]
                    )
                )
        time_index += 1

    time_index = 0
    H2O_flow = {}
    for t in tji.time:
        if t == 0 or t > t_lower_plot:
            H2O_flow[t] = []
            for x in length_list:
                # H2O gas flowrate
                H2O_flow[t].append(
                    value(
                        tji.get_vec(fs.FB.gas_phase.properties[tf, x].flow_mol)[
                            time_index
                        ]
                        * tji.get_vec(
                            fs.FB.gas_phase.properties[tf, x].mole_frac_comp["H2O"]
                        )[time_index]
                    )
                )
        time_index += 1

    time_index = 0
    Gas_flow = {}
    for t in tji.time:
        if t == 0 or t > t_lower_plot:
            Gas_flow[t] = []
            for x in length_list:
                # Gas gas flowrate
                Gas_flow[t].append(
                    value(
                        tji.get_vec(fs.FB.gas_phase.properties[tf, x].flow_mol)[
                            time_index
                        ]
                    )
                )
        time_index += 1

    # Create panda data frames with data
    Solid_temp_pd = pd.DataFrame(Solid_temp, index=length_list).transpose()
    Gas_temp_pd = pd.DataFrame(Gas_temp, index=length_list).transpose()
    Pressure_pd = pd.DataFrame(Bed_pressure, index=length_list).transpose()
    CO2_frac_pd = pd.DataFrame(CO2_frac, index=length_list).transpose()
    H2O_frac_pd = pd.DataFrame(H2O_frac, index=length_list).transpose()
    Car_frac_pd = pd.DataFrame(Car_frac, index=length_list).transpose()
    Car_conc_pd = pd.DataFrame(Car_conc, index=length_list).transpose()
    H2O_s_frac_pd = pd.DataFrame(H2O_s_frac, index=length_list).transpose()
    H2O_s_conc_pd = pd.DataFrame(H2O_s_conc, index=length_list).transpose()
    CO2_flow_pd = pd.DataFrame(CO2_flow, index=length_list).transpose()
    H2O_flow_pd = pd.DataFrame(H2O_flow, index=length_list).transpose()
    Gas_flow_pd = pd.DataFrame(Gas_flow, index=length_list).transpose()

    panda_dict = {
        "Solid_temp": Solid_temp_pd,
        "Gas_temp": Gas_temp_pd,
        "Pressure": Pressure_pd,
        "CO2_frac": CO2_frac_pd,
        "H2O_frac": H2O_frac_pd,
        "Car_frac": Car_frac_pd,
        "Car_conc": Car_conc_pd,
        "H2O_s_frac": H2O_s_frac_pd,
        "H2O_s_conc": H2O_s_conc_pd,
        "CO2_flow": CO2_flow_pd,
        "H2O_flow": H2O_flow_pd,
        "Gas_flow": Gas_flow_pd,
    }

    # Plot results
    # General plt options
    plt.rcParams.update(
        {
            "figure.max_open_warning": 0,
            "axes.titlesize": 14,
            "axes.labelsize": 14,
            "axes.linewidth": 2,
            "lines.linewidth": 3,
            "lines.markersize": 10,
            "xtick.labelsize": 14,
            "ytick.labelsize": 14,
            "savefig.bbox": "tight",
            "legend.fontsize": "large",
        }
    )

    ax1 = plt.gca()
    panda_dict["Gas_flow"].plot(kind="line", ax=ax1)
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel("Gas flowrate (mol/s)")
    plt.show()

    ax2 = plt.gca()
    panda_dict["Pressure"].plot(kind="line", ax=ax2)
    ax2.set_xlabel("Time (s)")
    ax2.set_ylabel("Bed Pressure (Pa)")
    plt.show()

    ax3 = plt.gca()
    panda_dict["Gas_temp"].plot(kind="line", ax=ax3)
    ax3.set_xlabel("Time (s)")
    ax3.set_ylabel("Gas Temperature (K)")
    plt.show()

    ax4 = plt.gca()
    panda_dict["Solid_temp"].plot(kind="line", ax=ax4)
    ax4.set_xlabel("Time (s)")
    ax4.set_ylabel("Solid Temperature (K)")
    plt.show()

    ax5 = plt.gca()
    panda_dict["CO2_frac"].plot(kind="line", ax=ax5)
    ax5.set_xlabel("Time (s)")
    ax5.set_ylabel("CO2(g) mole fraction (-)")
    plt.show()

    ax6 = plt.gca()
    panda_dict["H2O_frac"].plot(kind="line", ax=ax6)
    ax6.set_xlabel("Time (s)")
    ax6.set_ylabel("H2O(g) mole fraction (-)")
    plt.show()

    ax7 = plt.gca()
    panda_dict["Car_frac"].plot(kind="line", ax=ax7)
    ax7.set_xlabel("Time (s)")
    ax7.set_ylabel("Carbamate mass fraction (-)")
    plt.show()

    ax8 = plt.gca()
    panda_dict["H2O_s_frac"].plot(kind="line", ax=ax8)
    ax8.set_xlabel("Time (s)")
    ax8.set_ylabel("H2O(s) mass fraction (-)")
    plt.show()

    ax9 = plt.gca()
    panda_dict["Car_conc"].plot(kind="line", ax=ax9)
    ax9.set_xlabel("Time (s)")
    ax9.set_ylabel("Carbamate conc. (mol/kg)")
    plt.show()

    ax10 = plt.gca()
    panda_dict["H2O_s_conc"].plot(kind="line", ax=ax10)
    ax10.set_xlabel("Time (s)")
    ax10.set_ylabel("H2O(s) conc. (mol/kg)")
    plt.show()

    ax11 = plt.gca()
    panda_dict["CO2_flow"].plot(kind="line", ax=ax11)
    ax11.set_xlabel("Time (s)")
    ax11.set_ylabel("CO2(g) flowrate (mol/s)")
    plt.show()

    ax12 = plt.gca()
    panda_dict["H2O_flow"].plot(kind="line", ax=ax12)
    ax12.set_xlabel("Time (s)")
    ax12.set_ylabel("H2O(g) flowrate (mol/s)")
    plt.show()


def plot_results_spatial(fs, tji):
    """
    This function generates spatial results plots with temporal contours.
    """
    tf = fs.time.last()

    Solid_temp = {}

    length_domain_set = fs.FB.length_domain.get_finite_elements()
    length_list = [x for x in length_domain_set]

    time_index = 0
    Solid_temp = {}
    for t in tji.time:
        Solid_temp[t] = []
        for x in length_list:
            # Solid temperature
            Solid_temp[t].append(
                value(
                    tji.get_vec(fs.FB.solid_properties[tf, x].temperature)[time_index]
                )
            )
        time_index += 1

    time_index = 0
    Gas_temp = {}
    for t in tji.time:
        Gas_temp[t] = []
        for x in length_list:
            # Gas temperature
            Gas_temp[t].append(
                value(
                    tji.get_vec(fs.FB.gas_phase.properties[tf, x].temperature)[
                        time_index
                    ]
                )
            )
        time_index += 1

    time_index = 0
    Bed_pressure = {}
    for t in tji.time:
        Bed_pressure[t] = []
        for x in length_list:
            # Fuel conversion
            Bed_pressure[t].append(
                value(
                    tji.get_vec(fs.FB.gas_phase.properties[tf, x].pressure)[time_index]
                )
            )
        time_index += 1

    time_index = 0
    Car_frac = {}
    for t in tji.time:
        Car_frac[t] = []
        for x in length_list:
            # Carbamate mass fraction
            Car_frac[t].append(
                value(
                    tji.get_vec(fs.FB.solid_properties[tf, x].mass_frac_comp["Car"])[
                        time_index
                    ]
                )
            )
        time_index += 1

    time_index = 0
    Car_conc = {}
    for t in tji.time:
        Car_conc[t] = []
        for x in length_list:
            # Carbamate concentration - equivalent to CO2 adsorbed mol/kg_solid
            Car_conc[t].append(
                value(
                    tji.get_vec(
                        fs.FB.solid_reactions[tf, x].specie_concentration["Car"]
                    )[time_index]
                )
            )
        time_index += 1

    time_index = 0
    H2O_s_frac = {}
    for t in tji.time:
        H2O_s_frac[t] = []
        for x in length_list:
            # H2O(s) mass fraction
            H2O_s_frac[t].append(
                value(
                    tji.get_vec(fs.FB.solid_properties[tf, x].mass_frac_comp["H2O_s"])[
                        time_index
                    ]
                )
            )
        time_index += 1

    time_index = 0
    H2O_s_conc = {}
    for t in tji.time:
        H2O_s_conc[t] = []
        for x in length_list:
            # H2O(s) concentration - equivalent to H2O adsorbed mol/kg_solid
            H2O_s_conc[t].append(
                value(
                    tji.get_vec(
                        fs.FB.solid_reactions[tf, x].specie_concentration["H2O_s"]
                    )[time_index]
                )
            )
        time_index += 1

    time_index = 0
    CO2_frac = {}
    for t in tji.time:
        CO2_frac[t] = []
        for x in length_list:
            # CO2 mole fraction
            CO2_frac[t].append(
                value(
                    tji.get_vec(
                        fs.FB.gas_phase.properties[tf, x].mole_frac_comp["CO2"]
                    )[time_index]
                )
            )
        time_index += 1

    time_index = 0
    H2O_frac = {}
    for t in tji.time:
        H2O_frac[t] = []
        for x in length_list:
            # H2O mole fraction
            H2O_frac[t].append(
                value(
                    tji.get_vec(
                        fs.FB.gas_phase.properties[tf, x].mole_frac_comp["H2O"]
                    )[time_index]
                )
            )
        time_index += 1

    time_index = 0
    CO2_flow = {}
    for t in tji.time:
        CO2_flow[t] = []
        for x in length_list:
            # CO2 gas flowrate
            CO2_flow[t].append(
                value(
                    tji.get_vec(fs.FB.gas_phase.properties[tf, x].flow_mol)[time_index]
                    * tji.get_vec(
                        fs.FB.gas_phase.properties[tf, x].mole_frac_comp["CO2"]
                    )[time_index]
                )
            )
        time_index += 1

    time_index = 0
    H2O_flow = {}
    for t in tji.time:
        H2O_flow[t] = []
        for x in length_list:
            # H2O gas flowrate
            H2O_flow[t].append(
                value(
                    tji.get_vec(fs.FB.gas_phase.properties[tf, x].flow_mol)[time_index]
                    * tji.get_vec(
                        fs.FB.gas_phase.properties[tf, x].mole_frac_comp["H2O"]
                    )[time_index]
                )
            )
        time_index += 1

    time_index = 0
    Gas_flow = {}
    for t in tji.time:
        Gas_flow[t] = []
        for x in length_list:
            # Gas gas flowrate
            Gas_flow[t].append(
                value(
                    tji.get_vec(fs.FB.gas_phase.properties[tf, x].flow_mol)[time_index]
                )
            )
        time_index += 1

    # Create panda data frames with data
    Solid_temp_pd = pd.DataFrame(Solid_temp, index=length_list).transpose()
    Gas_temp_pd = pd.DataFrame(Gas_temp, index=length_list).transpose()
    Pressure_pd = pd.DataFrame(Bed_pressure, index=length_list).transpose()
    CO2_frac_pd = pd.DataFrame(CO2_frac, index=length_list).transpose()
    H2O_frac_pd = pd.DataFrame(H2O_frac, index=length_list).transpose()
    Car_frac_pd = pd.DataFrame(Car_frac, index=length_list).transpose()
    Car_conc_pd = pd.DataFrame(Car_conc, index=length_list).transpose()
    H2O_s_frac_pd = pd.DataFrame(H2O_s_frac, index=length_list).transpose()
    H2O_s_conc_pd = pd.DataFrame(H2O_s_conc, index=length_list).transpose()
    CO2_flow_pd = pd.DataFrame(CO2_flow, index=length_list).transpose()
    H2O_flow_pd = pd.DataFrame(H2O_flow, index=length_list).transpose()
    Gas_flow_pd = pd.DataFrame(Gas_flow, index=length_list).transpose()

    panda_dict_original = {
        "Solid_temp": Solid_temp_pd,
        "Gas_temp": Gas_temp_pd,
        "Pressure": Pressure_pd,
        "CO2_frac": CO2_frac_pd,
        "H2O_frac": H2O_frac_pd,
        "Car_frac": Car_frac_pd,
        "Car_conc": Car_conc_pd,
        "H2O_s_frac": H2O_s_frac_pd,
        "H2O_s_conc": H2O_s_conc_pd,
        "CO2_flow": CO2_flow_pd,
        "H2O_flow": H2O_flow_pd,
        "Gas_flow": Gas_flow_pd,
    }

    # Create new time points for interpolation
    new_time_points = np.around(np.linspace(0, tf, 5))

    panda_dict_interpolated = {}  # dictionary for storing interpolated pandas
    for key, panda in panda_dict_original.items():
        # Add the new time points to the time axis
        panda = panda.reindex(panda.index.union(new_time_points))
        # Interpolate btw data points to fill missing data for new time points
        panda = panda.interpolate(method="linear", limit_direction="forward")
        # Keep only the new time points by reindexing
        panda = panda.reindex(new_time_points)
        panda = panda.transpose()
        panda_dict_interpolated[key] = panda

    # Plot results
    # General plt options
    plt.rcParams.update(
        {
            "figure.max_open_warning": 0,
            "axes.titlesize": 14,
            "axes.labelsize": 14,
            "axes.linewidth": 2,
            "lines.linewidth": 3,
            "lines.markersize": 10,
            "xtick.labelsize": 14,
            "ytick.labelsize": 14,
            "savefig.bbox": "tight",
            "legend.fontsize": "large",
        }
    )

    ax1 = plt.gca()
    panda_dict_interpolated["Gas_flow"].plot(kind="line", ax=ax1)
    ax1.set_xlabel("Normalized Length (-)")
    ax1.set_ylabel("Gas flowrate (mol/s)")
    plt.show()

    ax2 = plt.gca()
    panda_dict_interpolated["Pressure"].plot(kind="line", ax=ax2)
    ax2.set_xlabel("Normalized Length (-)")
    ax2.set_ylabel("Bed Pressure (Pa)")
    plt.show()

    ax3 = plt.gca()
    panda_dict_interpolated["Gas_temp"].plot(kind="line", ax=ax3)
    ax3.set_xlabel("Normalized Length (-)")
    ax3.set_ylabel("Gas Temperature (K)")
    plt.show()

    ax4 = plt.gca()
    panda_dict_interpolated["Solid_temp"].plot(kind="line", ax=ax4)
    ax4.set_xlabel("Normalized Length (-)")
    ax4.set_ylabel("Solid Temperature (K)")
    plt.show()

    ax5 = plt.gca()
    panda_dict_interpolated["CO2_frac"].plot(kind="line", ax=ax5)
    ax5.set_xlabel("Normalized Length (-)")
    ax5.set_ylabel("CO2(g) mole fraction (-)")
    plt.show()

    ax6 = plt.gca()
    panda_dict_interpolated["H2O_frac"].plot(kind="line", ax=ax6)
    ax6.set_xlabel("Normalized Length (-)")
    ax6.set_ylabel("H2O(g) mole fraction (-)")
    plt.show()

    ax7 = plt.gca()
    panda_dict_interpolated["Car_frac"].plot(kind="line", ax=ax7)
    ax7.set_xlabel("Normalized Length (-)")
    ax7.set_ylabel("Carbamate mass fraction (-)")
    plt.show()

    ax8 = plt.gca()
    panda_dict_interpolated["H2O_s_frac"].plot(kind="line", ax=ax8)
    ax8.set_xlabel("Normalized Length (-)")
    ax8.set_ylabel("H2O(s) mass fraction (-)")
    plt.show()

    ax9 = plt.gca()
    panda_dict_interpolated["Car_conc"].plot(kind="line", ax=ax9)
    ax9.set_xlabel("Normalized Length (-)")
    ax9.set_ylabel("Carbamate [adsorbed CO2] conc. (mol/kg)")
    plt.show()

    ax10 = plt.gca()
    panda_dict_interpolated["H2O_s_conc"].plot(kind="line", ax=ax10)
    ax10.set_xlabel("Normalized Length (-)")
    ax10.set_ylabel("H2O(s) [adsorbed H2O] conc. (mol/kg)")
    plt.show()

    ax11 = plt.gca()
    panda_dict_interpolated["CO2_flow"].plot(kind="line", ax=ax11)
    ax11.set_xlabel("Normalized Length (-)")
    ax11.set_ylabel("CO2(g) flowrate (mol/s)")
    plt.show()

    ax12 = plt.gca()
    panda_dict_interpolated["H2O_flow"].plot(kind="line", ax=ax12)
    ax12.set_xlabel("Normalized Length (-)")
    ax12.set_ylabel("H2O(g) flowrate (mol/s)")
    plt.show()
