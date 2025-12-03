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
import copy

# Import Pyomo units
from pyomo.environ import units as pyunits, Var, value

# Import IDAES cores
from idaes.core import LiquidPhase, VaporPhase, Component, PhaseType
import idaes.logger as idaeslog

from idaes.core.util.math import smooth_max
from idaes.core.util.constants import Constants

from idaes.models.properties.modular_properties.state_definitions.FpTPxpc import FpTPxpc
from idaes.models.properties.modular_properties.eos.ideal import Ideal
from idaes.models.properties.modular_properties.phase_equil import SmoothVLE
from idaes.models.properties.modular_properties.phase_equil.bubble_dew import (
    IdealBubbleDew,
)
from idaes.core.util.misc import set_param_from_config
from idaes.models.properties.modular_properties.phase_equil.forms import fugacity
from idaes.models.properties.modular_properties.pure import Perrys
from idaes.models.properties.modular_properties.pure import RPP5

# Set up logger
_log = idaeslog.getLogger(__name__)
R = value(Constants.gas_constant)
# ---------------------------------------------------------------------
# Configuration dictionary for an ideal Benzene-Toluene system

# Data Sources:
# [1] The Properties of Gases and Liquids (1987)
#     4th edition, Chemical Engineering Series - Robert C. Reid
# [2] Perry's Chemical Engineers' Handbook 7th Ed.
# [3] Engineering Toolbox, https://www.engineeringtoolbox.com
#     Retrieved 1st December, 2019
# [4] Properties of Gases and Liquids (2000) 5th edition
#     Poling, B. E. and Prausnitz, J. M. and O'Connell, J. P.
#     McGraw Hill LLC
#     Might be the second printing---copyright was from 2001

# Legacy values from [1]
cp_ig_data = {
    ("benzene", 0): -3.392e1 / R,
    ("benzene", 1): 4.739e-1 / R,
    ("benzene", 2): -3.017e-4 / R,
    ("benzene", 3): 7.130e-8 / R,
    ("benzene", 4): 0,
    ("toluene", 0): -2.435e1 / R,
    ("toluene", 1): 5.125e-1 / R,
    ("toluene", 2): -2.765e-4 / R,
    ("toluene", 3): 4.911e-8 / R,
    ("toluene", 4): 0,
    ("hydrogen", 0): 2.714e1 / R,
    ("hydrogen", 1): 9.274e-3 / R,
    ("hydrogen", 2): -1.381e-5 / R,
    ("hydrogen", 3): 7.645e-9 / R,
    ("hydrogen", 4): 0,
    ("methane", 0): 1.925e1 / R,
    ("methane", 1): 5.213e-2 / R,
    ("methane", 2): 1.197e-5 / R,
    ("methane", 3): -1.132e-8 / R,
    ("methane", 4): 0,
}


class PerrysSafe(object):
    class dens_mol_liq_comp:
        @staticmethod
        def build_parameters(cobj):
            cobj.dens_mol_liq_comp_coeff_1 = Var(
                doc="Parameter 1 for liquid phase molar density",
                units=pyunits.kmol * pyunits.m**-3,
            )
            set_param_from_config(cobj, param="dens_mol_liq_comp_coeff", index="1")

            cobj.dens_mol_liq_comp_coeff_2 = Var(
                doc="Parameter 2 for liquid phase molar density",
                units=pyunits.dimensionless,
            )
            set_param_from_config(cobj, param="dens_mol_liq_comp_coeff", index="2")

            cobj.dens_mol_liq_comp_coeff_3 = Var(
                doc="Parameter 3 for liquid phase molar density", units=pyunits.K
            )
            set_param_from_config(cobj, param="dens_mol_liq_comp_coeff", index="3")

            cobj.dens_mol_liq_comp_coeff_4 = Var(
                doc="Parameter 4 for liquid phase molar density",
                units=pyunits.dimensionless,
            )
            set_param_from_config(cobj, param="dens_mol_liq_comp_coeff", index="4")

        @staticmethod
        def return_expression(b, cobj, T):
            # pg. 2-98
            T = pyunits.convert(T, to_units=pyunits.K)

            rho = cobj.dens_mol_liq_comp_coeff_1 / cobj.dens_mol_liq_comp_coeff_2 ** (
                1
                + smooth_max(1 - T / cobj.dens_mol_liq_comp_coeff_3, 0)
                ** cobj.dens_mol_liq_comp_coeff_4
            )

            units = b.params.get_metadata().derived_units

            return pyunits.convert(rho, units.DENSITY_MOLE)


