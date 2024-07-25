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
Liquid-Liquid Extractor model which includes aqueous and organic phase outlets.

This is inspired from the anaerobic_digester in watertap.

Assumptions:
     * Steady-state only
     * Organic phase property package has a single phase named Org
     * Aqueous phase property package has a single phase named Aq
     * Organic and Aqueous phase properties need not have the same component lists

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
        "organic_property_package",
        ConfigValue(
            default=useDefault,
            domain=is_physical_parameter_block,
            description="Property package to use for organic phase",
            doc="""Property parameter object used to define property calculations
                    for the organic phase,
                    **default** - useDefault.
                    **Valid values:** {
                    **useDefault** - use default package from parent model or flowsheet,
                    **PropertyParameterObject** - a PropertyParameterBlock object.}""",
        ),
    )
    CONFIG.declare(
        "organic_property_package_args",
        ConfigBlock(
            implicit=True,
            description="Arguments to use for constructing organic phase properties",
            doc="""A ConfigBlock with arguments to be passed to organic phase
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

    def build(self):
        """
        Begin building model (pre-DAE transformation).
        Args:
            None
        Returns:
            None
        """
        # Call UnitModel.build to setup dynamics
        super().build()

        # Check phase lists match assumptions
        if self.config.aqueous_property_package.phase_list != ["Aq"]:
            raise ConfigurationError(
                f"{self.name} Liquid-Liquid Extractor model requires that the aqueous "
                f"phase property package have a single phase named 'Aq'"
            )
        if self.config.organic_property_package.phase_list != ["Org"]:
            raise ConfigurationError(
                f"{self.name} Liquid-Liquid Extractor model requires that the organic "
                f"phase property package have a single phase named 'Org'"
            )

        # Check for at least one common component in component lists
        if not any(
            j in self.config.aqueous_property_package.component_list
            for j in self.config.organic_property_package.component_list
        ):
            raise ConfigurationError(
                f"{self.name} Liquid-Liquid Extractor model requires that the organic "
                f"and aqueous phase property packages have at least one "
                f"common component."
            )

        self.organic_phase = ControlVolume0DBlock(
            dynamic=self.config.dynamic,
            property_package=self.config.organic_property_package,
            property_package_args=self.config.organic_property_package_args,
        )

        self.organic_phase.add_state_blocks(
            has_phase_equilibrium=self.config.has_phase_equilibrium
        )

        # Separate organic and aqueous phases means that phase equilibrium will
        # be handled at the unit model level, thus has_phase_equilibrium is
        # False, but has_mass_transfer is True.

        self.organic_phase.add_material_balances(
            balance_type=self.config.material_balance_type,
            has_phase_equilibrium=self.config.has_phase_equilibrium,
            has_mass_transfer=True,
        )
        # ---------------------------------------------------------------------

        self.aqueous_phase = ControlVolume0DBlock(
            dynamic=self.config.dynamic,
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
            # has_rate_reactions=False,
            has_phase_equilibrium=self.config.has_phase_equilibrium,
            has_mass_transfer=True,
        )

        self.aqueous_phase.add_geometry()

        # ---------------------------------------------------------------------
        # Check flow basis is compatible
        t_init = self.flowsheet().time.first()
        if (
            self.aqueous_phase.properties_out[t_init].get_material_flow_basis()
            != self.organic_phase.properties_out[t_init].get_material_flow_basis()
        ):
            raise ConfigurationError(
                f"{self.name} aqueous and organic property packages must use the "
                f"same material flow basis."
            )

        self.organic_phase.add_geometry()

        # Add Ports
        self.add_inlet_port(
            name="organic_inlet", block=self.organic_phase, doc="Organic feed"
        )
        self.add_inlet_port(
            name="aqueous_inlet", block=self.aqueous_phase, doc="Aqueous feed"
        )
        self.add_outlet_port(
            name="organic_outlet", block=self.organic_phase, doc="Organic outlet"
        )
        self.add_outlet_port(
            name="aqueous_outlet",
            block=self.aqueous_phase,
            doc="Aqueous outlet",
        )

        # ---------------------------------------------------------------------
        # Add unit level constraints
        # First, need the union and intersection of component lists
        all_comps = (
            self.aqueous_phase.properties_out.component_list
            | self.organic_phase.properties_out.component_list
        )
        common_comps = (
            self.aqueous_phase.properties_out.component_list
            & self.organic_phase.properties_out.component_list
        )

        # Get units for unit conversion
        aunits = self.config.aqueous_property_package.get_metadata().get_derived_units
        ounits = self.config.organic_property_package.get_metadata().get_derived_units
        flow_basis = self.aqueous_phase.properties_out[t_init].get_material_flow_basis()

        if flow_basis == MaterialFlowBasis.mass:
            fb = "flow_mass"
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
                ] == -self.organic_phase.config.property_package.diffusion_factor[j] * (
                    self.aqueous_phase.properties_in[t].get_material_flow_terms("Aq", j)
                )
            elif j in self.organic_phase.properties_out.component_list:
                # No mass transfer term
                # Set organic flowrate to an arbitrary small value
                return self.organic_phase.mass_transfer_term[t, "Org", j] == 0 * ounits(
                    fb
                )
            elif j in self.aqueous_phase.properties_out.component_list:
                # No mass transfer term
                # Set aqueous flowrate to an arbitrary small value
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
            if j in common_comps:
                return (
                    self.organic_phase.mass_transfer_term[t, "Org", j]
                    == -self.aqueous_phase.mass_transfer_term[t, "Aq", j]
                )
            else:
                # No mass transfer term
                # Set organic flowrate to an arbitrary small value
                return self.organic_phase.mass_transfer_term[t, "Org", j] == 0 * aunits(
                    fb
                )

        self.material_org_balance = Constraint(
            self.flowsheet().time,
            self.organic_phase.properties_out.component_list,
            rule=rule_material_liq_balance,
            doc="Unit level material balances Org",
        )
