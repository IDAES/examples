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
Example reaction property package for the hydrodealkylation of
toluene to form benzene, along with the side reaction to form diphenyl.

This package assumes a single, ideal vapor phase with rate based conversion of
toluene to benzene and an equilibrium side-reaction of benzene to diphenyl.
"""

# Import Pyomo libraries
from pyomo.environ import (Constraint,
                           exp,
                           Param,
                           Set,
                           units as pyunits,
                           Var)

# Import IDAES cores
from idaes.core import (declare_process_block_class,
                        MaterialFlowBasis,
                        ReactionParameterBlock,
                        ReactionBlockDataBase,
                        ReactionBlockBase)
from idaes.core.util.constants import Constants as const
import idaes.logger as idaeslog

# Set up logger
_log = idaeslog.getLogger(__name__)


@declare_process_block_class("HDAReactionParameterBlock")
class HDAReactionParameterData(ReactionParameterBlock):
    """
    Reaction Parameter Block Class
    """

    def build(self):
        '''
        Callable method for Block construction.
        '''
        super(HDAReactionParameterData, self).build()

        self._reaction_block_class = HDAReactionBlock

        # Rate Reaction Index
        self.rate_reaction_idx = Set(initialize=["R1"])

        # Rate Reaction Stoichiometry
        self.rate_reaction_stoichiometry = {("R1", "Vap", "benzene"): 1,
                                            ("R1", "Vap", "toluene"): -1,
                                            ("R1", "Vap", "hydrogen"): -1,
                                            ("R1", "Vap", "methane"): 1,
                                            ("R1", "Vap", "diphenyl"): 0}

        # Equilibrium Reaction Index
        self.equilibrium_reaction_idx = Set(initialize=["E1"])

        # Equilibrium Reaction Stoichiometry
        self.equilibrium_reaction_stoichiometry = {
            ("E1", "Vap", "benzene"): -2,
            ("E1", "Vap", "toluene"): 0,
            ("E1", "Vap", "hydrogen"): 1,
            ("E1", "Vap", "methane"): 0,
            ("E1", "Vap", "diphenyl"): 1}

        # Arrhenius Constant
        self.arrhenius = Param(
            default=1.25e-9,
            doc="Arrhenius constant",
            units=pyunits.mol/pyunits.m**3/pyunits.s/pyunits.Pa**2)

        # Activation Energy
        self.energy_activation = Param(default=3800,
                                       doc="Activation energy",
                                       units=pyunits.J/pyunits.mol)

    @classmethod
    def define_metadata(cls, obj):
        obj.add_properties({
                'k_rxn': {'method': None},
                'reaction_rate': {'method': None}
                })
        obj.add_default_units({'time': pyunits.s,
                               'length': pyunits.m,
                               'mass': pyunits.kg,
                               'amount': pyunits.mol,
                               'temperature': pyunits.K})


class _HDAReactionBlock(ReactionBlockBase):
    """
    This Class contains methods which should be applied to Reaction Blocks as a
    whole, rather than individual elements of indexed Reaction Blocks.
    """
    def initialize(blk, outlvl=idaeslog.NOTSET, **kwargs):
        '''
        Initialization routine for reaction package.

        Keyword Arguments:
            outlvl : sets output level of initialization routine

        Returns:
            None
        '''
        init_log = idaeslog.getInitLogger(blk.name, outlvl, tag="properties")
        init_log.info('Initialization Complete.')


@declare_process_block_class("HDAReactionBlock",
                             block_class=_HDAReactionBlock)
class HDAReactionBlockData(ReactionBlockDataBase):
    """
    An example reaction package for saponification of ethyl acetate
    """

    def build(self):
        """
        Callable method for Block construction
        """
        super(HDAReactionBlockData, self).build()

        self.k_rxn = Var(
            initialize=7e-10,
            doc="Rate constant",
            units=pyunits.mol/pyunits.m**3/pyunits.s/pyunits.Pa**2)

        self.k_eq = Param(initialize=10000,
                          doc="Equlibrium constant",
                          units=pyunits.Pa)

        self.reaction_rate = Var(self.params.rate_reaction_idx,
                                 initialize=0,
                                 doc="Rate of reaction",
                                 units=pyunits.mol/pyunits.m**3/pyunits.s)

        self.arrhenius_equation = Constraint(
            expr=self.k_rxn == self.params.arrhenius * exp(
                -self.params.energy_activation /
                (const.gas_constant*self.state_ref.temperature)))

        def rate_rule(b, r):
            return b.reaction_rate[r] == (
                        b.k_rxn *
                        b.state_ref.mole_frac_comp["toluene"] *
                        b.state_ref.mole_frac_comp["hydrogen"] *
                        b.state_ref.pressure**2)
        self.rate_expression = Constraint(self.params.rate_reaction_idx,
                                          rule=rate_rule)

        # Equilibrium constraint
        self.equilibrium_constraint = Constraint(
            expr=self.k_eq *
            self.state_ref.mole_frac_comp["benzene"] *
            self.state_ref.pressure ==
            self.state_ref.mole_frac_comp["diphenyl"] *
            self.state_ref.mole_frac_comp["hydrogen"] *
            self.state_ref.pressure**2)

    def get_reaction_rate_basis(b):
        return MaterialFlowBasis.molar