thermo_config = {
    # Specifying components
    "components": {
        "benzene": {
            "type": Component,
            "elemental_composition": {"C": 6, "H": 6},
            "dens_mol_liq_comp": PerrysSafe,
            "enth_mol_liq_comp": Perrys,
            "enth_mol_ig_comp": RPP5,
            "pressure_sat_comp": RPP5,
            "phase_equilibrium_form": {("Vap", "Liq"): fugacity},
            "parameter_data": {
                "mw": (78.1136e-3, pyunits.kg / pyunits.mol),  # [1]
                "pressure_crit": (48.9e5, pyunits.Pa),  # [1]
                "temperature_crit": (562.2, pyunits.K),  # [1]
                "dens_mol_liq_comp_coeff": {
                    "eqn_type": 1,
                    "1": (1.0162, pyunits.kmol * pyunits.m**-3),  # [2] pg. 2-98
                    "2": (0.2655, None),
                    "3": (562.16, pyunits.K),
                    "4": (0.28212, None),
                },
                "cp_mol_ig_comp_coeff": {
                    f"a{k}": (cp_ig_data["benzene", k], pyunits.K**-k) for k in range(5)
                },
                "cp_mol_liq_comp_coeff": {
                    "1": (1.29e2 * 1e3, pyunits.J / pyunits.kmol / pyunits.K),  # [2]
                    "2": (-1.7e-1 * 1e3, pyunits.J / pyunits.kmol / pyunits.K**2),
                    "3": (6.48e-4 * 1e3, pyunits.J / pyunits.kmol / pyunits.K**3),
                    "4": (0, pyunits.J / pyunits.kmol / pyunits.K**4),
                    "5": (0, pyunits.J / pyunits.kmol / pyunits.K**5),
                },
                "enth_mol_form_liq_comp_ref": (49.0e3, pyunits.J / pyunits.mol),  # [3]
                "enth_mol_form_vap_comp_ref": (82.9e3, pyunits.J / pyunits.mol),  # [3]
                "pressure_sat_comp_coeff": {
                    "A": (4.202, pyunits.dimensionless),  # [1]
                    "B": (1322, pyunits.K),
                    "C": (-38.56 + 273.15, pyunits.K),
                },
            },
        },
        "toluene": {
            "type": Component,
            "elemental_composition": {"C": 7, "H": 8},
            "dens_mol_liq_comp": PerrysSafe,
            "enth_mol_liq_comp": Perrys,
            "enth_mol_ig_comp": RPP5,
            "pressure_sat_comp": RPP5,
            "phase_equilibrium_form": {("Vap", "Liq"): fugacity},
            "parameter_data": {
                "mw": (92.1405e-3, pyunits.kg / pyunits.mol),  # [1]
                "pressure_crit": (41e5, pyunits.Pa),  # [1]
                "temperature_crit": (591.8, pyunits.K),  # [1]
                "dens_mol_liq_comp_coeff": {
                    "eqn_type": 1,
                    "1": (0.8488, pyunits.kmol * pyunits.m**-3),  # [2] pg. 2-98
                    "2": (0.26655, None),
                    "3": (591.8, pyunits.K),
                    "4": (0.2878, None),
                },
                "cp_mol_ig_comp_coeff": {
                    f"a{k}": (cp_ig_data["toluene", k], pyunits.K**-k) for k in range(5)
                },
                "cp_mol_liq_comp_coeff": {
                    "1": (1.40e2 * 1e3, pyunits.J / pyunits.kmol / pyunits.K),  # [2]
                    "2": (-1.52e-1 * 1e3, pyunits.J / pyunits.kmol / pyunits.K**2),
                    "3": (6.95e-4 * 1e3, pyunits.J / pyunits.kmol / pyunits.K**3),
                    "4": (0, pyunits.J / pyunits.kmol / pyunits.K**4),
                    "5": (0, pyunits.J / pyunits.kmol / pyunits.K**5),
                },
                "enth_mol_form_liq_comp_ref": (12.0e3, pyunits.J / pyunits.mol),  # [3]
                "enth_mol_form_vap_comp_ref": (50.1e3, pyunits.J / pyunits.mol),  # [3]
                "pressure_sat_comp_coeff": {
                    "A": (4.216, pyunits.dimensionless),  # [1]
                    "B": (1435, pyunits.K),
                    "C": (-43.33 + 273.15, pyunits.K),
                },
            },
        },
        "hydrogen": {
            "type": Component,
            "valid_phase_types": [PhaseType.vaporPhase],
            "elemental_composition": {"H": 2},
            "enth_mol_ig_comp": RPP5,
            "pressure_sat_comp": RPP5,
            "parameter_data": {
                "mw": (2.016e-3, pyunits.kg / pyunits.mol),  # [1]
                "pressure_crit": (12.9e5, pyunits.Pa),  # [1]
                "temperature_crit": (33.0, pyunits.K),  # [1]
                # "dens_mol_liq_comp_coeff": {
                #     "eqn_type": 1,
                #     "1": (5.414, pyunits.kmol * pyunits.m ** -3),  # [2] pg. 2-98
                #     "2": (0.34893, None),
                #     "3": (33.19, pyunits.K),
                #     "4": (0.2706, None),
                # },
                "cp_mol_ig_comp_coeff": {
                    f"a{k}": (cp_ig_data["hydrogen", k], pyunits.K**-k)
                    for k in range(5)
                },
                # "cp_mol_liq_comp_coeff": {
                #     "1": (0, pyunits.J / pyunits.kmol / pyunits.K),  # [2]
                #     "2": (0, pyunits.J / pyunits.kmol / pyunits.K ** 2),
                #     "3": (0, pyunits.J / pyunits.kmol / pyunits.K ** 3),
                #     "4": (0, pyunits.J / pyunits.kmol / pyunits.K ** 4),
                #     "5": (0, pyunits.J / pyunits.kmol / pyunits.K ** 5),
                # },
                # "enth_mol_form_liq_comp_ref": (0.0, pyunits.J / pyunits.mol),  # [3]
                "enth_mol_form_vap_comp_ref": (0.0, pyunits.J / pyunits.mol),  # [3]
                "pressure_sat_comp_coeff": {
                    "A": (3.543, pyunits.dimensionless),  # [1]
                    "B": (99.40, pyunits.K),
                    "C": (7.726 + 273.15, pyunits.K),
                },
            },
        },
        "methane": {
            "type": Component,
            "valid_phase_types": [PhaseType.vaporPhase],
            "elemental_composition": {"C": 1, "H": 4},
            "enth_mol_ig_comp": RPP5,
            "pressure_sat_comp": RPP5,
            "parameter_data": {
                "mw": (16.043e-3, pyunits.kg / pyunits.mol),  # [1]
                "pressure_crit": (4.599e6, pyunits.Pa),  # [1]
                "temperature_crit": (190.564, pyunits.K),  # [1]
                # "dens_mol_liq_comp_coeff": {
                #     "eqn_type": 1,
                #     "1": (2.9214, pyunits.kmol * pyunits.m ** -3),  # [2] pg. 2-98
                #     "2": (0.28976, None),
                #     "3": (190.56, pyunits.K),
                #     "4": (0.28881, None),
                # },
                "cp_mol_ig_comp_coeff": {
                    f"a{k}": (cp_ig_data["methane", k], pyunits.K**-k) for k in range(5)
                },
                # "cp_mol_liq_comp_coeff": {
                #     "1": (0, pyunits.J / pyunits.kmol / pyunits.K),  # [2]
                #     "2": (0, pyunits.J / pyunits.kmol / pyunits.K ** 2),
                #     "3": (0, pyunits.J / pyunits.kmol / pyunits.K ** 3),
                #     "4": (0, pyunits.J / pyunits.kmol / pyunits.K ** 4),
                #     "5": (0, pyunits.J / pyunits.kmol / pyunits.K ** 5),
                # },
                # "enth_mol_form_liq_comp_ref": (-74.52e3, pyunits.J / pyunits.mol),  # [3]
                "enth_mol_form_vap_comp_ref": (
                    -74.52e3,
                    pyunits.J / pyunits.mol,
                ),  # [3]
                "pressure_sat_comp_coeff": {
                    "A": (3.990, pyunits.dimensionless),  # [1]
                    "B": (443.0, pyunits.K),
                    "C": (-0.49 + 273.15, pyunits.K),
                },
            },
        },
    },
    # Specifying phases
    "phases": {
        "Liq": {"type": LiquidPhase, "equation_of_state": Ideal},
        "Vap": {"type": VaporPhase, "equation_of_state": Ideal},
    },
    #
    # # Set base units of measurement
    "base_units": {
        "time": pyunits.s,
        "length": pyunits.m,
        "mass": pyunits.kg,
        "amount": pyunits.mol,
        "temperature": pyunits.K,
    },
    # # Specifying state definition
    "state_definition": FpTPxpc,
    "state_bounds": {
        "flow_mol_phase": (1e-12, 0.5, 100, pyunits.mol / pyunits.s),
        "temperature": (273.15, 298.15, 1500, pyunits.K),
        "pressure": (100000, 101325, 1000000, pyunits.Pa),
    },
    "pressure_ref": (101325, pyunits.Pa),
    "temperature_ref": (298.15, pyunits.K),
    # Defining phase equilibria
    "phases_in_equilibrium": [("Vap", "Liq")],
    "phase_equilibrium_state": {("Vap", "Liq"): SmoothVLE},
    "bubble_dew_method": IdealBubbleDew,  # LogBubbleDew,
    "include_enthalpy_of_formation": True,
}

thermo_config_vapor = copy.deepcopy(thermo_config)
thermo_config_vapor["phases"].pop("Liq")
thermo_config_vapor.pop("phases_in_equilibrium")
thermo_config_vapor.pop("phase_equilibrium_state")
thermo_config_vapor.pop("bubble_dew_method")
