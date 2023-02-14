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
Property package for ideal VLE calucations for the methanol synthesis problem.
Correlations from Turkay and Grossmann paper. See Latex files for details.
"""

# Import Python libraries
import logging

# Import Pyomo libraries
from pyomo.environ import (Constraint,
                           log,
                           NonNegativeReals,
                           value,
                           Var,
                           units as pyunits)
from pyomo.opt import SolverFactory, TerminationCondition

# Import IDAES cores
from idaes.core import (declare_process_block_class,
                        StateBlockData,
                        StateBlock,
                        MaterialFlowBasis,
                        MaterialBalanceType,
                        EnergyBalanceType)
from idaes.core.util.constants import Constants
from idaes.core.util.initialization import (fix_state_vars,
                                            revert_state_vars,
                                            solve_indexed_blocks)
from idaes.core.util.exceptions import ConfigurationError

# Some more inforation about this module
__author__ = "Jaffer Ghouse", "Brandon Paul"
__version__ = "0.0.1"


# Set up logger
_log = logging.getLogger(__name__)


class _IdealStateBlock(StateBlock):
    """
    This Class contains methods which should be applied to Property Blocks as a
    whole, rather than individual elements of indexed Property Blocks.
    """

    def initialize(blk, state_args=None,
                   hold_state=False, outlvl=0,
                   solver='ipopt', optarg={'tol': 1e-8}):
        """
        Initialization routine for property package.

        Keyword Arguments:
            state_args : Dictionary with initial guesses for the state vars
                         chosen. Note that if this method is triggered
                         through the control volume, and if initial guesses
                         were not provied at the unit model level, the
                         control volume passes the inlet values as initial
                         guess.The keys for the state_args dictionary are:

                         flow_mol : value at which to initialize component
                                    flows
                         pressure : value at which to initialize pressure
                         temperature : value at which to initialize temperature
                         mole_frac_comp: value at which to initialize the
                                    component mixture mole fraction
            outlvl : sets output level of initialization routine

                     * 0 = no output (default)
                     * 1 = return solver state for each step in routine
                     * 2 = include solver output infomation (tee=True)

            optarg : solver options dictionary object (default=None)
            solver : str indicating which solver to use during
                     initialization (default = 'ipopt')
            hold_state : flag indicating whether the initialization routine
                         should unfix any state variables fixed during
                         initialization (default=False).
                         - True - state variables are not unfixed, and
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
        # Fix state variables if not already fixed
        flags = fix_state_vars(blk, state_args)

        # Set solver options
        if outlvl > 1:
            stee = True
        else:
            stee = False

        if optarg is None:
            sopt = {'tol': 1e-8}
        else:
            sopt = optarg

        opt = SolverFactory('ipopt')
        opt.options = sopt

        # ---------------------------------------------------------------------
        for k in blk.keys():

            blk[k].eq_total.deactivate()
            blk[k].eq_comp.deactivate()
            if (blk[k].config.defined_state is False):
                blk[k].eq_mol_frac_out.deactivate()
            if (blk[k].config.has_phase_equilibrium) or \
                    (blk[k].config.parameters.config.valid_phase ==
                        ('Liq', 'Vap')) or \
                    (blk[k].config.parameters.config.valid_phase ==
                        ('Vap', 'Liq')):
                blk[k].eq_Keq.deactivate()
                blk[k].eq_sum_mol_frac.deactivate()

        if (blk[k].config.has_phase_equilibrium) or \
                (blk[k].config.parameters.config.valid_phase ==
                    ('Liq', 'Vap')) or \
                (blk[k].config.parameters.config.valid_phase ==
                    ('Vap', 'Liq')):
            results = solve_indexed_blocks(opt, [blk], tee=stee)

            if outlvl > 0:
                if results.solver.termination_condition \
                        == TerminationCondition.optimal:
                    _log.info("Initialization step 1 for "
                              "{} completed".format(blk.name))
                else:
                    _log.warning("Initialization step 1 for "
                                 "{} failed".format(blk.name))

        else:
            if outlvl > 0:
                _log.info("Initialization step 1 for "
                          "{} skipped".format(blk.name))

        for k in blk.keys():
            blk[k].eq_total.activate()
            blk[k].eq_comp.activate()
            if (blk[k].config.has_phase_equilibrium) or \
                    (blk[k].config.parameters.config.valid_phase ==
                        ('Liq', 'Vap')) or \
                    (blk[k].config.parameters.config.valid_phase ==
                        ('Vap', 'Liq')):
                blk[k].eq_Keq.activate()
                blk[k].eq_sum_mol_frac.activate()

        results = solve_indexed_blocks(opt, [blk], tee=stee)

        if outlvl > 0:
            if results.solver.termination_condition \
                    == TerminationCondition.optimal:
                _log.info("Initialization step 2 for "
                          "{} completed".format(blk.name))
            else:
                _log.warning("Initialization step 2 for "
                             "{} failed".format(blk.name))

        for k in blk.keys():
            if (blk[k].config.defined_state is False):
                blk[k].eq_mol_frac_out.activate()
        # ---------------------------------------------------------------------
        # If input block, return flags, else release state
        if hold_state is True:
            return flags
        else:
            blk.release_state(flags)

        if outlvl > 0:
            if outlvl > 0:
                _log.info('{} Initialization Complete.'.format(blk.name))

    def release_state(blk, flags, outlvl=0):
        '''
        Method to relase state variables fixed during initialization.

        Keyword Arguments:
            flags : dict containing information of which state variables
                    were fixed during initialization, and should now be
                    unfixed. This dict is returned by initialize if
                    hold_state=True.
            outlvl : sets output level of of logging
        '''
        # Unfix state variables
        revert_state_vars(blk, flags)

        if outlvl > 0:
            if outlvl > 0:
                _log.info('{} State Released.'.format(blk.name))


