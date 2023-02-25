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
Example of a thermophysical property package for the hydrodealkylation of
toluene to form benzene, along with the side reaction to form diphenyl.

This package assumes a single, ideal vapor phase and contains calculations
for molar density, heat capacity and specific enthalpy.
"""

# Import Pyomo libraries
from pyomo.environ import (
    Constraint, Expression, Reference, Param, units as pyunits, Var)

# Import IDAES cores
from idaes.core import (declare_process_block_class,
                        MaterialFlowBasis,
                        PhysicalParameterBlock,
                        StateBlockData,
                        StateBlock,
                        MaterialBalanceType,
                        EnergyBalanceType,
                        Component,
                        VaporPhase)
from idaes.core.solvers import get_solver
from idaes.core.util.initialization import (fix_state_vars,
                                            revert_state_vars,
                                            solve_indexed_blocks)
from idaes.core.util.model_statistics import degrees_of_freedom, \
                                             number_unfixed_variables
from idaes.core.util.constants import Constants as const
import idaes.logger as idaeslog

# Set up logger
_log = idaeslog.getLogger(__name__)


@declare_process_block_class("HDAParameterBlock")
class HDAParameterData(PhysicalParameterBlock):
    CONFIG = PhysicalParameterBlock.CONFIG()

    def build(self):
        '''
        Callable method for Block construction.
        '''
        super(HDAParameterData, self).build()

        self._state_block_class = HDAStateBlock

        self.benzene = Component()
        self.toluene = Component()
        self.methane = Component()
        self.hydrogen = Component()
        self.diphenyl = Component()

        self.Vap = VaporPhase()

        # Thermodynamic reference state
        self.pressure_ref = Param(mutable=True,
                                  default=101325,
                                  units=pyunits.Pa,
                                  doc='Reference pressure')
        self.temperature_ref = Param(mutable=True,
                                     default=298.15,
                                     units=pyunits.K,
                                     doc='Reference temperature')

        # Source: The Properties of Gases and Liquids (1987)
        # 4th edition, Chemical Engineering Series - Robert C. Reid
        self.mw_comp = Param(self.component_list,
                             mutable=False,
                             initialize={'benzene': 78.1136E-3,
                                         'toluene': 92.1405E-3,
                                         'hydrogen': 2.016e-3,
                                         'methane': 16.043e-3,
                                         'diphenyl': 154.212e-4},
                             units=pyunits.kg/pyunits.mol,
                             doc="Molecular weight")

        # Constants for specific heat capacity, enthalpy
        # Sources: The Properties of Gases and Liquids (1987)
        #         4th edition, Chemical Engineering Series - Robert C. Reid
        self.cp_mol_ig_comp_coeff_A = Var(
            self.component_list,
            initialize={"benzene": -3.392E1,
                        "toluene": -2.435E1,
                        "hydrogen": 2.714e1,
                        "methane": 1.925e1,
                        "diphenyl": -9.707e1},
            units=pyunits.J/pyunits.mol/pyunits.K,
            doc="Parameter A for ideal gas molar heat capacity")
        self.cp_mol_ig_comp_coeff_A.fix()

        self.cp_mol_ig_comp_coeff_B = Var(
            self.component_list,
            initialize={"benzene": 4.739E-1,
                        "toluene": 5.125E-1,
                        "hydrogen": 9.274e-3,
                        "methane": 5.213e-2,
                        "diphenyl": 1.106e0},
            units=pyunits.J/pyunits.mol/pyunits.K**2,
            doc="Parameter B for ideal gas molar heat capacity")
        self.cp_mol_ig_comp_coeff_B.fix()

        self.cp_mol_ig_comp_coeff_C = Var(
            self.component_list,
            initialize={"benzene": -3.017E-4,
                        "toluene": -2.765E-4,
                        "hydrogen": -1.381e-5,
                        "methane": -8.855e-4,
                        "diphenyl": -8.855e-4},
            units=pyunits.J/pyunits.mol/pyunits.K**3,
            doc="Parameter C for ideal gas molar heat capacity")
        self.cp_mol_ig_comp_coeff_C.fix()

        self.cp_mol_ig_comp_coeff_D = Var(
            self.component_list,
            initialize={"benzene": 7.130E-8,
                        "toluene": 4.911E-8,
                        "hydrogen": 7.645e-9,
                        "methane": -1.132e-8,
                        "diphenyl": 2.790e-7},
            units=pyunits.J/pyunits.mol/pyunits.K**4,
            doc="Parameter D for ideal gas molar heat capacity")
        self.cp_mol_ig_comp_coeff_D.fix()

        # Source: NIST Webook, https://webbook.nist.gov/, retrieved 11/3/2020
        self.enth_mol_form_vap_comp_ref = Var(
            self.component_list,
            initialize={"benzene": -82.9e3,
                        "toluene": -50.1e3,
                        "hydrogen": 0,
                        "methane": -75e3,
                        "diphenyl": -180e3},
            units=pyunits.J/pyunits.mol,
            doc="Standard heat of formation at reference state")
        self.enth_mol_form_vap_comp_ref.fix()

    @classmethod
    def define_metadata(cls, obj):
        """Define properties supported and units."""
        obj.add_properties(
            {'flow_mol': {'method': None},
             'mole_frac_comp': {'method': None},
             'temperature': {'method': None},
             'pressure': {'method': None},
             'mw_comp': {'method': None},
             'dens_mol': {'method': None},
             'enth_mol': {'method': '_enth_mol'}})

        obj.add_default_units({'time': pyunits.s,
                               'length': pyunits.m,
                               'mass': pyunits.kg,
                               'amount': pyunits.mol,
                               'temperature': pyunits.K})


class _HDAStateBlock(StateBlock):
    """
    This Class contains methods which should be applied to Property Blocks as a
    whole, rather than individual elements of indexed Property Blocks.
    """

    def initialize(blk, state_args={}, state_vars_fixed=False,
                   hold_state=False, outlvl=idaeslog.NOTSET,
                   solver=None, optarg=None):
        """
        Initialization routine for property package.
        Keyword Arguments:
            state_args : Dictionary with initial guesses for the state vars
                         chosen. The keys for the state_args dictionary are:

                         flow_mol : value at which to initialize flow rate
                         mole_frac_comp : dict of values to use when
                                          initializing mole fractions
                         pressure : value at which to initialize pressure
                         temperature : value at which to initialize temperature
            outlvl : sets logger output level for initialization routine
            optarg : solver options dictionary object (default=None)
            state_vars_fixed: Flag to denote if state vars have already been
                              fixed.
                              - True - states have already been fixed by the
                                       control volume 1D. Control volume 0D
                                       does not fix the state vars, so will
                                       be False if this state block is used
                                       with 0D blocks.
                             - False - states have not been fixed. The state
                                       block will deal with fixing/unfixing.
            solver : str indicating whcih solver to use during
                     initialization (default = None, use default solver)
            hold_state : flag indicating whether the initialization routine
                         should unfix any state variables fixed during
                         initialization (default=False).
                         - True - states varaibles are not unfixed, and
                                 a dict of returned containing flags for
                                 which states were fixed during
                                 initialization.
                        - False - state variables are unfixed after
                                 initialization by calling the
                                 relase_state method
        Returns:
            If hold_states is True, returns a dict containing flags for
            which states were fixed during initialization.
        """

        init_log = idaeslog.getInitLogger(blk.name, outlvl, tag="properties")
        solve_log = idaeslog.getSolveLogger(blk.name, outlvl, tag="properties")

        # Fix state variables if not already fixed
        if state_vars_fixed is False:
            flags = fix_state_vars(blk, state_args)

        else:
            pass

        # Deactivate sum of mole fractions constraint
        for k in blk.keys():
            if blk[k].config.defined_state is False:
                blk[k].mole_fraction_constraint.deactivate()

        # Check that degrees of freedom are zero after fixing state vars
        for k in blk.keys():
            if degrees_of_freedom(blk[k]) != 0:
                raise Exception("State vars fixed but degrees of freedom "
                                "for state block is not zero during "
                                "initialization.")

        # Set solver options
        if optarg is None:
            optarg = {"tol": 1e-8}

        opt = get_solver(solver, optarg)

        # ---------------------------------------------------------------------
        # Initialize property calculations

        # Check that there is something to solve for
        free_vars = 0
        for k in blk.keys():
            free_vars += number_unfixed_variables(blk[k])
        if free_vars > 0:
            # If there are free variables, call the solver to initialize
            try:
                with idaeslog.solver_log(solve_log, idaeslog.DEBUG) as slc:
                    res = solve_indexed_blocks(opt, [blk], tee=slc.tee)
            except:
                res = None
        else:
            res = None

        init_log.info("Properties Initialized {}.".format(
            idaeslog.condition(res)))

        # ---------------------------------------------------------------------
        # Return state to initial conditions
        if state_vars_fixed is False:
            if hold_state is True:
                return flags
            else:
                blk.release_state(flags)

        init_log.info("Initialization Complete")

    def release_state(blk, flags, outlvl=idaeslog.NOTSET):
        '''
        Method to release state variables fixed during initialization.
        Keyword Arguments:
            flags : dict containing information of which state variables
                    were fixed during initialization, and should now be
                    unfixed. This dict is returned by initialize if
                    hold_state=True.
            outlvl : sets output level of of logging
        '''
        init_log = idaeslog.getInitLogger(blk.name, outlvl, tag="properties")

        # Reactivate sum of mole fractions constraint
        for k in blk.keys():
            if blk[k].config.defined_state is False:
                blk[k].mole_fraction_constraint.activate()

        if flags is not None:
            # Unfix state variables
            revert_state_vars(blk, flags)

        init_log.info_high("State Released.")


@declare_process_block_class("HDAStateBlock",
                             block_class=_HDAStateBlock)
class HDAStateBlockData(StateBlockData):
    """
    Example property package for an ideal gas containing benzene, toluene
    hydrogen, methane and diphenyl.
    """

    def build(self):
        """Callable method for Block construction."""
        super(HDAStateBlockData, self).build()

        # Add state variables
        self.flow_mol = Var(
                initialize=1,
                bounds=(1e-8, 1000),
                units=pyunits.mol/pyunits.s,
                doc='Molar flow rate')
        self.mole_frac_comp = Var(self.component_list,
                                  initialize=0.2,
                                  bounds=(0, None),
                                  units=pyunits.dimensionless,
                                  doc="Component mole fractions")
        self.pressure = Var(initialize=101325,
                            bounds=(101325, 400000),
                            units=pyunits.Pa,
                            doc='State pressure')
        self.temperature = Var(initialize=298.15,
                               bounds=(298.15, 1500),
                               units=pyunits.K,
                               doc='State temperature')

        self.mw_comp = Reference(self.params.mw_comp)

        if self.config.defined_state is False:
            self.mole_fraction_constraint = Constraint(
                expr=1e3 == sum(1e3*self.mole_frac_comp[j]
                                for j in self.component_list))

        self.dens_mol = Var(initialize=1,
                            units=pyunits.mol/pyunits.m**3,
                            doc="Mixture density")

        self.ideal_gas_eq = Constraint(
            expr=self.pressure ==
            const.gas_constant*self.temperature*self.dens_mol)

    def _enth_mol(self):
        # Specific enthalpy
        def enth_rule(b):
            params = self.params
            T = self.temperature
            Tr = params.temperature_ref
            return sum(self.mole_frac_comp[j] * (
                           (params.cp_mol_ig_comp_coeff_D[j]/4)*(T**4-Tr**4) +
                           (params.cp_mol_ig_comp_coeff_C[j]/3)*(T**3-Tr**3) +
                           (params.cp_mol_ig_comp_coeff_B[j]/2)*(T**2-Tr**2) +
                           params.cp_mol_ig_comp_coeff_A[j]*(T-Tr) +
                           params.enth_mol_form_vap_comp_ref[j])
                       for j in self.component_list)
        self.enth_mol = Expression(rule=enth_rule)

    def get_material_flow_terms(self, p, j):
        return self.flow_mol * self.mole_frac_comp[j]

    def get_enthalpy_flow_terms(self, p):
        """Create enthalpy flow terms."""
        return self.flow_mol * self.enth_mol

    def default_material_balance_type(self):
        return MaterialBalanceType.componentPhase

    def default_energy_balance_type(self):
        return EnergyBalanceType.enthalpyTotal

    def get_material_flow_basis(self):
        return MaterialFlowBasis.molar

    def define_state_vars(self):
        return {"flow_mol": self.flow_mol,
                "mole_frac_comp": self.mole_frac_comp,
                "temperature": self.temperature,
                "pressure": self.pressure}
