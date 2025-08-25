#################################################################################
# The Institute for the Design of Advanced Energy Systems Integrated Platform
# Framework (IDAES IP) was produced under the DOE Institute for the
# Design of Advanced Energy Systems (IDAES).
#
# Copyright (c) 2018-2024 by the software owners: The Regents of the
# University of California, through Lawrence Berkeley National Laboratory,
# National Technology & Engineering Solutions of Sandia, LLC, Carnegie Mellon
# University, West Virginia University Research Corporation, et al.
# All rights reserved.  Please see the files COPYRIGHT.md and LICENSE.md
# for full copyright and license information.
#################################################################################
"""
Benzene-Toluene phase equilibrium package using ideal liquid and vapor.

Example property package using the Generic Property Package Framework.
This exmample shows how to set up a property package to do benzene-toluene
phase equilibrium in the generic framework using ideal liquid and vapor
assumptions along with methods drawn from the pre-built IDAES property
libraries.
"""
# Import Pyomo units
from pyomo.environ import units as pyunits

# Import IDAES cores
from idaes.core import LiquidPhase, VaporPhase, Component
import idaes.logger as idaeslog

from idaes.models.properties.modular_properties.state_definitions import FTPx
from idaes.models.properties.modular_properties.eos.ideal import Ideal
from idaes.models.properties.modular_properties.phase_equil import SmoothVLE
from idaes.models.properties.modular_properties.phase_equil.bubble_dew import (
    IdealBubbleDew,
)
from idaes.models.properties.modular_properties.phase_equil.forms import fugacity
from idaes.models.properties.modular_properties.pure import Perrys
from idaes.models.properties.modular_properties.pure import RPP5
from idaes.models.properties.modular_properties.reactions.rate_forms import power_law_rate
from idaes.models.properties.modular_properties.reactions.dh_rxn import constant_dh_rxn
from idaes.models.properties.modular_properties.reactions.rate_constant import arrhenius
from idaes.models.properties.modular_properties.base.utility import ConcentrationForm

# Set up logger
_log = idaeslog.getLogger(__name__)

# ---------------------------------------------------------------------
# Configuration dictionary for an ideal Benzene-Toluene system

# Data Sources:
# [1] The Properties of Gases and Liquids (1987)
#     4th edition, Chemical Engineering Series - Robert C. Reid
# [2] Perry's Chemical Engineers' Handbook 7th Ed.
# [3] Engineering Toolbox, https://www.engineeringtoolbox.com
#     Retrieved 1st December, 2019

reaction_config = {

    'rate_reactions': {
        "hydrodealkylation": {
            "stoichiometry": {
                ("Vap", "benzene"): 1,
                ("Vap", "toluene"): -1,
                ("Vap", "hydrogen"): -1,
                ("Vap", "methane"): 1,
            },
            "heat_of_reaction": constant_dh_rxn,
            "rate_constant": arrhenius,
            "rate_form": power_law_rate,
            "concentration_form": ConcentrationForm.partialPressure,
            "parameter_data": {
                "dh_rxn_ref": (-1.08e5, pyunits.J / pyunits.mol),
                "arrhenius_const": (6.3e10, pyunits.mol * pyunits.m ** -3 * pyunits.s ** -1 * pyunits.Pa ** -1.5),
                "energy_activation": (217.6e3, pyunits.J / pyunits.mol),
                "reaction_order": {
                    ("Vap", "benzene"): 0,
                    ("Vap", "toluene"): 1.0,
                    ("Vap", "hydrogen"): .5,
                    ("Vap", "methane"): 0, }
            }
        }
    },

    # Set base units of measurement
    "base_units": {
        "time": pyunits.s,
        "length": pyunits.m,
        "mass": pyunits.kg,
        "amount": pyunits.mol,
        "temperature": pyunits.K,
    },
}
