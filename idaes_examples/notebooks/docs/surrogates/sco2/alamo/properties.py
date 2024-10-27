##############################################################################
# Institute for the Design of Advanced Energy Systems Process Systems
# Engineering Framework (IDAES PSE Framework) Copyright (c) 2018-2019, by the
# software owners: The Regents of the University of California, through
# Lawrence Berkeley National Laboratory,  National Technology & Engineering
# Solutions of Sandia, LLC, Carnegie Mellon University, West Virginia
# University Research Corporation, et al. All rights reserved.
#
# Please see the files COPYRIGHT.txt and LICENSE.txt for full copyright and
# license information, respectively. Both files are also available online
# at the URL "https://github.com/IDAES/idaes-pse".
##############################################################################
"""
Surrogate property package for SCO2 cycle.

Valid Pressure Range = 7.49 MPa to 35 MPa
Valid Temperature Range = 306.25 K to 1000 K

"""

# Import Python libraries
import logging

# Import Pyomo libraries
from pyomo.environ import (
    Constraint,
    Param,
    Reals,
    Set,
    value,
    Var,
    NonNegativeReals,
    units,
)
from pyomo.opt import SolverFactory, TerminationCondition

# Import IDAES cores
from idaes.core import (
    declare_process_block_class,
    PhysicalParameterBlock,
    StateBlockData,
    StateBlock,
    MaterialBalanceType,
    EnergyBalanceType,
    LiquidPhase,
    Component,
)
from idaes.core.util.initialization import solve_indexed_blocks
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.core.util.misc import extract_data
from idaes.core.solvers import get_solver
from pyomo.util.check_units import assert_units_consistent
from idaes.core.surrogate.surrogate_block import SurrogateBlock
from idaes.core.surrogate.alamopy import AlamoSurrogate

from pyomo.util.model_size import build_model_size_report

# Some more information about this module
__author__ = "Javal Vyas"


# Set up logger
_log = logging.getLogger(__name__)


