#################################################################################
# The Institute for the Design of Advanced Energy Systems Integrated Platform
# Framework (IDAES IP) was produced under the DOE Institute for the
# Design of Advanced Energy Systems (IDAES), and is copyright (c) 2018-2021
# by the software owners: The Regents of the University of California, through
# Lawrence Berkeley National Laboratory,  National Technology & Engineering
# Solutions of Sandia, LLC, Carnegie Mellon University, West Virginia University
# Research Corporation, et al.  All rights reserved.
#
# Please see the files COPYRIGHT.md and LICENSE.md for full copyright and
# license information.
#################################################################################
"""
This package provides the necessary constraints for solid phase properties of
the NETL_32D sorbent.
Components - H2O, Carbamate('Car'), SiO

Parameters and equations written in this model were primarily derived from:
A. Lee, D.C. Miller, A One-Dimensional (1-D) Three-Region Model for a
 Bubbling Fluidized-Bed Adsorber, Ind. Eng. Chem. Res. 52 (2013) 469–484.

"""

# Import Pyomo libraries
from pyomo.environ import (
    Constraint,
    Expression,
    Param,
    Reals,
    value,
    Var,
    units as pyunits,
)
from pyomo.util.calc_var_value import calculate_variable_from_constraint

# Import IDAES cores
from idaes.core import (
    declare_process_block_class,
    MaterialFlowBasis,
    PhysicalParameterBlock,
    StateBlockData,
    StateBlock,
    MaterialBalanceType,
    EnergyBalanceType,
    Component,
    SolidPhase,
)
from idaes.core.util.initialization import (
    fix_state_vars,
    revert_state_vars,
    solve_indexed_blocks,
)
from idaes.core.util.math import smooth_max
from idaes.core.util.misc import add_object_reference
from idaes.core.util.model_statistics import (
    degrees_of_freedom,
    number_unfixed_variables_in_activated_equalities,
)
import idaes.logger as idaeslog
from idaes.core.util import scaling as iscale
from idaes.core.solvers import get_solver

# Some more information about this module
__author__ = "Chinedu Okoli"


# Set up logger
_log = idaeslog.getLogger(__name__)


