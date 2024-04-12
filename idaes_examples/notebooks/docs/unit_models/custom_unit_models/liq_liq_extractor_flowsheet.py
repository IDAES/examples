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
'''
    The below is an implementation of a flowsheet for liquid liquid extractor. 
    The unit model uses two property packages for two liquid fluids
'''
import pyomo.environ as pyo
import idaes.core
import idaes.models.unit_models
from idaes.core.solvers import get_solver
import idaes.logger as idaeslog
from pyomo.network import Arc
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.core.initialization import InitializationStatus
from idaes.core.initialization.block_triangularization import (
    BlockTriangularizationInitializer,
)
from organic_property import OrgPhase
from aqueous_property import AqPhase
from liquid_liquid_extractor import LiqExtraction

m = pyo.ConcreteModel()
m.fs = idaes.core.FlowsheetBlock(dynamic=False)
m.fs.org_properties = OrgPhase()
m.fs.aq_properties = AqPhase()

m.fs.lex = LiqExtraction(
    dynamic=False,
    has_pressure_change=False,
    organic_property_package=m.fs.org_properties,
    aqueous_property_package=m.fs.aq_properties,
)
m.fs.lex.organic_inlet.flow_vol.fix(80 * pyo.units.L / pyo.units.hour)
m.fs.lex.organic_inlet.temperature.fix(300 * pyo.units.K)
m.fs.lex.organic_inlet.pressure.fix(1 * pyo.units.atm)
m.fs.lex.organic_inlet.conc_mass_comp[0, "NaCl"].fix(1e-10 * pyo.units.g / pyo.units.L)
m.fs.lex.organic_inlet.conc_mass_comp[0, "KNO3"].fix(1e-10 * pyo.units.g / pyo.units.L)
m.fs.lex.organic_inlet.conc_mass_comp[0, "CaSO4"].fix(1e-10 * pyo.units.g / pyo.units.L)

m.fs.lex.aqueous_inlet.flow_vol.fix(100 * pyo.units.L / pyo.units.hour)
m.fs.lex.aqueous_inlet.temperature.fix(300 * pyo.units.K)
m.fs.lex.aqueous_inlet.pressure.fix(1 * pyo.units.atm)
m.fs.lex.aqueous_inlet.conc_mass_comp[0, "NaCl"].fix(0.15 * pyo.units.g / pyo.units.L)
m.fs.lex.aqueous_inlet.conc_mass_comp[0, "KNO3"].fix(0.2 * pyo.units.g / pyo.units.L)
m.fs.lex.aqueous_inlet.conc_mass_comp[0, "CaSO4"].fix(0.1 * pyo.units.g / pyo.units.L)

initializer = BlockTriangularizationInitializer()
initializer.initialize(m.fs.lex)

solver = get_solver()
results = solver.solve(m, tee=True)
