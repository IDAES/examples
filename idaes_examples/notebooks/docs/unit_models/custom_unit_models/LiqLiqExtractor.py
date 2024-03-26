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
from Org_property import OrgPhase
from Aq_property import AqPhase
from liquid_extraction import LiqExtraction

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
m.fs.lex.organic_inlet.conc_mass_comp[0, "NaCl"].fix(0 * pyo.units.g / pyo.units.L)
m.fs.lex.organic_inlet.conc_mass_comp[0, "KNO3"].fix(0 * pyo.units.g / pyo.units.L)
m.fs.lex.organic_inlet.conc_mass_comp[0, "CaSO4"].fix(0 * pyo.units.g / pyo.units.L)

m.fs.lex.aqueous_inlet.flow_vol.fix(100 * pyo.units.L / pyo.units.hour)
m.fs.lex.aqueous_inlet.temperature.fix(300 * pyo.units.K)
m.fs.lex.aqueous_inlet.pressure.fix(1 * pyo.units.atm)
m.fs.lex.aqueous_inlet.conc_mass_comp[0, "NaCl"].fix(0.15 * pyo.units.g / pyo.units.L)
m.fs.lex.aqueous_inlet.conc_mass_comp[0, "KNO3"].fix(0.2 * pyo.units.g / pyo.units.L)
m.fs.lex.aqueous_inlet.conc_mass_comp[0, "CaSO4"].fix(0.1 * pyo.units.g / pyo.units.L)

print(degrees_of_freedom(m))

initializer = BlockTriangularizationInitializer()
initializer.initialize(m.fs.lex)
assert initializer.summary[m.fs.lex]["status"] == InitializationStatus.Ok

solver = get_solver()
results = solver.solve(m, tee=True)


# m.fs.display()
# m.fs.pprint()
m.fs.lex.organic_inlet.flow_vol.display()
m.fs.lex.aqueous_inlet.flow_vol.display()
m.fs.lex.aqueous_inlet.conc_mass_comp.display()
m.fs.lex.organic_inlet.conc_mass_comp.display()
m.fs.lex.aqueous_inlet.conc_mass_comp.display()
m.fs.lex.organic_outlet.conc_mass_comp.display()
m.fs.lex.aqueous_outlet.conc_mass_comp.display()
m.fs.lex.aqueous_outlet.flow_vol.display()
m.fs.lex.organic_outlet.flow_vol.display()
pyo.assert_optimal_termination(results)