@declare_process_block_class("SolidPhaseParameterBlock")
class PhysicalParameterData(PhysicalParameterBlock):
    """
    Property Parameter Block Class

    This package provedes the necessary constraints for solids properties
    for sorbent NETL 32D.
    """

    def build(self):
        """
        Callable method for Block construction.
        """
        super(PhysicalParameterData, self).build()

        self._state_block_class = SolidPhaseStateBlock

        # Create Phase object
        self.Sol = SolidPhase()

        # Create Component objects
        self.H2O_s = Component()
        self.Car = Component()
        self.SiO = Component()

        # -------------------------------------------------------------------------
        """ Pure solid component properties"""

        # Thermodynamic reference state
        self.temperature_ref = Param(
            mutable=True,
            default=298.15,
            doc="Thermodynamic Reference" "Temperature [K]",
        )

        # TODO - actual molecular weights of the materials can be substituted here
        # but are not necessary for peformance calculations
        mw_comp_dict = {
            "H2O_s": 0.018,  # MW of H2O(g) is used for H2O(s)
            "Car": 0.044,  # MW of CO2(g) is used for carbamate
            "SiO": 0.06,  # complex material, MW of SiO2 is used as a dummy
        }
        # Molecular weight should be defined in default units
        # (default mass units)/(default amount units)
        # per the define_meta.add_default_units method below
        self.mw_comp = Param(
            self.component_list,
            mutable=False,
            initialize=mw_comp_dict,
            doc="Molecular weights of solid components [kg/mol]",
            units=pyunits.kg / pyunits.mol,
        )

        # -------------------------------------------------------------------------
        """ Mixed solid properties"""
        # These are setup as fixed vars to allow for parameter estimation

        # Particle size
        self.particle_dia = Var(
            domain=Reals,
            initialize=1.5e-4,
            doc="Diameter of solid particles [m]",
            units=pyunits.m,
        )
        self.particle_dia.fix()

        # Minimum fluidization voidage
        self.voidage_mf = Var(
            domain=Reals,
            initialize=0.5,  # obtained from original BFB paper, ergun eqn gives 0.46
            doc="Voidage at minimum fluidization [-]",
            units=pyunits.m**3 / pyunits.m**3,
        )

        self.voidage_mf.fix()
        # calculated from ergun eqn for diameter of particle = 1.5e-4 m,
        # and minimukm fluidization voidage = 0.5
        self.velocity_mf = Var(
            domain=Reals,
            initialize=0.0091,
            doc="Velocity at minimum fluidization [m/s]",
            units=pyunits.m / pyunits.s,
        )
        self.velocity_mf.fix()

        # Voidage of the bed
        self.voidage = Var(
            domain=Reals,
            initialize=0.45,
            doc="Voidage [-]",
            units=pyunits.m**3 / pyunits.m**3,
        )
        self.voidage.fix()

        # Particle density
        self.dens_mass_particle_param = Var(
            domain=Reals,
            initialize=442,
            doc="Constant mass density of the particle",
            units=pyunits.kg / pyunits.m**3,
        )
        self.dens_mass_particle_param.fix()

        # Particle heat capacity
        self.cp_mass_param = Var(
            domain=Reals,
            initialize=1.13,
            doc="Constant heat capacity of the particle",
            units=pyunits.J / pyunits.kg / pyunits.K,
        )
        self.cp_mass_param.fix()

        # Particle thermal conductivity
        self.therm_cond_sol = Var(
            domain=Reals,
            initialize=1.36,
            doc="Thermal conductivity of solid particles [J/m.K.s]",
            units=pyunits.J / pyunits.m / pyunits.K / pyunits.s,
        )
        self.therm_cond_sol.fix()

        # Set default scaling for state variables
        self.set_default_scaling("flow_mass", 1e-3)
        self.set_default_scaling("temperature", 1e-2)
        for comp in self.component_list:
            self.set_default_scaling("mass_frac_comp", 1e1, index=comp)

        # Set default scaling for thermophysical and transport properties
        self.set_default_scaling("enth_mass", 1e-6)
        self.set_default_scaling("cp_mass", 1e-6)
        self.set_default_scaling("dens_mass_particle", 1e-2)
        self.set_default_scaling("dens_mass_skeletal", 1e-2)

    @classmethod
    def define_metadata(cls, obj):
        obj.add_properties(
            {
                # TODO - also use flow_mass state var if moving or bubbling fludized
                # bed unit models are used
                # "flow_mass": {"method": None, "units": "kg/s"},
                "temperature": {"method": None, "units": "K"},
                "mass_frac_comp": {"method": None, "units": None},
                "cp_mass": {"method": "_cp_mass", "units": "J/kg.K"},
                "enth_mass": {"method": "_enth_mass", "units": "J/kg"},
            }
        )
        
        obj.define_custom_properties(
            {
                "dens_mass_particle": {"method": None,
                                       "units": pyunits.dimensionless},
                "mass_frac_comp_max": {"method": "_mass_frac_comp_max",
                                       "units": pyunits.dimensionless},
            }
        )

        obj.add_default_units(
            {
                "time": pyunits.s,
                "length": pyunits.m,
                "mass": pyunits.kg,
                "amount": pyunits.mol,
                "temperature": pyunits.K,
            }
        )


