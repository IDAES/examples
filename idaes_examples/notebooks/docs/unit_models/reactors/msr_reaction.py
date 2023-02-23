#################################################################################
# The Institute for the Design of Advanced Energy Systems Integrated Platform
# Framework (IDAES IP) was produced under the DOE Institute for the
# Design of Advanced Energy Systems (IDAES).
#
# Copyright (c) 2018-2023 by the software owners: The Regents of the
# University of California, through Lawrence Berkeley National Laboratory,
# National Technology & Engineering Solutions of Sandia, LLC, Carnegie Mellon
# University, West Virginia University Research Corporation, et al.
# All rights reserved.  Please see the files COPYRIGHT.md and LICENSE.md
# for full copyright and license information.
#################################################################################
"""
Property package for Methane Steam Reforming and Water Gas Shift
using Peng-Robinson equation of state.

Author: Brandon Paul
"""
from pyomo.environ import units as pyunits

from idaes.models.properties.modular_properties.base.generic_reaction import \
    ConcentrationForm
from idaes.models.properties.modular_properties.reactions.dh_rxn import \
    constant_dh_rxn
from idaes.models.properties.modular_properties.reactions.equilibrium_constant import \
    van_t_hoff
from idaes.models.properties.modular_properties.reactions.equilibrium_forms import \
    power_law_equil

# empirical expressions for equilibrium constants as functions of temperature
# Source: Int. J. Hydrogen Energy, 42 (2017), pp. 2889-2903
# to convert to vant hoff form for correlation log(keq) = A/T + B,
# k_eq_ref = 10^(B + A/T_eq_ref) where T_eq_ref is chosen in K
# T_eq_ref chosen as 973.15 K (700 C), the case study catalyst temperature

# For this example, the thermophysical properties are imported from the
# IDAES natural gas property package (located in the power generation folder)

config_dict = {
    "base_units": {"time": pyunits.s,
                   "length": pyunits.m,
                   "mass": pyunits.kg,
                   "amount": pyunits.mol,
                   "temperature": pyunits.K},
    "equilibrium_reactions": {
        #  Steam Methane Reformation Reaction
        "E1": {"stoichiometry": {("Vap", "CH4"): -1,
                                 ("Vap", "H2O"): -1,
                                 ("Vap", "CO"): 1,
                                 ("Vap", "H2"): 3,
                                 ("Vap", "CO2"): 0},
               "heat_of_reaction": constant_dh_rxn,
               "equilibrium_constant": van_t_hoff,
               "equilibrium_form": power_law_equil,
               "concentration_form": ConcentrationForm.moleFraction,
               "parameter_data": {  # from log(keq) = -26830/T + 30.114
                   "dh_rxn_ref": (206000, pyunits.J/pyunits.mol),  # 223077
                   "k_eq_ref": (12.727, None),
                   "T_eq_ref": (973.15, pyunits.K)}},

        #  Water Gas Shift Reaction
        "E2": {"stoichiometry": {("Vap", "CH4"): 0,
                                 ("Vap", "H2O"): -1,
                                 ("Vap", "CO"): -1,
                                 ("Vap", "H2"): 1,
                                 ("Vap", "CO2"): 1},
               "heat_of_reaction": constant_dh_rxn,
               "equilibrium_constant": van_t_hoff,
               "equilibrium_form": power_law_equil,
               "concentration_form": ConcentrationForm.moleFraction,
               "parameter_data": {  # from log(keq) = 4400/T -4.036
                   "dh_rxn_ref": (-41000, pyunits.J/pyunits.mol),  # -36584
                   "k_eq_ref": (1.6248, None),
                   "T_eq_ref": (973.15, pyunits.K)}}}}