@declare_process_block_class("SCO2ParameterBlock")
class PhysicalParameterData(PhysicalParameterBlock):
    """
    Property Parameter Block Class

    Contains parameters and indexing sets associated with properties for
    supercritical CO2.

    """

    def build(self):
        """
        Callable method for Block construction.
        """
        super(PhysicalParameterData, self).build()

        self._state_block_class = SCO2StateBlock

        # List of valid phases in property package
        self.Liq = LiquidPhase()

        # Component list - a list of component identifiers
        self.CO2 = Component()

    @classmethod
    def define_metadata(cls, obj):
        obj.add_properties(
            {
                "flow_mol": {"method": None, "units": "kmol/s"},
                "pressure": {"method": None, "units": "MPa"},
                "temperature": {"method": None, "units": "K"},
                "enth_mol": {"method": None, "units": "kJ/kmol"},
                "entr_mol": {"method": None, "units": "kJ/kmol/K"},
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
        blk,
        state_args=None,
        hold_state=False,
        outlvl=1,
        state_vars_fixed=False,
        solver="ipopt",
        optarg={"tol": 1e-8},
    ):
        """
        Initialisation routine for property package.

        Keyword Arguments:
            flow_mol : value at which to initialize component flows
                             (default=None)
            pressure : value at which to initialize pressure (default=None)
            temperature : value at which to initialize temperature
                          (default=None)
            outlvl : sets output level of initialisation routine

                     * 0 = no output (default)
                     * 1 = return solver state for each step in routine
                     * 2 = include solver output information (tee=True)
            state_vars_fixed: Flag to denote if state vars have already been
                              fixed.
                              - True - states have already been fixed by the
                                       control volume 1D. Control volume 0D
                                       does not fix the state vars, so will
                                       be False if this state block is used
                                       with 0D blocks.
                             - False - states have not been fixed. The state
                                       block will deal with fixing/unfixing.
            optarg : solver options dictionary object (default=None)
            solver : str indicating which solver to use during
                     initialization (default = 'ipopt')
            hold_state : flag indicating whether the initialization routine
                         should unfix any state variables fixed during
                         initialization (default=False).
                         - True - states variables are not unfixed, and
                                 a dict of returned containing flags for
                                 which states were fixed during
                                 initialization.
                        - False - state variables are unfixed after
                                 initialization by calling the
                                 release_state method

        Returns:
            If hold_states is True, returns a dict containing flags for
            which states were fixed during initialization.
        """
        if state_vars_fixed is False:
            # Fix state variables if not already fixed
            Fcflag = {}
            Pflag = {}
            Tflag = {}

            for k in blk.keys():
                if blk[k].flow_mol.fixed is True:
                    Fcflag[k] = True
                else:
                    Fcflag[k] = False
                    if state_args is None:
                        blk[k].flow_mol.fix()
                    else:
                        blk[k].flow_mol.fix(state_args["flow_mol"])

                if blk[k].pressure.fixed is True:
                    Pflag[k] = True
                else:
                    Pflag[k] = False
                    if state_args is None:
                        blk[k].pressure.fix()
                    else:
                        blk[k].pressure.fix(state_args["pressure"])

                if blk[k].temperature.fixed is True:
                    Tflag[k] = True
                else:
                    Tflag[k] = False
                    if state_args is None:
                        blk[k].temperature.fix()
                    else:
                        blk[k].temperature.fix(state_args["temperature"])

            # If input block, return flags, else release state
            flags = {"Fcflag": Fcflag, "Pflag": Pflag, "Tflag": Tflag}

        else:
            # Check when the state vars are fixed already result in dof 0
            for k in blk.keys():
                if degrees_of_freedom(blk[k]) != 0:
                    raise Exception(
                        "State vars fixed but degrees of freedom "
                        "for state block is not zero during "
                        "initialization."
                    )

        if state_vars_fixed is False:
            if hold_state is True:
                return flags
            else:
                blk.release_state(flags)

    def release_state(blk, flags, outlvl=0):
        """
        Method to release state variables fixed during initialisation.

        Keyword Arguments:
            flags : dict containing information of which state variables
                    were fixed during initialization, and should now be
                    unfixed. This dict is returned by initialize if
                    hold_state=True.
            outlvl : sets output level of of logging
        """
        if flags is None:
            return

        # Unfix state variables
        for k in blk.keys():
            if flags["Fcflag"][k] is False:
                blk[k].flow_mol.unfix()
            if flags["Pflag"][k] is False:
                blk[k].pressure.unfix()
            if flags["Tflag"][k] is False:
                blk[k].temperature.unfix()

        if outlvl > 0:
            if outlvl > 0:
                _log.info("{} State Released.".format(blk.name))


@declare_process_block_class("SCO2StateBlock", block_class=_StateBlock)
class SCO2StateBlockData(StateBlockData):
    """
    An example property package for ideal gas properties with Gibbs energy
    """

    def build(self):
        """
        Callable method for Block construction
        """
        super(SCO2StateBlockData, self).build()
        self._make_state_vars()

    def _make_state_vars(self):
        # Create state variables

        self.flow_mol = Var(
            domain=NonNegativeReals,
            initialize=1.0,
            units=units.kmol / units.s,
            doc="Total molar flowrate [kmol/s]",
        )

        self.pressure = Var(
            domain=NonNegativeReals,
            initialize=8,
            bounds=(7.38, 40),
            units=units.MPa,
            doc="State pressure [MPa]",
        )

        self.temperature = Var(
            domain=NonNegativeReals,
            initialize=350,
            bounds=(304.2, 760 + 273.15),
            units=units.K,
            doc="State temperature [K]",
        )

        self.entr_mol = Var(
            domain=Reals,
            initialize=10,
            units=units.kJ / units.kmol / units.K,
            doc="Entropy [kJ/ kmol / K]",
        )

        self.enth_mol = Var(
            domain=Reals,
            initialize=1,
            units=units.kJ / units.kmol,
            doc="Enthalpy [kJ/ kmol]",
        )

        inputs = [self.pressure, self.temperature]
        outputs = [self.enth_mol, self.entr_mol]
        self.alamo_surrogate = AlamoSurrogate.load_from_file("alamo_surrogate.json")
        self.surrogate_enth = SurrogateBlock()
        self.surrogate_enth.build_model(
            self.alamo_surrogate,
            input_vars=inputs,
            output_vars=outputs,
        )

    def get_material_flow_terms(self, p, j):
        return self.flow_mol

    def get_enthalpy_flow_terms(self, p):
        return self.flow_mol * self.enth_mol

    def default_material_balance_type(self):
        return MaterialBalanceType.componentTotal

    def default_energy_balance_type(self):
        return EnergyBalanceType.enthalpyTotal

    def define_state_vars(self):
        return {
            "flow_mol": self.flow_mol,
            "temperature": self.temperature,
            "pressure": self.pressure,
        }

    def model_check(blk):
        """
        Model checks for property block
        """
        # Check temperature bounds
        if value(blk.temperature) < blk.temperature.lb:
            _log.error("{} Temperature set below lower bound.".format(blk.name))
        if value(blk.temperature) > blk.temperature.ub:
            _log.error("{} Temperature set above upper bound.".format(blk.name))

        # Check pressure bounds
        if value(blk.pressure) < blk.pressure.lb:
            _log.error("{} Pressure set below lower bound.".format(blk.name))
        if value(blk.pressure) > blk.pressure.ub:
            _log.error("{} Pressure set above upper bound.".format(blk.name))
