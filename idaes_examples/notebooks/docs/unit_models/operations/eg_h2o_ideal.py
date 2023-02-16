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
# Import Python libraries
import logging

# Import Pyomo units
from pyomo.environ import units as pyunits

# Import IDAES cores
from idaes.core import LiquidPhase, Component

from idaes.models.properties.modular_properties.state_definitions import FpcTP
from idaes.models.properties.modular_properties.eos.ideal import Ideal
from idaes.models.properties.modular_properties.phase_equil.forms import fugacity
from idaes.models.properties.modular_properties.pure.Perrys import Perrys
from idaes.models.properties.modular_properties.pure.RPP4 import RPP4

# Set up logger
_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Configuration dictionary for an ideal ethylene oxide, water,
# sulfuric acid, and ethylene glycol system

# Data Sources:
# [1] The Properties of Gases and Liquids (1987)
#     4th edition, Chemical Engineering Series - Robert C. Reid
# [2] Perry's Chemical Engineers' Handbook 7th Ed.
# [3] NIST Chemistry WebBook, https://webbook.nist.gov/chemistry/
#     Retrieved 23rd September, 2021

config_dict = {
    # Specifying components
    "components": {
        'water':
            {"type": Component,
             "elemental_composition": {"H": 2, "O": 1},
             "dens_mol_liq_comp": Perrys,
             "enth_mol_liq_comp": Perrys,
             "enth_mol_ig_comp": RPP4,
             "pressure_sat_comp": RPP4,
             "phase_equilibrium_form": {("Vap", "Liq"): fugacity},
             "parameter_data": {
                 "mw": (18.015E-3, pyunits.kg/pyunits.mol),  # [1]
                 "pressure_crit": (221.2e5, pyunits.Pa),  # [1]
                 "temperature_crit": (647.3, pyunits.K),  # [1]
                 "dens_mol_liq_comp_coeff": {
                     'eqn_type': 2,
                     '1': (-13.851, pyunits.kmol/pyunits.m**3),  # [2]pg. 2-98
                     '2': (0.64038, pyunits.kmol/pyunits.m**3/pyunits.K),
                     '3': (-0.00191, pyunits.kmol/pyunits.m**3/pyunits.K**2),
                     '4': (1.8211E-6, pyunits.kmol/pyunits.m**3/pyunits.K**3)},
                 "cp_mol_ig_comp_coeff": {
                     'A': (3.194E1, pyunits.J/pyunits.mol/pyunits.K),  # [1]
                     'B': (1.436E-3, pyunits.J/pyunits.mol/pyunits.K**2),
                     'C': (2.432E-5, pyunits.J/pyunits.mol/pyunits.K**3),
                     'D': (-1.176E-8, pyunits.J/pyunits.mol/pyunits.K**4)},
                 "cp_mol_liq_comp_coeff": {
                     '1': (2.7637E2, pyunits.J/pyunits.kmol/pyunits.K),  # [2]
                     '2': (-2.0901, pyunits.J/pyunits.kmol/pyunits.K**2),
                     '3': (8.125E-3, pyunits.J/pyunits.kmol/pyunits.K**3),
                     '4': (-1.4116E-5, pyunits.J/pyunits.kmol/pyunits.K**4),
                     '5': (9.3701E-9, pyunits.J/pyunits.kmol/pyunits.K**5)},
                 "enth_mol_form_liq_comp_ref": (
                     -285.83e3, pyunits.J/pyunits.mol),  # [3]
                 "enth_mol_form_vap_comp_ref": (
                     -241.836e3, pyunits.J/pyunits.mol),  # [3]
                 "pressure_sat_comp_coeff": {'A': (-7.76451, None),  # [1]
                                             'B': (1.45838, None),
                                             'C': (-2.77580, None),
                                             'D': (-1.23303, None)}}},
        'ethylene_glycol':
            {"type": Component,
             "elemental_composition": {"C": 2, "H": 6, "O": 2},
             "dens_mol_liq_comp": Perrys,
             "enth_mol_liq_comp": Perrys,
             "enth_mol_ig_comp": RPP4,
             "pressure_sat_comp": RPP4,
             "phase_equilibrium_form": {("Vap", "Liq"): fugacity},
             "parameter_data": {
                 "mw": (62.069E-3, pyunits.kg/pyunits.mol),  # [1]
                 "pressure_crit": (77e5, pyunits.Pa),  # [1]
                 "temperature_crit": (645, pyunits.K),  # [1]
                 "dens_mol_liq_comp_coeff": {
                     'eqn_type': 1,
                     '1': (1.315, pyunits.kmol*pyunits.m**-3),  # [2] pg. 2-98
                     '2': (0.25125, None),
                     '3': (720, pyunits.K),
                     '4': (0.21868, None)},
                 "cp_mol_ig_comp_coeff": {
                     'A': (3.570E1, pyunits.J/pyunits.mol/pyunits.K),  # [1]
                     'B': (2.483E-1, pyunits.J/pyunits.mol/pyunits.K**2),
                     'C': (-1.497E-4, pyunits.J/pyunits.mol/pyunits.K**3),
                     'D': (3.010E-8, pyunits.J/pyunits.mol/pyunits.K**4)},
                 "cp_mol_liq_comp_coeff": {
                     '1': (3.5540E1, pyunits.J/pyunits.kmol/pyunits.K),  # [2]
                     '2': (4.3678E-1, pyunits.J/pyunits.kmol/pyunits.K**2),
                     '3': (-1.8486E-4, pyunits.J/pyunits.kmol/pyunits.K**3),
                     '4': (0, pyunits.J/pyunits.kmol/pyunits.K**4),
                     '5': (0, pyunits.J/pyunits.kmol/pyunits.K**5)},
                 "enth_mol_form_liq_comp_ref": (
                     -455.24e3, pyunits.J/pyunits.mol),  # [3]
                 "enth_mol_form_vap_comp_ref": (
                     -389.37e3, pyunits.J/pyunits.mol),  # [3]
                 "pressure_sat_comp_coeff": {'A': (13.6299, None),  # [1]
                                             'B': (6022.18, None),
                                             'C': (-28.25, None),
                                             'D': (0, None)}}}},

    # Specifying phases
    "phases":  {'Liq': {"type": LiquidPhase,
                        "equation_of_state": Ideal}},

    # Set base units of measurement
    "base_units": {"time": pyunits.s,
                   "length": pyunits.m,
                   "mass": pyunits.kg,
                   "amount": pyunits.mol,
                   "temperature": pyunits.K},

    # Specifying state definition
    "state_definition": FpcTP,
    "state_bounds": {"flow_mol_phase_comp": (0, 100, 1000,
                                             pyunits.mol/pyunits.s),
                     "temperature": (273.15, 298.15, 450, pyunits.K),
                     "pressure": (1e3, 1e5, 1e6, pyunits.Pa)},
    "pressure_ref": (1e5, pyunits.Pa),
    "temperature_ref": (298.15, pyunits.K)}
