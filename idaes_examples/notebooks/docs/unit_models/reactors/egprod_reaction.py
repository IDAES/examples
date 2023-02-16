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
Phase equilibrium package for Ethylene Oxide hydrolysis to Ethylene Glycol
using ideal liquid and vapor.

Author: Brandon Paul
"""
from pyomo.environ import units as pyunits

from idaes.models.properties.modular_properties.base.generic_reaction import (
        ConcentrationForm)
from idaes.models.properties.modular_properties.reactions.dh_rxn import \
    constant_dh_rxn
from idaes.models.properties.modular_properties.reactions.rate_constant import \
    arrhenius
from idaes.models.properties.modular_properties.reactions.rate_forms import \
    power_law_rate


# For this example, the thermophysical properties are imported from the
# corresponding ideal property package, egprod_ideal.py

# Next, create the reaction property definition which describes the system on
# reactions to be modeled.
config_dict = {
    "base_units": {"time": pyunits.s,
                   "length": pyunits.m,
                   "mass": pyunits.kg,
                   "amount": pyunits.mol,
                   "temperature": pyunits.K},
    "rate_reactions": {
        "R1": {"stoichiometry": {("Liq", "ethylene_oxide"): -1,
                                 ("Liq", "water"): -1,
                                 ("Liq", "sulfuric_acid"): 0,  # catalyst
                                 ("Liq", "ethylene_glycol"): 1},
               "heat_of_reaction": constant_dh_rxn,
               "rate_constant": arrhenius,
               "rate_form": power_law_rate,
               "concentration_form": ConcentrationForm.molarity,  # m3 or L?
               "parameter_data": {  # Activation energy and heat of reaction
                                    # Phys.Chem.Chem.Phys., 2018, 20, 7701-7709
                                    # Arrhenius constant calculated from k =
                                    # 0.331/min (Elements of Chemical Reaction
                                    # Engineering 5th ed, Fogler, p. 157-160)
                                    # 1st order in EO, assume excess water/cat.
                   "reaction_order": {("Liq", "ethylene_oxide"): 1},
                   "dh_rxn_ref": (-48199.68, pyunits.J/pyunits.mol),
                   "arrhenius_const": (1.5638e-9, pyunits.s**-1),
                   "energy_activation": (-40961.36, pyunits.J/pyunits.mol)}}}}