@declare_process_block_class("IdealStateBlock",
                             block_class=_IdealStateBlock)
class StateBlockData(StateBlockData):
    """An example property package for ideal VLE."""

    def build(self):
        """Callable method for Block construction."""
        super(StateBlockData, self).build()

        # Check for valid phase indicator and consistent flags
        if self.config.has_phase_equilibrium and \
                self.config.parameters.config.valid_phase in ['Vap', 'Liq']:
            raise ConfigurationError("Inconsistent inputs. Valid phase"
                                     " flag not set to VL for the state"
                                     " block but has_phase_equilibrium"
                                     " is set to True.")
        self._make_state_vars()
        self._make_vars()
        if not self.config.has_phase_equilibrium and \
                self.config.parameters.config.valid_phase == "Liq":
            self._make_liq_phase_eq()

        if (self.config.has_phase_equilibrium) or \
                (self.config.parameters.config.valid_phase ==
                    ('Liq', 'Vap')) or \
                (self.config.parameters.config.valid_phase ==
                    ('Vap', 'Liq')):
            self._make_flash_eq()

        if not self.config.has_phase_equilibrium and \
                self.config.parameters.config.valid_phase == "Vap":
            self._make_vap_phase_eq()

    def get_material_flow_basis(self):
        return MaterialFlowBasis.molar

    def _make_state_vars(self):
        """List the necessary state variable objects."""
        self.flow_mol = Var(initialize=1.0,
                            domain=NonNegativeReals,
                            units=pyunits.kmol/pyunits.s,
                            doc='Component molar flowrate')
        self.mole_frac_comp = Var(self._params.component_list,
                                  bounds=(0, 1),
                                  units=pyunits.dimensionless,
                                  initialize=1.0 /
                                  len(self._params.component_list))
        self.pressure = Var(initialize=0.101325,
                            domain=NonNegativeReals,
                            units=pyunits.MPa,
                            doc='State pressure')
        self.temperature = Var(initialize=3,
                               domain=NonNegativeReals,
                               units=pyunits.hK,
                               doc='State temperature')

    def _make_vars(self):
        self.flow_mol_phase = Var(self._params.phase_list,
                                  initialize=0.5,
                                  units=pyunits.kmol/pyunits.s,
                                  bounds=(0, None))

        self.mole_frac_phase_comp = Var(self._params.phase_list,
                                        self._params.component_list,
                                        initialize=1 /
                                        len(self._params.component_list),
                                        units=pyunits.dimensionless,
                                        bounds=(0, 1))

    def _make_liq_phase_eq(self):
        def rule_total_mass_balance(self):
            return self.flow_mol_phase['Liq'] == self.flow_mol
        self.eq_total = Constraint(rule=rule_total_mass_balance)

        def rule_comp_mass_balance(self, i):
            return self.flow_mol * self.mole_frac_comp[i] == \
                self.flow_mol_phase['Liq'] * \
                self.mole_frac_phase_comp['Liq', i]
        self.eq_comp = Constraint(self._params.component_list,
                                  rule=rule_comp_mass_balance)

        if self.config.defined_state is False:
            # applied at outlet only
            self.eq_mol_frac_out = Constraint(
                expr=sum(self.mole_frac_comp[i]
                         for i in self._params.component_list) == 1)

    def _make_vap_phase_eq(self):
        def rule_total_mass_balance(self):
            return self.flow_mol_phase['Vap'] == self.flow_mol
        self.eq_total = Constraint(rule=rule_total_mass_balance)

        def rule_comp_mass_balance(self, i):
            return self.flow_mol * self.mole_frac_comp[i] == \
                self.flow_mol_phase['Vap'] * \
                self.mole_frac_phase_comp['Vap', i]
        self.eq_comp = Constraint(self._params.component_list,
                                  rule=rule_comp_mass_balance)

        if self.config.defined_state is False:
            # applied at outlet only
            self.eq_mol_frac_out = Constraint(
                expr=sum(self.mole_frac_comp[i]
                         for i in self._params.component_list) == 1)

    def _make_flash_eq(self):
        self.vapor_pressure = Var(self._params.component_list,
                                  initialize=0.101325,
                                  domain=NonNegativeReals,
                                  units=pyunits.MPa,
                                  doc="Vapor pressure",
                                  bounds=(0.01, None))

        def rule_total_mass_balance(self):
            return self.flow_mol_phase['Liq'] + \
                self.flow_mol_phase['Vap'] == self.flow_mol
        self.eq_total = Constraint(rule=rule_total_mass_balance)

        def rule_comp_mass_balance(self, i):
            return self.flow_mol * self.mole_frac_comp[i] == \
                self.flow_mol_phase['Liq'] * \
                self.mole_frac_phase_comp['Liq', i] + \
                self.flow_mol_phase['Vap'] * \
                self.mole_frac_phase_comp['Vap', i]
        self.eq_comp = Constraint(self._params.component_list,
                                  rule=rule_comp_mass_balance)

        def rule_mole_frac(self):
            return sum(self.mole_frac_phase_comp['Liq', i]
                       for i in self._params.component_list) - \
                sum(self.mole_frac_phase_comp['Vap', i]
                    for i in self._params.component_list) == 0
        self.eq_sum_mol_frac = Constraint(rule=rule_mole_frac)

        if self.config.defined_state is False:
            # applied at outlet only
            self.eq_mol_frac_out = Constraint(
                expr=sum(self.mole_frac_comp[i]
                         for i in self._params.component_list) == 1)

        def rule_Keq(self, i):
            return self.mole_frac_phase_comp['Vap', i] * self.pressure == \
                self.vapor_pressure[i] * self.mole_frac_phase_comp['Liq', i]
        self.eq_Keq = Constraint(self._params.component_list, rule=rule_Keq)

        def rule_P_vap(self, j):  # coefficient converts MPa to mmHg
            return log(7500.6168 * self.vapor_pressure[j]) == \
                self._params.vapor_pressure_coeff[j, 'A'] - \
                (self._params.vapor_pressure_coeff[j, 'B'] /
                 (pyunits.convert(self.temperature, pyunits.K) -
                 self._params.vapor_pressure_coeff[j, 'C']))
        self.eq_P_vap = Constraint(self._params.component_list,
                                   rule=rule_P_vap)

    def _dens_mol_phase(self):
        self.dens_mol_phase = Var(self._params.phase_list,
                               units=pyunits.kmol/pyunits.m**3,
                               doc="Molar density")

        def dens_mol_phase_calculation(self, p):
            if p == "Vap":
                return self.pressure == (
                    self.dens_mol_phase[p] *
                    pyunits.convert(Constants.gas_constant,
                                    pyunits.MJ/pyunits.kmol/pyunits.K) *
                    pyunits.convert(self.temperature, pyunits.K))
            elif p == "Liq":
                # dummy value
                return self.dens_mol_phase[p] == 11.1*pyunits.kmol/pyunits.m**3
        try:
            # Try to build constraint
            self.dens_mol_phase_calculation = Constraint(
                self._params.phase_list, rule=dens_mol_phase_calculation)
        except AttributeError:
            # If constraint fails, clean up so that DAE can try again later
            self.del_component(self.dens_mol_phase)
            self.del_component(self.dens_mol_phase_calculation)
            raise

    def get_material_flow_terms(self, p, j):
        """Create material flow terms for control volume."""
        if (p == "Vap") and (j in self._params.component_list):
            return self.flow_mol_phase['Vap'] * \
                    self.mole_frac_phase_comp['Vap', j]
        elif (p == "Liq") and (j in self._params.component_list):
            return self.flow_mol_phase['Liq'] * \
                    self.mole_frac_phase_comp['Liq', j]
        else:
            return 0

    def get_enthalpy_flow_terms(self, p):
        """Create enthalpy flow terms [MJ/s]."""
        if p == "Vap":
            return self.flow_mol_phase['Vap'] * self._params.Cp * \
                   pyunits.convert(self.temperature, pyunits.K)
        elif p == "Liq":
            return self.flow_mol_phase['Liq'] * self._params.Cp * \
                   pyunits.convert(self.temperature, pyunits.K)

    def get_material_density_terms(self, p, j):
        """Create material density terms."""
        if p == "Liq":
            if j in self._params.component_list:
                return self.dens_mol_phase[p] * \
                        self.mole_frac_phase_comp['Liq', j]
            else:
                return 0
        elif p == "Vap":
            if j in self._params.component_list:
                return self.dens_mol_phase[p] * \
                        self.mole_frac_phase_comp['Vap', j]
            else:
                return 0

    def get_enthalpy_density_terms(self, p):
        """Create enthalpy density terms."""
        if p == "Liq":
            return self.dens_mol_phase[p] * self._params.Cp * \
                   pyunits.convert(self.temperature, pyunits.K)
        elif p == "Vap":
            return (self.dens_mol_phase[p] * (
                    self._params.Cp -
                    pyunits.convert(Constants.gas_constant,
                                    pyunits.MJ/pyunits.kmol/pyunits.K) *
                    pyunits.convert(self.temperature, pyunits.K)))

    def default_material_balance_type(self):
        return MaterialBalanceType.componentTotal

    def default_energy_balance_type(self):
        return EnergyBalanceType.enthalpyTotal

    def define_state_vars(self):
        """Define state vars."""
        return {"flow_mol": self.flow_mol,
                "mole_frac_comp": self.mole_frac_comp,
                "temperature": self.temperature,
                "pressure": self.pressure}

    def model_check(blk):
        """Model checks for property block."""
        # Check temperature bounds
        if value(blk.temperature) < blk.temperature.lb:
            _log.error('{} Temperature set below lower bound.'
                       .format(blk.name))
        if value(blk.temperature) > blk.temperature.ub:
            _log.error('{} Temperature set above upper bound.'
                       .format(blk.name))

        # Check pressure bounds
        if value(blk.pressure) < blk.pressure.lb:
            _log.error('{} Pressure set below lower bound.'.format(blk.name))
        if value(blk.pressure) > blk.pressure.ub:
            _log.error('{} Pressure set above upper bound.'.format(blk.name))
