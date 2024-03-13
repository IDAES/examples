#################################################################################
# WaterTAP Copyright (c) 2020-2023, The Regents of the University of California,
# through Lawrence Berkeley National Laboratory, Oak Ridge National Laboratory,
# National Renewable Energy Laboratory, and National Energy Technology
# Laboratory (subject to receipt of any required approvals from the U.S. Dept.
# of Energy). All rights reserved.
#
# Please see the files COPYRIGHT.md and LICENSE.md for full copyright and license
# information, respectively. These files are also available online at the URL
# "https://github.com/watertap-org/watertap/"
#################################################################################
"""
Liquid-Liquid Extractor model which includes aqueous and organic phase outlets.

This is inspired from the anaerobic_digestor in watertap.

Assumptions:
     * Steady-state only
     * Liquid phase property package has a single phase named Liq
     * Aqueous phase property package has a single phase named Aq
     * Liquid and Aqueous phase properties need not have the same component lists

"""

# Import Pyomo libraries
from pyomo.common.config import ConfigBlock, ConfigValue, In, Bool
from pyomo.environ import (
    value,
    Constraint,
    check_optimal_termination,
)

# Import IDAES cores
from idaes.core import (
    ControlVolume0DBlock,
    declare_process_block_class,
    MaterialBalanceType,
    EnergyBalanceType,
    MaterialFlowBasis,
    MomentumBalanceType,
    UnitModelBlockData,
    useDefault,
)
from idaes.core.util.config import (
    is_physical_parameter_block,
    is_reaction_parameter_block,
)

import idaes.logger as idaeslog
from idaes.core.solvers import get_solver
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.core.util.exceptions import ConfigurationError, InitializationError

__author__ = "Javal Vyas"


