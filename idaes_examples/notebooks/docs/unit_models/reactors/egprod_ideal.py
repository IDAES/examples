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
from idaes.models.properties.modular_properties.pure.NIST import NIST

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
#     Retrieved 18th March, 2024
# [4] Chemeo - Chemical properties of Sulfuric Acid,
#     https://www.chemeo.com/cid/24-837-6/Sulfuric-Acid
# [5] CRC Handbook of Chemistry and Physics, 97th Ed., W.M. Haynes
# [6] Journal of Physical and Chemical Reference Data 20, 1157
#     (1991); https:// doi.org/10.1063/1.555899

config_dict = {
    # Specifying components
    "components": {
        "ethylene_oxide": {
            "type": Component,
            "elemental_composition": {"C": 2, "H": 4, "O": 1},
            "dens_mol_liq_comp": Perrys,
            "enth_mol_liq_comp": Perrys,
            "enth_mol_ig_comp": RPP4,
            "pressure_sat_comp": RPP4,
            "phase_equilibrium_form": {("Vap", "Liq"): fugacity},
            "parameter_data": {
                "mw": (44.054e-3, pyunits.kg / pyunits.mol),  # [1] pg. 676
                "pressure_crit": (71.9e5, pyunits.Pa),  # [1] pg. 676
                "temperature_crit": (469, pyunits.K),  # [1] pg. 676
                "dens_mol_liq_comp_coeff": {  # [2] pg. 2-97
                    "eqn_type": 1,
                    "1": (1.836, pyunits.kmol * pyunits.m**-3),
                    "2": (0.26024, None),
                    "3": (469.15, pyunits.K),
                    "4": (0.2696, None),
                },
                "cp_mol_ig_comp_coeff": {  # [1] pg. 677
                    "A": (-7.519e0, pyunits.J / pyunits.mol / pyunits.K),
                    "B": (2.222e-1, pyunits.J / pyunits.mol / pyunits.K**2),
                    "C": (-1.256e-4, pyunits.J / pyunits.mol / pyunits.K**3),
                    "D": (2.592e-8, pyunits.J / pyunits.mol / pyunits.K**4),
                },
                "cp_mol_liq_comp_coeff": {  # [2] pg. 2-173
                    "1": (1.4471e5, pyunits.J / pyunits.kmol / pyunits.K),
                    "2": (-7.5887e2, pyunits.J / pyunits.kmol / pyunits.K**2),
                    "3": (2.8261, pyunits.J / pyunits.kmol / pyunits.K**3),
                    "4": (-3.0640e-3, pyunits.J / pyunits.kmol / pyunits.K**4),
                    "5": (0, pyunits.J / pyunits.kmol / pyunits.K**5),
                },
                "enth_mol_form_liq_comp_ref": (
                    -95.7e3,
                    pyunits.J / pyunits.mol,
                ),  # [3] updated 5/10/24
                "enth_mol_form_vap_comp_ref": (
                    -52.64e3,
                    pyunits.J / pyunits.mol,
                ),  # [3] updated 5/10/24
                "pressure_sat_comp_coeff": {
                    "A": (-6.56234, None),  # [1] pg. 678
                    "B": (0.42696, None),
                    "C": (-1.25638, None),
                    "D": (-3.18133, None),
                },
            },
        },
        "water": {
            "type": Component,
            "elemental_composition": {"H": 2, "O": 1},
            "dens_mol_liq_comp": Perrys,
            "enth_mol_liq_comp": Perrys,
            "enth_mol_ig_comp": RPP4,
            "pressure_sat_comp": RPP4,
            "phase_equilibrium_form": {("Vap", "Liq"): fugacity},
            "parameter_data": {
                "mw": (18.015e-3, pyunits.kg / pyunits.mol),  # [1] pg. 667
                "pressure_crit": (221.2e5, pyunits.Pa),  # [1] pg. 667
                "temperature_crit": (647.3, pyunits.K),  # [1] pg. 667
                "dens_mol_liq_comp_coeff": {  # [2] pg. 2-98
                    "eqn_type": 1,
                    "1": (5.459, pyunits.kmol * pyunits.m**-3),
                    "2": (0.30542, None),
                    "3": (647.13, pyunits.K),
                    "4": (0.081, None),
                },
                "cp_mol_ig_comp_coeff": {  # [1] pg. 668
                    "A": (3.224e1, pyunits.J / pyunits.mol / pyunits.K),
                    "B": (1.924e-3, pyunits.J / pyunits.mol / pyunits.K**2),
                    "C": (1.055e-5, pyunits.J / pyunits.mol / pyunits.K**3),
                    "D": (-3.596e-9, pyunits.J / pyunits.mol / pyunits.K**4),
                },
                "cp_mol_liq_comp_coeff": {  # [2] pg. 2-174
                    "1": (2.7637e5, pyunits.J / pyunits.kmol / pyunits.K),
                    "2": (-2.0901e3, pyunits.J / pyunits.kmol / pyunits.K**2),
                    "3": (8.1250, pyunits.J / pyunits.kmol / pyunits.K**3),
                    "4": (-1.4116e-2, pyunits.J / pyunits.kmol / pyunits.K**4),
                    "5": (9.3701e-6, pyunits.J / pyunits.kmol / pyunits.K**5),
                },
                "enth_mol_form_liq_comp_ref": (
                    -285.830e3,
                    pyunits.J / pyunits.mol,
                ),  # [3] updated 5/10/24
                "enth_mol_form_vap_comp_ref": (
                    -241.826e3,
                    pyunits.J / pyunits.mol,
                ),  # [3] updated 5/10/24
                "pressure_sat_comp_coeff": {
                    "A": (-7.76451, None),  # [1] pg. 669
                    "B": (1.45838, None),
                    "C": (-2.77580, None),
                    "D": (-1.23303, None),
                },
            },
        },
        "sulfuric_acid": {
            "type": Component,
            "elemental_composition": {"H": 2, "S": 1, "O": 4},
            "dens_mol_liq_comp": Perrys,  # fitted to this equation form
            "enth_mol_liq_comp": Perrys,  # fitted to this equation form
            "enth_mol_ig_comp": NIST,
            "pressure_sat_comp": RPP4,  # fitted to this equation form
            "phase_equilibrium_form": {("Vap", "Liq"): fugacity},
            "parameter_data": {
                "mw": (98.08e-3, pyunits.kg / pyunits.mol),  # [4] 5/20/24
                "pressure_crit": (129.4262e5, pyunits.Pa),  # [4] 5/20/2024
                "temperature_crit": (590.76, pyunits.K),  # [4] 5/202/24
                "dens_mol_liq_comp_coeff": {
                    "eqn_type": 2,  # [5] pg. 15-41 regressed from 100% H2SO4 density data
                    "1": (23.669, pyunits.kmol / pyunits.m**3),
                    "2": (-2.5307e-2, pyunits.kmol / pyunits.m**3 / pyunits.K),
                    "3": (3.3523e-5, pyunits.kmol / pyunits.m**3 / pyunits.K**2),
                    "4": (-1.8538e-8, pyunits.kmol / pyunits.m**3 / pyunits.K**3),
                },
                "cp_mol_ig_comp_coeff": {  # [3] valid on 298-1200 K, updated 5/10/2024
                    "A": (47.28924, pyunits.J / pyunits.mol / pyunits.K),
                    "B": (190.3314, pyunits.J / pyunits.mol / pyunits.K / pyunits.kK),
                    "C": (
                        -148.1299,
                        pyunits.J / pyunits.mol / pyunits.K / pyunits.kK**2,
                    ),
                    "D": (
                        43.86631,
                        pyunits.J / pyunits.mol / pyunits.K / pyunits.kK**3,
                    ),
                    "E": (
                        -0.740016,
                        pyunits.J / pyunits.mol / pyunits.K / pyunits.kK**-2,
                    ),
                    "F": (-758.9525, pyunits.kJ / pyunits.mol),
                    "G": (301.2961, pyunits.J / pyunits.mol / pyunits.K),
                    "H": (-735.1288, pyunits.kJ / pyunits.mol),
                },
                "cp_mol_liq_comp_coeff": {  # [6] pg. 1189 regressed from x1=1 and Cp/R for all T values
                    "1": (-202.695, pyunits.J / pyunits.kmol / pyunits.K),
                    "2": (2.9994, pyunits.J / pyunits.kmol / pyunits.K**2),
                    "3": (-9.239e-3, pyunits.J / pyunits.kmol / pyunits.K**3),
                    "4": (1.0113e-5, pyunits.J / pyunits.kmol / pyunits.K**4),
                    "5": (0, pyunits.J / pyunits.kmol / pyunits.K**5),
                },
                "enth_mol_form_liq_comp_ref": (
                    -810.4097e3,
                    pyunits.J / pyunits.mol,
                ),  # [6] Table 4 pg. 1183
                "enth_mol_form_vap_comp_ref": (
                    -735.13e3,
                    pyunits.J / pyunits.mol,
                ),  # [3] updated 5/10/24
                "pressure_sat_comp_coeff": {
                    "A": (-18.122, None),  # [5] data for regression on pg. 6-122
                    "B": (10.596, None),
                    "C": (-18.908, None),
                    "D": (-32.728, None),
                },
            },
        },
        "ethylene_glycol": {
            "type": Component,
            "elemental_composition": {"C": 2, "H": 6, "O": 2},
            "dens_mol_liq_comp": Perrys,
            "enth_mol_liq_comp": Perrys,
            "enth_mol_ig_comp": RPP4,
            "pressure_sat_comp": RPP4,
            "phase_equilibrium_form": {("Vap", "Liq"): fugacity},
            "parameter_data": {
                "mw": (62.069e-3, pyunits.kg / pyunits.mol),  # [1] pg. 676
                "pressure_crit": (77e5, pyunits.Pa),  # [1] pg. 676
                "temperature_crit": (645, pyunits.K),  # [1] pg. 676
                "dens_mol_liq_comp_coeff": {  # [2] pg. 2-95
                    "eqn_type": 1,
                    "1": (1.3151, pyunits.kmol * pyunits.m**-3),
                    "2": (0.25125, None),
                    "3": (719.7, pyunits.K),
                    "4": (0.2187, None),
                },
                "cp_mol_ig_comp_coeff": {  # [1] pg. 677
                    "A": (3.570e1, pyunits.J / pyunits.mol / pyunits.K),
                    "B": (2.483e-1, pyunits.J / pyunits.mol / pyunits.K**2),
                    "C": (-1.497e-4, pyunits.J / pyunits.mol / pyunits.K**3),
                    "D": (3.010e-8, pyunits.J / pyunits.mol / pyunits.K**4),
                },
                "cp_mol_liq_comp_coeff": {  # [2] pg. 2-171
                    "1": (3.5540e4, pyunits.J / pyunits.kmol / pyunits.K),
                    "2": (4.3678e2, pyunits.J / pyunits.kmol / pyunits.K**2),
                    "3": (-1.8486e-1, pyunits.J / pyunits.kmol / pyunits.K**3),
                    "4": (0, pyunits.J / pyunits.kmol / pyunits.K**4),
                    "5": (0, pyunits.J / pyunits.kmol / pyunits.K**5),
                },
                "enth_mol_form_liq_comp_ref": (
                    -460.0e3,
                    pyunits.J / pyunits.mol,
                ),  # [3] updated 5/10/24
                "enth_mol_form_vap_comp_ref": (
                    -394.4e3,
                    pyunits.J / pyunits.mol,
                ),  # [3] updated 5/10/24
                # [1] pg. 678 pressure sat coef values for alternative equation form
                # ln Pvp = A - B/(T + C) with A = 13.6299, B = 6022.18, C = -28.25
                # reformulated for generic property supported form
                # ln Pvp = [(1 - x)^-1 * (A*x + B*x^1.5 + C*x^3 + D*x^6)] * Pc where x = 1 - T/Tc
                "pressure_sat_comp_coeff": {
                    "A": (-16.4022, None),
                    "B": (10.0100, None),
                    "C": (-6.5216, None),
                    "D": (-11.1182, None),
                },
            },
        },
    },
    # Specifying phases
    "phases": {"Liq": {"type": LiquidPhase, "equation_of_state": Ideal}},
    # Set base units of measurement
    "base_units": {
        "time": pyunits.s,
        "length": pyunits.m,
        "mass": pyunits.kg,
        "amount": pyunits.mol,
        "temperature": pyunits.K,
    },
    # Specifying state definition
    "state_definition": FpcTP,
    "state_bounds": {
        "flow_mol_phase_comp": (0, 100, 1000, pyunits.mol / pyunits.s),
        "temperature": (273.15, 298.15, 450, pyunits.K),
        "pressure": (5e4, 1e5, 1e6, pyunits.Pa),
    },
    "pressure_ref": (1e5, pyunits.Pa),
    "temperature_ref": (298.15, pyunits.K),
}