class _SolidPhaseStateBlock(StateBlock):
    """
    This Class contains methods which should be applied to State Blocks as a
    whole, rather than individual elements of indexed State Blocks.
    """

    def initialize(
        blk,
        state_args=None,
        hold_state=False,
        state_vars_fixed=False,
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
                         guess.
                         Keys for the state_args dictionary are:
                         flow_mass, temperature, and mass_frac_comp
            outlvl : sets output level of initialization routine
            optarg : solver options dictionary object (default=None, use
                     default solver options)
            solver : str indicating which solver to use during
                     initialization (default = None, use default solver)
            hold_state : flag indicating whether the initialization routine
                         should unfix any state variables fixed during
                         initialization (default=False).
                         - True - states variables are not unfixed, and
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

        init_log.info_high("Starting initialization")

        # Deactivate the constraints specific for outlet block i.e.
        # when defined state is False
        for k in blk.keys():
            if blk[k].config.defined_state is False:
                blk[k].sum_component_eqn.deactivate()

        # Fix state variables if not already fixed
        if state_vars_fixed is False:
            flags = fix_state_vars(blk, state_args)
        else:
            # Check when the state vars are fixed already result in dof 0
            for k in blk.keys():
                if degrees_of_freedom(blk[k]) != 0:
                    raise Exception(
                        "State vars fixed but degrees of freedom "
                        "for state block is not zero during "
                        "initialization."
                    )

        # ---------------------------------------------------------------------
        # Initialize values
        for k in blk.keys():
            if hasattr(blk[k], "mixture_heat_capacity_eqn"):
                calculate_variable_from_constraint(
                    blk[k].cp_mass, blk[k].mixture_heat_capacity_eqn
                )

            if hasattr(blk[k], "mixture_enthalpy_eqn"):
                calculate_variable_from_constraint(
                    blk[k].enth_mass, blk[k].mixture_enthalpy_eqn
                )

        # Solve property block if non-empty
        free_vars = 0
        for k in blk.keys():
            free_vars += number_unfixed_variables_in_activated_equalities(blk[k])

        if free_vars > 0:
            # Create solver
            opt = get_solver(solver, optarg)
            with idaeslog.solver_log(solve_log, idaeslog.DEBUG) as slc:
                res = solve_indexed_blocks(opt, [blk], tee=slc.tee)
        else:
            res = ""
        init_log.info_high(
            "Initialization complete {}.".format(idaeslog.condition(res))
        )

        # ---------------------------------------------------------------------
        if state_vars_fixed is False:
            if hold_state is True:
                return flags
            else:
                blk.release_state(flags)

    def release_state(blk, flags, outlvl=idaeslog.NOTSET):
        """
        Method to relase state variables fixed during initialization.
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
        revert_state_vars(blk, flags)

        # Activate state variable related constraints
        for k in blk.keys():
            if blk[k].config.defined_state is False:
                blk[k].sum_component_eqn.activate()

        init_log = idaeslog.getInitLogger(blk.name, outlvl, tag="properties")
        init_log.info_high("States released.")


@declare_process_block_class("SolidPhaseStateBlock", block_class=_SolidPhaseStateBlock)
class SolidPhaseStateBlockData(StateBlockData):
    """
    Property package for gas phase properties of methane combustion in CLC FR
    """

    def build(self):
        """
        Callable method for Block construction
        """
        super(SolidPhaseStateBlockData, self).build()

        # Object reference for molecular weight if needed by CV1D
        # Molecular weights
        add_object_reference(self, "mw_comp", self.config.parameters.mw_comp)

        self._make_state_vars()

    def _make_state_vars(self):
        """List the necessary state variable objects."""

        # create units object to get default units from the param block
        units_meta = self._params.get_metadata().derived_units

        # TODO - also use flow_mass state var if moving or bubbling fludized
        # bed unit models are used

        # self.flow_mass = Var(
        #     initialize=1.0,
        #     domain=Reals,
        #     doc="Component mass flowrate",
        #     units=units_meta["mass"] / units_meta["time"],
        # )

        self.dens_mass_particle = Var(
            domain=Reals,
            initialize=442,
            doc="Particle density of oxygen carrier",
            units=units_meta["mass"] * units_meta["length"] ** -3,
        )

        self.mass_frac_comp = Var(
            self._params.component_list,
            initialize=1 / len(self._params.component_list),
            doc="State component mass fractions [-]",
            units=units_meta["mass"] / units_meta["mass"],
        )
        self.temperature = Var(
            initialize=298.15,
            domain=Reals,
            doc="State temperature",
            units=units_meta["temperature"],
        )

        # Create standard constraints
        # Sum mass fractions if not inlet block
        if self.config.defined_state is False:

            def sum_component_eqn(b):
                return 1 == sum(b.mass_frac_comp[j] for j in b._params.component_list)

            self.sum_component_eqn = Constraint(rule=sum_component_eqn)

    def _mass_frac_comp_max(self):
        eps = 2e-10

        def mass_frac_comp_max_expr(b, i):
            return smooth_max(b.mass_frac_comp[i], 0, eps)

        try:
            self.mass_frac_comp_max = Expression(
                self._params.component_list, rule=mass_frac_comp_max_expr
            )
        except AttributeError:
            self.del_component(self.mass_frac_comp_max)
            raise

    def _dens_mass_particle(self):
        # Particle density of OC (includes the OC pores)
        units_meta = self._params.get_metadata().derived_units
        self.dens_mass_particle = Var(
            domain=Reals,
            initialize=3251.75,
            doc="Particle density of oxygen carrier",
            units=units_meta["mass"] * units_meta["length"] ** -3,
        )

        def density_particle_constraint(b):
            return b.dens_mass_particle == b._params.dens_mass_particle_param

        try:
            # Try to build constraint
            self.density_particle_constraint = Constraint(
                rule=density_particle_constraint
            )
        except AttributeError:
            # If constraint fails, clean up so that DAE can try again later
            self.del_component(self.dens_mass_particle)
            self.del_component(self.density_particle_constraint)
            raise

    def _cp_mass(self):
        # Mixture heat capacities
        units_meta = self._params.get_metadata().derived_units
        units_cp_mass = (
            units_meta["energy"]
            * units_meta["mass"] ** -1
            * units_meta["temperature"] ** -1
        )
        self.cp_mass = Var(
            domain=Reals,
            initialize=1.0,
            doc="Mixture heat capacity, mass-basis",
            units=units_cp_mass,
        )

        def cp_mass(b):
            return b.cp_mass == b._params.cp_mass_param

        try:
            # Try to build constraint
            self.mixture_heat_capacity_eqn = Constraint(rule=cp_mass)
        except AttributeError:
            # If constraint fails, clean up so that DAE can try again later
            self.del_component(self.cp_mass)
            self.del_component(self.mixture_heat_capacity_eqn)
            raise

    def _enth_mass(self):
        # Mixture mass enthalpy
        units_meta = self._params.get_metadata().derived_units
        units_enth_mass = units_meta["energy"] * units_meta["mass"] ** -1
        self.enth_mass = Var(
            domain=Reals,
            initialize=0.0,
            doc="Mixture specific enthalpy",
            units=units_enth_mass,
        )
        try:
            # Try to build constraint
            self.mixture_enthalpy_eqn = Constraint(
                expr=(
                    self.enth_mass
                    == self.cp_mass * (self.temperature - self._params.temperature_ref)
                )
            )
        except AttributeError:
            # If constraint fails, clean up so that DAE can try again later
            self.del_component(self.enth_mass)
            self.del_component(self.mixture_enthalpy_eqn)
            raise

    def get_material_flow_terms(self, p, j):
        if not self.is_property_constructed("material_flow_terms"):
            try:

                def rule_material_flow_terms(b, j):
                    return b.flow_mass * b.mass_frac_comp[j]

                self.material_flow_terms = Expression(
                    self._params.component_list, rule=rule_material_flow_terms
                )
            except AttributeError:
                self.del_component(self.material_flow_terms)
        return self.material_flow_terms[j]

    def get_enthalpy_flow_terms(self, p):
        if not self.is_property_constructed("enthalpy_flow_terms"):
            try:

                def rule_enthalpy_flow_terms(b):
                    return self.enth_mass * self.flow_mass

                self.enthalpy_flow_terms = Expression(rule=rule_enthalpy_flow_terms)
            except AttributeError:
                self.del_component(self.enthalpy_flow_terms)
        return self.enthalpy_flow_terms

    def get_material_density_terms(self, p, j):
        if not self.is_property_constructed("material_density_terms"):
            try:

                def rule_material_density_terms(b, j):
                    return b.dens_mass_particle * b.mass_frac_comp[j]

                self.material_density_terms = Expression(
                    self._params.component_list, rule=rule_material_density_terms
                )
            except AttributeError:
                self.del_component(self.material_density_terms)
        return self.material_density_terms[j]

    def get_energy_density_terms(self, p):
        if not self.is_property_constructed("energy_density_terms"):
            try:

                def rule_energy_density_terms(b):
                    return b.dens_mass_particle * b.enth_mass

                self.energy_density_terms = Expression(rule=rule_energy_density_terms)
            except AttributeError:
                self.del_component(self.energy_density_terms)
        return self.energy_density_terms

    def define_state_vars(b):
        # TODO - also use flow_mass state var if moving or bubbling fludized
        # bed unit models are used
        return {
            # "flow_mass": b.flow_mass,
            "dens_mass_particle": b.dens_mass_particle,
            "temperature": b.temperature,
            "mass_frac_comp": b.mass_frac_comp,
        }

    def get_material_flow_basis(b):
        return MaterialFlowBasis.mass

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

    def default_material_balance_type(blk):
        return MaterialBalanceType.componentTotal

    def default_energy_balance_type(blk):
        return EnergyBalanceType.enthalpyTotal

    def calculate_scaling_factors(self):
        super().calculate_scaling_factors()

        # scale some variables - no variables to scale

        # scale some constraints
        if self.is_property_constructed("material_flow_terms"):
            for i, c in self.material_flow_terms.items():
                sf1 = iscale.get_scaling_factor(self.mass_frac_comp[i])
                sf2 = iscale.get_scaling_factor(self.flow_mass)
                iscale.set_scaling_factor(c, sf1 * sf2)

        if self.is_property_constructed("material_density_terms"):
            for i, c in self.material_density_terms.items():
                sf1 = iscale.get_scaling_factor(self.mass_frac_comp[i])
                sf2 = iscale.get_scaling_factor(self.dens_mass_particle)
                iscale.set_scaling_factor(c, sf1 * sf2)

        if self.is_property_constructed("energy_density_terms"):
            for i, c in self.energy_density_terms.items():
                sf1 = iscale.get_scaling_factor(self.enth_mass)
                sf2 = iscale.get_scaling_factor(self.dens_mass_particle)
                iscale.set_scaling_factor(c, sf1 * sf2)

        if self.is_property_constructed("enthalpy_flow_terms"):
            for i, c in self.enthalpy_flow_terms.items():
                sf1 = iscale.get_scaling_factor(self.enth_mass)
                sf2 = iscale.get_scaling_factor(self.flow_mass)
                iscale.set_scaling_factor(c, sf1 * sf2)

        # Scale some constraints
        if self.is_property_constructed("sum_component_eqn"):
            iscale.constraint_scaling_transform(
                self.sum_component_eqn,
                iscale.get_scaling_factor(self.mass_frac_comp["Fe2O3"]),
                overwrite=False,
            )
        if self.is_property_constructed("density_particle_constraint"):
            iscale.constraint_scaling_transform(
                self.density_particle_constraint,
                iscale.get_scaling_factor(self.dens_mass_particle),
                overwrite=False,
            )
        if self.is_property_constructed("density_skeletal_constraint"):
            iscale.constraint_scaling_transform(
                self.density_particle_constraint,
                iscale.get_scaling_factor(self.dens_mass_skeletal),
                overwrite=False,
            )
        if self.is_property_constructed("mixture_heat_capacity_eqn"):
            iscale.constraint_scaling_transform(
                self.mixture_heat_capacity_eqn,
                iscale.get_scaling_factor(self.cp_mass),
                overwrite=False,
            )

        if self.is_property_constructed("mixture_enthalpy_eqn"):
            iscale.constraint_scaling_transform(
                self.mixture_enthalpy_eqn,
                iscale.get_scaling_factor(self.enth_mass),
                overwrite=False,
            )