@declare_process_block_class("LiqExtraction")
class LiqExtractionData(UnitModelBlockData):
    """
    LiqExtraction Unit Model Class
    """

    CONFIG = UnitModelBlockData.CONFIG()

    CONFIG.declare(
        "material_balance_type",
        ConfigValue(
            default=MaterialBalanceType.useDefault,
            domain=In(MaterialBalanceType),
            description="Material balance construction flag",
            doc="""Indicates what type of mass balance should be constructed,
**default** - MaterialBalanceType.useDefault.
**Valid values:** {
**MaterialBalanceType.useDefault - refer to property package for default
balance type
**MaterialBalanceType.none** - exclude material balances,
**MaterialBalanceType.componentPhase** - use phase component balances,
**MaterialBalanceType.componentTotal** - use total component balances,
**MaterialBalanceType.elementTotal** - use total element balances,
**MaterialBalanceType.total** - use total material balance.}""",
        ),
    )
    CONFIG.declare(
        "energy_balance_type",
        ConfigValue(
            default=EnergyBalanceType.useDefault,
            domain=In(EnergyBalanceType),
            description="Energy balance construction flag",
            doc="""Indicates what type of energy balance should be constructed,
**default** - EnergyBalanceType.useDefault.
**Valid values:** {
**EnergyBalanceType.useDefault - refer to property package for default
balance type
**EnergyBalanceType.none** - exclude energy balances,
**EnergyBalanceType.enthalpyTotal** - single enthalpy balance for material,
**EnergyBalanceType.enthalpyPhase** - enthalpy balances for each phase,
**EnergyBalanceType.energyTotal** - single energy balance for material,
**EnergyBalanceType.energyPhase** - energy balances for each phase.}""",
        ),
    )
    CONFIG.declare(
        "momentum_balance_type",
        ConfigValue(
            default=MomentumBalanceType.pressureTotal,
            domain=In(MomentumBalanceType),
            description="Momentum balance construction flag",
            doc="""Indicates what type of momentum balance should be constructed,
**default** - MomentumBalanceType.pressureTotal.
**Valid values:** {
**MomentumBalanceType.none** - exclude momentum balances,
**MomentumBalanceType.pressureTotal** - single pressure balance for material,
**MomentumBalanceType.pressurePhase** - pressure balances for each phase,
**MomentumBalanceType.momentumTotal** - single momentum balance for material,
**MomentumBalanceType.momentumPhase** - momentum balances for each phase.}""",
        ),
    )
    CONFIG.declare(
        "has_heat_transfer",
        ConfigValue(
            default=False,
            domain=Bool,
            description="Heat transfer term construction flag",
            doc="""Indicates whether terms for heat transfer should be constructed,
**default** - False.
**Valid values:** {
**True** - include heat transfer terms,
**False** - exclude heat transfer terms.}""",
        ),
    )
    CONFIG.declare(
        "has_pressure_change",
        ConfigValue(
            default=False,
            domain=Bool,
            description="Pressure change term construction flag",
            doc="""Indicates whether terms for pressure change should be
constructed,
**default** - False.
**Valid values:** {
**True** - include pressure change terms,
**False** - exclude pressure change terms.}""",
        ),
    )
    CONFIG.declare(
        "has_equilibrium_reactions",
        ConfigValue(
            default=False,
            domain=Bool,
            description="Equilibrium reaction construction flag",
            doc="""Indicates whether terms for equilibrium controlled reactions
should be constructed,
**default** - True.
**Valid values:** {
**True** - include equilibrium reaction terms,
**False** - exclude equilibrium reaction terms.}""",
        ),
    )
    CONFIG.declare(
        "has_phase_equilibrium",
        ConfigValue(
            default=False,
            domain=Bool,
            description="Phase equilibrium construction flag",
            doc="""Indicates whether terms for phase equilibrium should be
constructed,
**default** = False.
**Valid values:** {
**True** - include phase equilibrium terms
**False** - exclude phase equilibrium terms.}""",
        ),
    )
    CONFIG.declare(
        "has_heat_of_reaction",
        ConfigValue(
            default=False,
            domain=Bool,
            description="Heat of reaction term construction flag",
            doc="""Indicates whether terms for heat of reaction terms should be
constructed,
**default** - False.
**Valid values:** {
**True** - include heat of reaction terms,
**False** - exclude heat of reaction terms.}""",
        ),
    )
    CONFIG.declare(
        "liquid_property_package",
        ConfigValue(
            default=useDefault,
            domain=is_physical_parameter_block,
            description="Property package to use for liquid phase",
            doc="""Property parameter object used to define property calculations
for the liquid phase,
**default** - useDefault.
**Valid values:** {
**useDefault** - use default package from parent model or flowsheet,
**PropertyParameterObject** - a PropertyParameterBlock object.}""",
        ),
    )
    CONFIG.declare(
        "liquid_property_package_args",
        ConfigBlock(
            implicit=True,
            description="Arguments to use for constructing liquid phase properties",
            doc="""A ConfigBlock with arguments to be passed to liquid phase
property block(s) and used when constructing these,
**default** - None.
**Valid values:** {
see property package for documentation.}""",
        ),
    )
    CONFIG.declare(
        "aqueous_property_package",
        ConfigValue(
            default=useDefault,
            domain=is_physical_parameter_block,
            description="Property package to use for aqueous phase",
            doc="""Property parameter object used to define property calculations
for the aqueous phase,
**default** - useDefault.
**Valid values:** {
**useDefault** - use default package from parent model or flowsheet,
**PropertyParameterObject** - a PropertyParameterBlock object.}""",
        ),
    )
    CONFIG.declare(
        "aqueous_property_package_args",
        ConfigBlock(
            implicit=True,
            description="Arguments to use for constructing aqueous phase properties",
            doc="""A ConfigBlock with arguments to be passed to aqueous phase
property block(s) and used when constructing these,
**default** - None.
**Valid values:** {
see property package for documentation.}""",
        ),
    )
    CONFIG.declare(
        "reaction_package",
        ConfigValue(
            default=None,
            domain=is_reaction_parameter_block,
            description="Reaction package to use for control volume",
            doc="""Reaction parameter object used to define reaction calculations,
**default** - None.
**Valid values:** {
**None** - no reaction package,
**ReactionParameterBlock** - a ReactionParameterBlock object.}""",
        ),
    )
    CONFIG.declare(
        "reaction_package_args",
        ConfigBlock(
            implicit=True,
            description="Arguments to use for constructing reaction packages",
            doc="""A ConfigBlock with arguments to be passed to a reaction block(s)
and used when constructing these,
**default** - None.
**Valid values:** {
see reaction package for documentation.}""",
        ),
    )

    def build(self):
        """
        Begin building model (pre-DAE transformation).
        Args:
            None
        Returns:
            None
        """
        # Call UnitModel.build to setup dynamics
        super(LiqExtractionData, self).build()

        # Check phase lists match assumptions
        if self.config.aqueous_property_package.phase_list != ["Aq"]:
            raise ConfigurationError(
                f"{self.name} Liquid-Liquid Extractor model requires that the aquoues "
                f"phase property package have a single phase named 'Aq'"
            )
        if self.config.liquid_property_package.phase_list != ["Liq"]:
            raise ConfigurationError(
                f"{self.name} Liquid-Liquid Extractor model requires that the liquid "
                f"phase property package have a single phase named 'Liq'"
            )

        # Check for at least one common component in component lists
        if not any(
            j in self.config.aqueous_property_package.component_list
            for j in self.config.liquid_property_package.component_list
        ):
            raise ConfigurationError(
                f"{self.name} Liquid-Liquid Extractor model requires that the liquid "
                f"and aqueous phase property packages have at least one "
                f"common component."
            )

        self.liquid_phase = ControlVolume0DBlock(
            dynamic=self.config.dynamic,
            has_holdup=self.config.has_holdup,
            property_package=self.config.liquid_property_package,
            property_package_args=self.config.liquid_property_package_args,
        )

        self.liquid_phase.add_state_blocks(
            has_phase_equilibrium=self.config.has_phase_equilibrium
        )

        # Separate liquid and aqueous phases means that phase equilibrium will
        # be handled at the unit model level, thus has_phase_equilibrium is
        # False, but has_mass_transfer is True.

        self.liquid_phase.add_material_balances(
            balance_type=self.config.material_balance_type,
            has_rate_reactions=False,
            has_equilibrium_reactions=self.config.has_equilibrium_reactions,
            has_phase_equilibrium=self.config.has_phase_equilibrium,
            has_mass_transfer=True,
        )

        self.liquid_phase.add_energy_balances(
            balance_type=self.config.energy_balance_type,
            has_heat_transfer=False,
            has_enthalpy_transfer=False,
        )

        self.liquid_phase.add_momentum_balances(
            balance_type=self.config.momentum_balance_type,
            has_pressure_change=self.config.has_pressure_change,
        )

        # ---------------------------------------------------------------------

        self.aqueous_phase = ControlVolume0DBlock(
            dynamic=self.config.dynamic,
            has_holdup=self.config.has_holdup,
            property_package=self.config.aqueous_property_package,
            property_package_args=self.config.aqueous_property_package_args,
        )

        self.aqueous_phase.add_state_blocks(
            has_phase_equilibrium=self.config.has_phase_equilibrium
        )

        # Separate liquid and aqueous phases means that phase equilibrium will
        # be handled at the unit model level, thus has_phase_equilibrium is
        # False, but has_mass_transfer is True.

        self.aqueous_phase.add_material_balances(
            balance_type=self.config.material_balance_type,
            has_rate_reactions=False,
            has_phase_equilibrium=self.config.has_phase_equilibrium,
            has_mass_transfer=True,
        )

        self.aqueous_phase.add_energy_balances(
            balance_type=self.config.energy_balance_type,
            has_heat_transfer=False,
            has_enthalpy_transfer=False,
        )

        self.aqueous_phase.add_momentum_balances(
            balance_type=self.config.momentum_balance_type,
            has_pressure_change=self.config.has_pressure_change,
        )

        self.aqueous_phase.add_geometry()
       
        # ---------------------------------------------------------------------
        # Check flow basis is compatable
        t_init = self.flowsheet().time.first()
        if (
            self.aqueous_phase.properties_out[t_init].get_material_flow_basis()
            != self.liquid_phase.properties_out[t_init].get_material_flow_basis()
        ):
            raise ConfigurationError(
                f"{self.name} aqueous and liquid property packages must use the "
                f"same material flow basis."
            )

        self.liquid_phase.add_geometry()

        # Add Ports
        self.add_inlet_port(
            name="liquid_inlet", block=self.liquid_phase, doc="Liquid feed"
        )
        self.add_inlet_port(
            name="aqueous_inlet", block=self.aqueous_phase, doc="Aqueous feed"
        )
        self.add_outlet_port(
            name="liquid_outlet", block=self.liquid_phase, doc="Bottoms stream"
        )
        self.add_outlet_port(
            name="aqueous_outlet",
            block=self.aqueous_phase,
            doc="Aqueous stream from reactor",
        )

        # ---------------------------------------------------------------------
        # Add unit level constraints
        # First, need the union and intersection of component lists
        all_comps = (
            self.aqueous_phase.properties_out.component_list
            | self.liquid_phase.properties_out.component_list
        )
        common_comps = (
            self.aqueous_phase.properties_out.component_list
            & self.liquid_phase.properties_out.component_list
        )

        # Get units for unit conversion
        aunits = self.config.aqueous_property_package.get_metadata().get_derived_units
        lunits = self.config.liquid_property_package.get_metadata().get_derived_units
        flow_basis = self.aqueous_phase.properties_out[t_init].get_material_flow_basis()

        if flow_basis == MaterialFlowBasis.mass:
            fb = "flow_mass"
        elif flow_basis == MaterialFlowBasis.molar:
            fb = "flow_mole"
        else:
            raise ConfigurationError(
                f"{self.name} Liquid-Liquid Extractor only supports mass "
                f"basis for MaterialFlowBasis."
            )

        # Material balances
        def rule_material_aq_balance(self, t, j):
            if j in common_comps:
                return self.aqueous_phase.mass_transfer_term[
                    t, "Aq", j
                ] == -self.liquid_phase.config.property_package.diffusion_factor[j] * (
                    self.aqueous_phase.properties_in[t].get_mass_comp(j)
                    / self.aqueous_phase.properties_in[t].get_flow_rate()
                )
            elif j in self.liquid_phase.properties_out.component_list:
                # No mass transfer term
                # Set Liquid flowrate to an arbitary small value
                return self.liquid_phase.mass_transfer_term[t, "Liq", j] == 0 * lunits(
                    fb
                )
            elif j in self.aqueous_phase.properties_out.component_list:
                # No mass transfer term
                # Set aqueous flowrate to an arbitary small value
                return self.aqueous_phase.mass_transfer_term[t, "Aq", j] == 0 * aunits(
                    fb
                )

        self.material_aq_balance = Constraint(
            self.flowsheet().time,
            self.aqueous_phase.properties_out.component_list,
            rule=rule_material_aq_balance,
            doc="Unit level material balances for Aq",
        )

        def rule_material_liq_balance(self, t, j):
            print(t)
            if j in common_comps:
                return (
                    self.liquid_phase.mass_transfer_term[t, "Liq", j]
                    == -self.aqueous_phase.mass_transfer_term[t, "Aq", j]
                )
            else:
                # No mass transfer term
                # Set Liquid flowrate to an arbitary small value
                return self.liquid_phase.mass_transfer_term[t, "Liq", j] == 0 * aunits(
                    fb
                )

        self.material_liq_balance = Constraint(
            self.flowsheet().time,
            self.liquid_phase.properties_out.component_list,
            rule=rule_material_liq_balance,
            doc="Unit level material balances Liq",
        )

    def initialize_build(
        self,
        liquid_state_args=None,
        aqueous_state_args=None,
        outlvl=idaeslog.NOTSET,
        solver=None,
        optarg=None,
    ):
        """
        Initialization routine for Liquid Liquid Extractor unit model.

        Keyword Arguments:
            liquid_state_args : a dict of arguments to be passed to the
                liquid property packages to provide an initial state for
                initialization (see documentation of the specific property
                package) (default = none).
            aqueous_state_args : a dict of arguments to be passed to the
                aqueous property package to provide an initial state for
                initialization (see documentation of the specific property
                package) (default = none).
            outlvl : sets output level of initialization routine
            optarg : solver options dictionary object (default=None, use
                     default solver options)
            solver : str indicating which solver to use during
                     initialization (default = None, use default IDAES solver)

        Returns:
            None
        """
        if optarg is None:
            optarg = {}

        # Check DOF
        if degrees_of_freedom(self) != 0:
            raise InitializationError(
                f"{self.name} degrees of freedom were not 0 at the beginning "
                f"of initialization. DoF = {degrees_of_freedom(self)}"
            )

        # Set solver options
        init_log = idaeslog.getInitLogger(self.name, outlvl, tag="unit")
        solve_log = idaeslog.getSolveLogger(self.name, outlvl, tag="unit")

        solverobj = get_solver(solver, optarg)

        # ---------------------------------------------------------------------
        # Initialize liquid phase control volume block
        flags = self.liquid_phase.initialize(
            outlvl=outlvl,
            optarg=optarg,
            solver=solver,
            state_args=liquid_state_args,
            hold_state=True,
        )

        init_log.info_high("Initialization Step 1 Complete.")
        # ---------------------------------------------------------------------
        # Initialize aqueous phase state block
        if aqueous_state_args is None:
            t_init = self.flowsheet().time.first()
            aqueous_state_args = {}
            aq_state_vars = self.aqueous_phase[t_init].define_state_vars()

            liq_state = self.liquid_phase.properties_out[t_init]

            # Check for unindexed state variables
            for sv in aq_state_vars:
                if "flow" in sv:
                    aqueous_state_args[sv] = value(getattr(liq_state, sv))
                elif "conc" in sv:
                    # Flow is indexed by component
                    aqueous_state_args[sv] = {}
                    for j in aq_state_vars[sv]:
                        if j in liq_state.component_list:
                            aqueous_state_args[sv][j] = 1e3 * value(
                                getattr(liq_state, sv)[j]
                            )
                        else:
                            aqueous_state_args[sv][j] = 0.5

                elif "pressure" in sv:
                    aqueous_state_args[sv] = 1 * value(getattr(liq_state, sv))

                else:
                    aqueous_state_args[sv] = value(getattr(liq_state, sv))

        self.aqueous_phase.initialize(
            outlvl=outlvl,
            optarg=optarg,
            solver=solver,
            state_args=aqueous_state_args,
            hold_state=False,
        )

        init_log.info_high("Initialization Step 2 Complete.")

        # ---------------------------------------------------------------------
        # # Solve unit model
        with idaeslog.solver_log(solve_log, idaeslog.DEBUG) as slc:
            results = solverobj.solve(self, tee=slc.tee)
            if not check_optimal_termination(results):
                init_log.warning(
                    f"Trouble solving unit model {self.name}, trying one more time"
                )
                results = solverobj.solve(self, tee=slc.tee)
        init_log.info_high(
            "Initialization Step 3 {}.".format(idaeslog.condition(results))
        )

        # ---------------------------------------------------------------------
        # Release Inlet state
        self.liquid_phase.release_state(flags, outlvl)
        self.aqueous_phase.release_state(flags, outlvl)

        if not check_optimal_termination(results):
            raise InitializationError(
                f"{self.name} failed to initialize successfully. Please check "
                f"the output logs for more information."
            )

        init_log.info("Initialization Complete: {}".format(idaeslog.condition(results)))
