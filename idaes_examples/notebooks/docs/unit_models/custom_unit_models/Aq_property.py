# Changes the divide behavior to not do integer division
from __future__ import division

# Import Python libraries
import logging

import idaes.logger as idaeslog
from idaes.core.util.initialization import fix_state_vars, revert_state_vars

# Import Pyomo libraries
from pyomo.environ import (
    Param,
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
class PhysicalParameterData(PhysicalParameterBlock):
    """
    Property Parameter Block Class

    Contains parameters and indexing sets associated with properties for
    liquid Phase

    """

    def build(self):
        """
        Callable method for Block construction.
        """
        super(PhysicalParameterData, self).build()

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
        obj.add_properties(
            {
                "flow_mol": {"method": None, "units": "kmol/s"},
                "pressure": {"method": None, "units": "MPa"},
                "temperature": {"method": None, "units": "K"},
            }
        )

        obj.add_default_units(
            {
                "time": units.s,
                "length": units.m,
                "mass": units.kg,
                "amount": units.mol,
                "temperature": units.K,
            }
        )


class _StateBlock(StateBlock):
    """
    This Class contains methods which should be applied to Property Blocks as a
    whole, rather than individual elements of indexed Property Blocks.
    """

    def initialize(
        self,
        state_args=None,
        state_vars_fixed=False,
        hold_state=False,
        outlvl=idaeslog.NOTSET,
        solver=None,
        optarg=None,
    ):
        """
        Initialization routine for property package.

        Keyword Arguments:
            state_args : Dictionary with initial guesses for the state vars
                         chosen. Note that if this method is triggered
                         through the control volume, and if initial guesses
                         were not provided at the unit model level, the
                         control volume passes the inlet values as initial
                         guess.The keys for the state_args dictionary are:
            flow_mol_comp : value at which to initialize component flows (default=None)
            pressure : value at which to initialize pressure (default=None)
            temperature : value at which to initialize temperature (default=None)
            outlvl : sets output level of initialization routine
            state_vars_fixed: Flag to denote if state vars have already been fixed.
                              True - states have already been fixed and
                              initialization does not need to worry
                              about fixing and unfixing variables.
                              False - states have not been fixed. The state
                              block will deal with fixing/unfixing.
            optarg : solver options dictionary object (default=None, use
                     default solver options)
            solver : str indicating which solver to use during
                     initialization (default = None, use default solver)
            hold_state : flag indicating whether the initialization routine
                         should unfix any state variables fixed during
                         initialization (default=False).
                         True - states variables are not unfixed, and
                         a dict of returned containing flags for
                         which states were fixed during initialization.
                         False - state variables are unfixed after
                         initialization by calling the
                         release_state method

        Returns:
            If hold_states is True, returns a dict containing flags for
            which states were fixed during initialization.
        """
        init_log = idaeslog.getInitLogger(self.name, outlvl, tag="properties")

        if state_vars_fixed is False:
            # Fix state variables if not already fixed
            flags = fix_state_vars(self, state_args)

        else:
            # Check when the state vars are fixed already result in dof 0
            for k in self.keys():
                if degrees_of_freedom(self[k]) != 0:
                    raise Exception(
                        "State vars fixed but degrees of freedom "
                        "for state block is not zero during "
                        "initialization."
                    )

        if state_vars_fixed is False:
            if hold_state is True:
                return flags
            else:
                self.release_state(flags)

        init_log.info("Initialization Complete.")

    def release_state(self, flags, outlvl=idaeslog.NOTSET):
        """
        Method to release state variables fixed during initialization.

        Keyword Arguments:
            flags : dict containing information of which state variables
                    were fixed during initialization, and should now be
                    unfixed. This dict is returned by initialize if
                    hold_state=True.
            outlvl : sets output level of logging
        """
        init_log = idaeslog.getInitLogger(self.name, outlvl, tag="properties")

        if flags is None:
            return
        # Unfix state variables
        revert_state_vars(self, flags)
        init_log.info("State Released.")


@declare_process_block_class("AqPhaseStateBlock", block_class=_StateBlock)
class AqPhaseStateBlockData(StateBlockData):
    """
    An example property package for ideal gas properties with Gibbs energy
    """

    def build(self):
        """
        Callable method for Block construction
        """
        super(AqPhaseStateBlockData, self).build()
        self._make_state_vars()

    def _make_state_vars(self):
        self.flow_vol = Var(
            initialize=1,
            domain=NonNegativeReals,
            doc="Total volumetric flowrate",
            units=units.ml / units.min,
        )

        salts_conc = {"NaCl": 0.15, "KNO3": 0.2, "CaSO4": 0.1}
        self.conc_mass_comp = Var(
            salts_conc.keys(),
            domain=NonNegativeReals,
            initialize=1,
            doc="Component mass concentrations",
            units=units.g / units.kg,
        )
        self.pressure = Var(
            domain=NonNegativeReals,
            initialize=1,
            bounds=(1, 5),
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
                return self.flow_vol * self.conc_mass_comp[j]

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

    def get_mass_comp(self, j):
        return self.conc_mass_comp[j]

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
