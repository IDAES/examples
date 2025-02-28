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

# Import Python libraries
import logging

import idaes.logger as idaeslog
from idaes.core.util.initialization import fix_state_vars, revert_state_vars

# Import Pyomo libraries
from pyomo.environ import (
    Param,
    Set,
    Var,
    NonNegativeReals,
    units,
    Expression,
    PositiveReals,
)

# Import IDAES cores
from idaes.core import (
    declare_process_block_class,
    MaterialFlowBasis,
    PhysicalParameterBlock,
    StateBlockData,
    StateBlock,
    MaterialBalanceType,
    EnergyBalanceType,
    Solute,
    Solvent,
    LiquidPhase,
)
from idaes.core.util.model_statistics import degrees_of_freedom

# Some more information about this module
__author__ = "Javal Vyas"

# Set up logger
_log = logging.getLogger(__name__)


@declare_process_block_class("AqPhase")
class AqPhaseData(PhysicalParameterBlock):
    """
    Property Parameter Block Class

    Contains parameters and indexing sets associated with properties for
    aqueous Phase

    """

    def build(self):
        """
        Callable method for Block construction.
        """
        super().build()

        self._state_block_class = AqPhaseStateBlock

        # List of valid phases in property package
        self.Aq = LiquidPhase()

        # Component list - a list of component identifiers
        self.NaCl = Solute()
        self.KNO3 = Solute()
        self.CaSO4 = Solute()
        self.H2O = Solvent()

        # Heat capacity of solvent
        self.cp_mass = Param(
            mutable=True,
            initialize=4182,
            doc="Specific heat capacity of solvent",
            units=units.J / units.kg / units.K,
        )

        self.dens_mass = Param(
            mutable=True,
            initialize=997,
            doc="Density of ethylene dibromide",
            units=units.kg / units.m**3,
        )
        self.temperature_ref = Param(
            within=PositiveReals,
            mutable=True,
            default=298.15,
            doc="Reference temperature",
            units=units.K,
        )

    @classmethod
    def define_metadata(cls, obj):
        obj.add_default_units(
            {
                "time": units.hour,
                "length": units.m,
                "mass": units.g,
                "amount": units.mol,
                "temperature": units.K,
            }
        )


class _AqueousStateBlock(StateBlock):
    """
    This Class contains methods which should be applied to Property Blocks as a
    whole, rather than individual elements of indexed Property Blocks.
    """

    def fix_initialization_states(self):
        fix_state_vars(self)


@declare_process_block_class("AqPhaseStateBlock", block_class=_AqueousStateBlock)
class AqPhaseStateBlockData(StateBlockData):
    """
    An example property package for ideal gas properties with Gibbs energy
    """

    def build(self):
        """
        Callable method for Block construction
        """
        super().build()
        self._make_state_vars()

    def _make_state_vars(self):
        self.flow_vol = Var(
            initialize=1,
            domain=NonNegativeReals,
            doc="Total volumetric flowrate",
            units=units.L / units.hour,
        )

        self.conc_mass_comp = Var(
            self.params.solute_set,
            domain=NonNegativeReals,
            initialize={"NaCl": 0.15, "KNO3": 0.2, "CaSO4": 0.1},
            doc="Component mass concentrations",
            units=units.g / units.L,
        )

        self.pressure = Var(
            domain=NonNegativeReals,
            initialize=1,
            bounds=(0, 5),
            units=units.atm,
            doc="State pressure [atm]",
        )

        self.temperature = Var(
            domain=NonNegativeReals,
            initialize=300,
            bounds=(273, 373),
            units=units.K,
            doc="State temperature [K]",
        )

        def material_flow_expression(self, j):
            if j == "H2O":
                return self.flow_vol * self.params.dens_mass
            else:
                return self.conc_mass_comp[j] * self.flow_vol

        self.material_flow_expression = Expression(
            self.component_list,
            rule=material_flow_expression,
            doc="Material flow terms",
        )

        def enthalpy_flow_expression(self):
            return (
                self.flow_vol
                * self.params.dens_mass
                * self.params.cp_mass
                * (self.temperature - self.params.temperature_ref)
            )

        self.enthalpy_flow_expression = Expression(
            rule=enthalpy_flow_expression, doc="Enthalpy flow term"
        )

    def get_flow_rate(self):
        return self.flow_vol

    def get_material_flow_terms(self, p, j):
        return self.material_flow_expression[j]

    def get_enthalpy_flow_terms(self, p):
        return self.enthalpy_flow_expression

    def default_material_balance_type(self):
        return MaterialBalanceType.componentTotal

    def default_energy_balance_type(self):
        return EnergyBalanceType.enthalpyTotal

    def define_state_vars(self):
        return {
            "flow_vol": self.flow_vol,
            "conc_mass_comp": self.conc_mass_comp,
            "temperature": self.temperature,
            "pressure": self.pressure,
        }

    def get_material_flow_basis(self):
        return MaterialFlowBasis.mass
