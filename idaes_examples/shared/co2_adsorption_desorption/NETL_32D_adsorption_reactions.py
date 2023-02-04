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
Property package for the reaction of CO2 with an adorbent (NETL 32D).
Overall adsorption reactions for CO2 and H2O adsorption:
Note that the reactions are only a simplified way of showing the key
reactions taking place and should not be used for element balances
(1) H2O(g) <=> H2O(s)
(2) SiO + CO2(g) <=> SiO(g) + Car(s)

Parameters and equations written in this model were primarily derived from:
A. Lee, D.S. Mebane, D.J. Fauth, D.C. Miller, A Model for the Adsorption 
 Kinetics of CO2 on Amine-Impregnated Mesoporous Sorbents in the Presence of 
 Water. Presented at the 28th International Pittsburgh Coal Conference, 
 Pittsburgh, PA, 2011.
A. Lee, D.C. Miller, A One-Dimensional (1-D) Three-Region Model for a
 Bubbling Fluidized-Bed Adsorber, Ind. Eng. Chem. Res. 52 (2013) 469–484.

"""

# Import Pyomo libraries
from pyomo.environ import (
    Constraint,
    exp,
    Param,
    Reals,
    Set,
    value,
    Var,
    units as pyunits,
)
from pyomo.util.calc_var_value import calculate_variable_from_constraint
from pyomo.common.config import ConfigBlock, ConfigValue, Bool


# Import IDAES cores
from idaes.core import (
    declare_process_block_class,
    MaterialFlowBasis,
    ReactionParameterBlock,
    ReactionBlockDataBase,
    ReactionBlockBase,
)
from idaes.core.util.misc import add_object_reference
from idaes.core.util.initialization import (
    fix_state_vars,
    revert_state_vars,
    solve_indexed_blocks,
)
from idaes.core.util.model_statistics import (
    number_unfixed_variables_in_activated_equalities,
)
from idaes.core.util.config import (
    is_state_block,
    is_physical_parameter_block,
    is_reaction_parameter_block,
)
from idaes.core.util.math import smooth_max
from idaes.core.util.constants import Constants
import idaes.logger as idaeslog
from idaes.core.util import scaling as iscale
from idaes.core.solvers import get_solver

# Some more information about this module
__author__ = "Chinedu Okoli"


# Set up logger
_log = idaeslog.getLogger(__name__)


@declare_process_block_class("HeteroReactionParameterBlock")
class ReactionParameterData(ReactionParameterBlock):
    """
    Property Parameter Block Class

    Contains parameters and indexing sets associated with reaction properties
    for CO2 adsorption onto the NETL 32D sorbent.

    """

    # Create Class ConfigBlock
    CONFIG = ConfigBlock()
    CONFIG.declare(
        "gas_property_package",
        ConfigValue(
            description="Reference to associated PropertyPackageParameter "
            "object for the gas phase.",
            domain=is_physical_parameter_block,
        ),
    )
    CONFIG.declare(
        "solid_property_package",
        ConfigValue(
            description="Reference to associated PropertyPackageParameter "
            "object for the solid phase.",
            domain=is_physical_parameter_block,
        ),
    )
    CONFIG.declare(
        "default_arguments",
        ConfigBlock(
            description="Default arguments to use with Property Package", implicit=True
        ),
    )

    def build(self):
        """
        Callable method for Block construction.
        """
        super(ReactionParameterBlock, self).build()

        self._reaction_block_class = ReactionBlock

        # Reaction Index
        self.rate_reaction_idx = Set(initialize=["R1", "R2"])

        # Smoothing factor
        self.eps = Param(
            mutable=True,
            default=1e-8,
            doc="Smoothing Factor",
            units=pyunits.mol / pyunits.m**3,
        )
        # Reaction rate scale factor
        self._scale_factor_rxn = Param(
            mutable=True,
            default=1,
            doc="Scale Factor for reaction eqn." "Used to help initialization routine",
        )

        # Reaction Stoichiometry
        self.rate_reaction_stoichiometry = {
            ("R1", "Vap", "N2"): 0,
            ("R1", "Vap", "O2"): 0,
            ("R1", "Vap", "H2O"): -1,
            ("R1", "Vap", "CO2"): 0,
            ("R1", "Sol", "H2O_s"): 1,
            ("R1", "Sol", "Car"): 0,
            ("R1", "Sol", "SiO"): 0,
            ("R2", "Vap", "N2"): 0,
            ("R2", "Vap", "O2"): 0,
            ("R2", "Vap", "H2O"): 0,
            ("R2", "Vap", "CO2"): -1,
            ("R2", "Sol", "H2O_s"): 0,
            ("R2", "Sol", "Car"): 1,
            ("R2", "Sol", "SiO"): 0,
        }

        # Standard Heat of Reaction - J/mol_rxn
        dh_rxn_dict = {
            "R1": -52100,
            "R2": -64700,
        }

        # Heat of Reaction should be defined in default units
        # (default energy units)/(default amount units)
        # per the define_meta.add_default_units method in the
        # relevant phase - in this case, the solid phase properties
        self.dh_rxn = Var(
            self.rate_reaction_idx,
            initialize=dh_rxn_dict,
            doc="Heat of reaction [J/mol]",
            units=pyunits.J / pyunits.mol,
        )
        self.dh_rxn.fix()

        # Reaction entropy - J/mol/K
        dS_rxn_dict = {"R1": -78.5, "R2": -174.6}
        self.dS_rxn = Var(
            self.rate_reaction_idx,
            domain=Reals,
            initialize=dS_rxn_dict,
            doc="Activation energy [J/mol/K]",
            units=pyunits.J / pyunits.mol / pyunits.K,
        )
        self.dS_rxn.fix()

        # -------------------------------------------------------------------------
        """ Reaction properties that can be estimated"""

        # Amine loading of the sorbent
        self.nv = Var(
            domain=Reals,
            initialize=1900.46,
            doc="Amine loading of the sorbent",
            units=pyunits.mol / pyunits.m**3,
        )
        self.nv.fix()

        # Reaction activation Energy - J/mol
        energy_activation_dict = {"R1": 28200, "R2": 57700}
        self.energy_activation = Var(
            self.rate_reaction_idx,
            domain=Reals,
            initialize=energy_activation_dict,
            doc="Activation energy [J/mol]",
            units=pyunits.J / pyunits.mol,
        )
        self.energy_activation.fix()

        # Pre-exponential factor
        k0_rxn_dict = {"R1": 56234.13, "R2": 100}
        self.k0_rxn = Var(
            self.rate_reaction_idx,
            domain=Reals,
            initialize=k0_rxn_dict,
            doc="Pre-exponential factor",
            units=pyunits.mol / pyunits.m**3 / pyunits.s,
        )
        self.k0_rxn.fix()

    @classmethod
    def define_metadata(cls, obj):
        obj.add_properties(
            {
                "k_rxn": {
                    "method": "_rate_constant",
                    "units": "mol/m**3/s]",
                },
                "reaction_rate": {
                    "method": "_reaction_rate",
                    "units": "mol_rxn/m**3/s",
                },
            }
        )
        
        obj.define_custom_properties(
            {
                "specie_concentration": {
                    "method": "_specie_concentration",
                    "units": "mol/kg",
                },
                "Kequil_rxn": {"method": "_Kequil_rxn", "units": None},
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


class _ReactionBlock(ReactionBlockBase):
    """
    This Class contains methods which should be applied to Reaction Blocks as a
    whole, rather than individual elements of indexed Reaction Blocks.
    """

    def initialize(blk, outlvl=idaeslog.NOTSET, optarg=None, solver=None):
        """
        Initialization routine for reaction package.

        Keyword Arguments:
            outlvl : sets output level of initialization routine
            optarg : solver options dictionary object (default=None, use
                     default solver options)
            solver : str indicating which solver to use during
                     initialization (default = None, use default solver)
        Returns:
            None
        """
        init_log = idaeslog.getInitLogger(blk.name, outlvl, tag="reactions")
        solve_log = idaeslog.getSolveLogger(blk.name, outlvl, tag="reactions")

        init_log.info_high("Starting initialization")

        # TODO - Update in the future as needed
        # Get a single representative block for getting config arguments
        for k in blk.keys():
            break

        # Fix state variables if not already fixed
        # Fix state variables of the primary (solid) state block
        state_var_flags = fix_state_vars(blk[k].config.solid_state_block)

        # Fix values of secondary (gas) state block variables if not fixed,
        # as well as the solid density variable.
        # This is done to keep the initialization problem square
        Cflag = {}  # Gas mole fraction flag
        Dflag = {}  # Solid density flag

        for k in blk.keys():
            for j in blk[k].gas_state_ref._params.component_list:
                if blk[k].gas_state_ref.mole_frac_comp[j].fixed is True:
                    Cflag[k, j] = True
                else:
                    Cflag[k, j] = False
                    blk[k].gas_state_ref.mole_frac_comp[j].fix(
                        blk[k].gas_state_ref.mole_frac_comp[j].value
                    )
            if blk[k].solid_state_ref.dens_mass_particle.fixed is True:
                Dflag[k] = True
            else:
                Dflag[k] = False
                blk[k].solid_state_ref.dens_mass_particle.fix(
                    blk[k].solid_state_ref.dens_mass_particle.value
                )

        # Initialize values
        for k in blk.keys():
            for j in blk[k].solid_state_ref._params.component_list:
                if hasattr(blk[k], "specie_concentration_eqn"):
                    calculate_variable_from_constraint(
                        blk[k].specie_concentration[j],
                        blk[k].specie_concentration_eqn[j],
                    )
            for j in blk[k]._params.rate_reaction_idx:
                if hasattr(blk[k], "Kequil_rxn_eqn"):
                    calculate_variable_from_constraint(
                        blk[k].Kequil_rxn[j], blk[k].Kequil_rxn_eqn[j]
                    )

                if hasattr(blk[k], "rate_constant_eqn"):
                    calculate_variable_from_constraint(
                        blk[k].k_rxn[j], blk[k].rate_constant_eqn[j]
                    )

                if hasattr(blk[k], "gen_rate_expression"):
                    calculate_variable_from_constraint(
                        blk[k].reaction_rate[j], blk[k].gen_rate_expression[j]
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
            "reactions initialization complete {}.".format(idaeslog.condition(res))
        )

        # ---------------------------------------------------------------------
        # Revert state vars and other variables to pre-initialization states
        # Revert state variables of the primary (solid) state block
        revert_state_vars(blk[k].config.solid_state_block, state_var_flags)

        for k in blk.keys():
            for j in blk[k].gas_state_ref._params.component_list:
                if Cflag[k, j] is False:
                    blk[k].gas_state_ref.mole_frac_comp[j].unfix()
            if Dflag[k] is False:
                blk[k].solid_state_ref.dens_mass_particle.unfix()

        init_log = idaeslog.getInitLogger(blk.name, outlvl, tag="reactions")
        init_log.info_high("States released.")


@declare_process_block_class("ReactionBlock", block_class=_ReactionBlock)
class ReactionBlockData(ReactionBlockDataBase):
    """
    Heterogeneous reaction package
    """

    # Create Class ConfigBlock
    CONFIG = ConfigBlock()
    CONFIG.declare(
        "parameters",
        ConfigValue(
            domain=is_reaction_parameter_block,
            description="""
            A reference to an instance of the Reaction Parameter
            Block associated with this property package.
            """,
        ),
    )
    CONFIG.declare(
        "solid_state_block",
        ConfigValue(
            domain=is_state_block,
            description="""
            A reference to an instance of a StateBlock for the
            solid phase with which this reaction block should be associated.
            """,
        ),
    )
    CONFIG.declare(
        "gas_state_block",
        ConfigValue(
            domain=is_state_block,
            description="""
            A reference to an instance of a StateBlock for the
            gas phase with which this reaction block should be associated.
            """,
        ),
    )
    CONFIG.declare(
        "has_equilibrium",
        ConfigValue(
            default=False,
            domain=Bool,
            description="Equilibrium reaction construction flag",
            doc="""
        Indicates whether terms for equilibrium controlled reactions
        should be constructed,
        **default** - True.
        **Valid values:** {
        **True** - include equilibrium reaction terms,
        **False** - exclude equilibrium reaction terms.}
        """,
        ),
    )

    def build(self):
        """
        Callable method for Block construction
        """
        super(ReactionBlockDataBase, self).build()

        # Object references to the corresponding state blocks and parameters
        add_object_reference(self, "_params", self.config.parameters)

        add_object_reference(
            self, "solid_state_ref", self.config.solid_state_block[self.index()]
        )
        add_object_reference(
            self, "gas_state_ref", self.config.gas_state_block[self.index()]
        )

        # Object reference for parameters if needed by CV1D
        # Reaction stoichiometry
        add_object_reference(
            self,
            "rate_reaction_stoichiometry",
            self.config.parameters.rate_reaction_stoichiometry,
        )

        # Heat of reaction
        add_object_reference(self, "dh_rxn", self.config.parameters.dh_rxn)

    # Adsorbed species concentration
    def _specie_concentration(self):
        self.specie_concentration = Var(
            self.solid_state_ref._params.component_list,
            domain=Reals,
            initialize=1,
            doc="Adsorbed species concentration on the sorbent",
            units=pyunits.mol / pyunits.kg,
        )

        def specie_concentration_eqn(b, j):
            if j == "H2O_s":
                return (
                    b.specie_concentration[j]
                    * b.solid_state_ref.mass_frac_comp["SiO"]
                    * b.solid_state_ref._params.mw_comp[j]
                    == b.solid_state_ref.mass_frac_comp[j]
                )
            elif j == "Car":
                return (
                    b.specie_concentration[j]
                    * b.solid_state_ref.mass_frac_comp["SiO"]
                    * b.solid_state_ref._params.mw_comp[j]
                    == b.solid_state_ref.mass_frac_comp[j]
                )
            else:
                return self.specie_concentration[j] == 1.0

        try:
            # Try to build constraint
            self.specie_concentration_eqn = Constraint(
                self.solid_state_ref._params.component_list,
                rule=specie_concentration_eqn,
            )
        except AttributeError:
            # If constraint fails, clean up so that DAE can try again later
            self.del_component(self.specie_concentration)
            self.del_component(self.specie_concentration_eqn)
            raise

    # Rate constant method
    def _rate_constant(self):
        self.k_rxn = Var(
            self._params.rate_reaction_idx,
            domain=Reals,
            initialize=1,
            doc="Rate constant",
            units=pyunits.mol / pyunits.m**3 / pyunits.s,
        )

        def rate_constant_eqn(b, j):
            temperature_smooth = smooth_max(
                b.solid_state_ref.temperature, 298.15 * pyunits.K, 1e-8
            )
            return b.k_rxn[j] == b._params.k0_rxn[j] * temperature_smooth * exp(
                -b._params.energy_activation[j]
                / (
                    pyunits.convert(
                        Constants.gas_constant,  # J/mol/K
                        to_units=pyunits.J / pyunits.mol / pyunits.K,
                    )
                    * temperature_smooth
                )
            )

        try:
            # Try to build constraint
            self.rate_constant_eqn = Constraint(
                self._params.rate_reaction_idx, rule=rate_constant_eqn
            )
        except AttributeError:
            # If constraint fails, clean up so that DAE can try again later
            self.del_component(self.k_rxn)
            self.del_component(self.rate_constant_eqn)
            raise

    # Equilibrium constant method
    def _Kequil_rxn(self):
        self.Kequil_rxn = Var(
            self._params.rate_reaction_idx,
            domain=Reals,
            initialize=1,
            doc="Rate constant",
            units=pyunits.mol / pyunits.m**3 / pyunits.s,
        )

        def Kequil_rxn_eqn(b, j):
            R = pyunits.convert(
                Constants.gas_constant,  # J/mol/K
                to_units=pyunits.J / pyunits.mol / pyunits.K,
            )
            temperature_smooth = smooth_max(
                b.solid_state_ref.temperature, 298.15 * pyunits.K, 1e-8
            )
            b.Kequil_rxn[j].set_value(
                value(
                    exp(
                        -b._params.dh_rxn[j] / (R * temperature_smooth)
                        + b._params.dS_rxn[j] / R
                    )
                    / b.gas_state_ref.pressure
                )
            )
            return b.Kequil_rxn[j] * b.gas_state_ref.pressure == exp(
                -b._params.dh_rxn[j] / (R * temperature_smooth)
                + b._params.dS_rxn[j] / R
            )

        try:
            # Try to build constraint
            self.Kequil_rxn_eqn = Constraint(
                self._params.rate_reaction_idx, rule=Kequil_rxn_eqn
            )
        except AttributeError:
            # If constraint fails, clean up so that DAE can try again later
            self.del_component(self.Kequil_rxn)
            self.del_component(self.Kequil_rxn_eqn)
            raise

    # General rate of reaction method
    def _reaction_rate(self):
        self.reaction_rate = Var(
            self._params.rate_reaction_idx,
            domain=Reals,
            initialize=0,
            doc="Gen. rate of reaction [mol_rxn/m3.s]",
            units=pyunits.mol / pyunits.m**3 / pyunits.s,
        )

        def rate_rule(b, r):
            if r == "R1":
                return b.reaction_rate[r] * b.Kequil_rxn[r] == b.k_rxn[r] * (
                    (
                        b.Kequil_rxn[r]
                        * b.gas_state_ref.pressure
                        * b.gas_state_ref.mole_frac_comp["H2O"]
                    )
                    - (
                        b.specie_concentration["H2O_s"]
                        * b.solid_state_ref.dens_mass_particle
                    )
                )
            elif r == "R2":
                return b.reaction_rate[r] * b.Kequil_rxn[r] == b.k_rxn[r] * (
                    b.Kequil_rxn[r]
                    * (
                        (
                            1
                            - 2
                            * (
                                b.specie_concentration["Car"]
                                * b.solid_state_ref.dens_mass_particle
                                / b._params.nv
                            )
                        )
                        ** 2
                    )
                    * (b.gas_state_ref.pressure * b.gas_state_ref.mole_frac_comp["CO2"])
                    - (
                        (
                            b.specie_concentration["Car"]
                            * b.solid_state_ref.dens_mass_particle
                            / b._params.nv
                        )
                        * (
                            (
                                b.specie_concentration["Car"]
                                * b.solid_state_ref.dens_mass_particle
                                / b._params.nv
                            )
                        )
                    )
                )

        try:
            # Try to build constraint
            self.gen_rate_expression = Constraint(
                self._params.rate_reaction_idx, rule=rate_rule
            )
        except AttributeError:
            # If constraint fails, clean up so that DAE can try again later
            self.del_component(self.reaction_rate)
            self.del_component(self.gen_rate_expression)
            raise

    def get_reaction_rate_basis(b):
        return MaterialFlowBasis.molar

    def model_check(blk):
        """
        Model checks for property block
        """
        # Check temperature bounds
        if value(blk.temperature) < blk.temperature.lb:
            _log.error("{} Temperature set below lower bound.".format(blk.name))
        if value(blk.temperature) > blk.temperature.ub:
            _log.error("{} Temperature set above upper bound.".format(blk.name))

    def calculate_scaling_factors(self):
        super().calculate_scaling_factors()

        # Scale some variables
        if hasattr(self, "Kequil_rxn"):
            # Set scaling for individual reactions (helps with convergence)
            Kequil_rxn = {}
            K_equil_scale = {}
            R = pyunits.convert(  # Gas constant
                Constants.gas_constant,  # J/mol/K
                to_units=pyunits.J / pyunits.mol / pyunits.K,
            )
            T_init = 380  # Temperature for initialization in K
            for r, v in self.Kequil_rxn.items():
                Kequil_rxn[r] = value(
                    exp(
                        -self._params.dh_rxn[r] / (R * T_init)
                        + self._params.dS_rxn[r] / R
                    )
                )
                K_equil_scale[r] = 1 / Kequil_rxn[r]
                if iscale.get_scaling_factor(v) is None:
                    sf = iscale.get_scaling_factor(
                        self.Kequil_rxn[r], default=K_equil_scale[r], warning=False
                    )
                    iscale.set_scaling_factor(v, sf)

        if hasattr(self, "k_rxn"):
            rate_constant_dict = self._params.k0_rxn
            for r, v in self.k_rxn.items():
                scale = 1 / value(rate_constant_dict[r])

                if iscale.get_scaling_factor(v) is None:
                    sf = iscale.get_scaling_factor(
                        self.k_rxn[r], default=scale, warning=False
                    )
                    iscale.set_scaling_factor(v, sf)

        if hasattr(self, "reaction_rate"):
            # Set scaling for individual reactions (helps with convergence)
            rxn_scale = {"R1": 1e-6, "R2": 1e-4}
            for r, v in self.reaction_rate.items():
                if iscale.get_scaling_factor(v) is None:
                    sf = iscale.get_scaling_factor(
                        self.reaction_rate[r], default=rxn_scale[r], warning=False
                    )
                    iscale.set_scaling_factor(v, sf)

        # Scale some constraints
        if self.is_property_constructed("specie_concentration_eqn"):
            for i, c in self.specie_concentration_eqn.items():
                iscale.constraint_scaling_transform(c, 1e3, overwrite=False)

        if self.is_property_constructed("Kequil_rxn_eqn"):
            for r, c in self.Kequil_rxn_eqn.items():
                iscale.constraint_scaling_transform(
                    c, iscale.get_scaling_factor(self.Kequil_rxn[r]), overwrite=True
                )

        if self.is_property_constructed("rate_constant_eqn"):
            for r, c in self.rate_constant_eqn.items():
                iscale.constraint_scaling_transform(
                    c, iscale.get_scaling_factor(self.k_rxn[r]), overwrite=True
                )

        if self.is_property_constructed("gen_rate_expression"):
            for r, c in self.gen_rate_expression.items():
                iscale.constraint_scaling_transform(
                    c, iscale.get_scaling_factor(self.reaction_rate[r]), overwrite=True
                )
