from pyomo.environ import (
    Constraint,
    Var,
    ConcreteModel,
    Expression,
    Objective,
    TransformationFactory,
    value,
)
from pyomo.network import Arc, SequentialDecomposition

from idaes.core import FlowsheetBlock

from idaes.models.unit_models import (
    PressureChanger,
    Mixer,
    Separator as Splitter,
    Heater,
    StoichiometricReactor,
    Feed,
    Product,
)

from idaes.core.util.exceptions import InitializationError
import idaes.logger as idaeslog

# Todo: import flash model from idaes.models.unit_models

# Todo: import flash model from idaes.models.unit_models
from idaes.models.unit_models import Flash

from idaes.models.unit_models.pressure_changer import ThermodynamicAssumption
from idaes.core.util.model_statistics import degrees_of_freedom

from idaes.core.solvers import get_solver

from idaes.models.properties.modular_properties.base.generic_property import (
    GenericParameterBlock,
)
from idaes.models.properties.modular_properties.base.generic_reaction import (
    GenericReactionParameterBlock,
)
from idaes_examples.mod.hda.hda_ideal_VLE_modular import thermo_config
from idaes_examples.mod.hda.hda_reaction_modular import reaction_config

m = ConcreteModel()
m.fs = FlowsheetBlock(dynamic=False)

m.fs.thermo_params = GenericParameterBlock(**thermo_config)
m.fs.reaction_params = GenericReactionParameterBlock(
    property_package=m.fs.thermo_params, **reaction_config
)

m.fs.I101 = Feed(property_package=m.fs.thermo_params)
m.fs.I102 = Feed(property_package=m.fs.thermo_params)

m.fs.M101 = Mixer(
    property_package=m.fs.thermo_params,
    num_inlets=3,
)

m.fs.H101 = Heater(
    property_package=m.fs.thermo_params,
    has_pressure_change=False,
    has_phase_equilibrium=True,
)

m.fs.R101 = StoichiometricReactor(
    property_package=m.fs.thermo_params,
    reaction_package=m.fs.reaction_params,
    has_heat_of_reaction=True,
    has_heat_transfer=True,
    has_pressure_change=False,
)

m.fs.F101 = Flash(
    property_package=m.fs.thermo_params,
    has_heat_transfer=True,
    has_pressure_change=True,
)

m.fs.S101 = Splitter(
    property_package=m.fs.thermo_params,
    ideal_separation=False,
    outlet_list=["purge", "recycle"],
)

m.fs.C101 = PressureChanger(
    property_package=m.fs.thermo_params,
    compressor=True,
    thermodynamic_assumption=ThermodynamicAssumption.isothermal,
)

m.fs.F102 = Flash(
    property_package=m.fs.thermo_params,
    has_heat_transfer=True,
    has_pressure_change=True,
)

m.fs.P101 = Product(property_package=m.fs.thermo_params)
m.fs.P102 = Product(property_package=m.fs.thermo_params)
m.fs.P103 = Product(property_package=m.fs.thermo_params)

m.fs.s01 = Arc(source=m.fs.I101.outlet, destination=m.fs.M101.inlet_1)
m.fs.s02 = Arc(source=m.fs.I102.outlet, destination=m.fs.M101.inlet_2)
m.fs.s03 = Arc(source=m.fs.M101.outlet, destination=m.fs.H101.inlet)
m.fs.s04 = Arc(source=m.fs.H101.outlet, destination=m.fs.R101.inlet)
m.fs.s05 = Arc(source=m.fs.R101.outlet, destination=m.fs.F101.inlet)
m.fs.s06 = Arc(source=m.fs.F101.vap_outlet, destination=m.fs.S101.inlet)
m.fs.s07 = Arc(source=m.fs.F101.liq_outlet, destination=m.fs.F102.inlet)
m.fs.s08 = Arc(source=m.fs.S101.recycle, destination=m.fs.C101.inlet)
m.fs.s09 = Arc(source=m.fs.C101.outlet, destination=m.fs.M101.inlet_3)
m.fs.s10 = Arc(source=m.fs.F102.vap_outlet, destination=m.fs.P101.inlet)
m.fs.s11 = Arc(source=m.fs.F102.liq_outlet, destination=m.fs.P102.inlet)
m.fs.s12 = Arc(source=m.fs.S101.purge, destination=m.fs.P103.inlet)

TransformationFactory("network.expand_arcs").apply_to(m)

m.fs.purity = Expression(
    expr=m.fs.F102.control_volume.properties_out[0].flow_mol_phase_comp[
        "Vap", "benzene"
    ]
    / (
        m.fs.F102.control_volume.properties_out[0].flow_mol_phase_comp["Vap", "benzene"]
        + m.fs.F102.control_volume.properties_out[0].flow_mol_phase_comp[
            "Vap", "toluene"
        ]
    )
)

m.fs.cooling_cost = Expression(
    expr=0.212e-7 * (-m.fs.F101.heat_duty[0]) + 0.212e-7 * (-m.fs.R101.heat_duty[0])
)

m.fs.heating_cost = Expression(
    expr=2.2e-7 * m.fs.H101.heat_duty[0] + 1.9e-7 * m.fs.F102.heat_duty[0]
)

m.fs.operating_cost = Expression(
    expr=(3600 * 24 * 365 * (m.fs.heating_cost + m.fs.cooling_cost))
)

assert degrees_of_freedom(m) == 29

F_liq_toluene = 0.30
F_liq_non_zero = 1e-5

F_vap_I101 = F_liq_non_zero * 4
F_liq_I101 = F_liq_toluene + F_liq_non_zero

m.fs.I101.flow_mol_phase[0, "Vap"].fix(F_vap_I101)
m.fs.I101.flow_mol_phase[0, "Liq"].fix(F_liq_I101)
m.fs.I101.mole_frac_phase_comp[0, "Vap", "benzene"].fix(F_liq_non_zero / F_vap_I101)
m.fs.I101.mole_frac_phase_comp[0, "Vap", "toluene"].fix(F_liq_non_zero / F_vap_I101)
m.fs.I101.mole_frac_phase_comp[0, "Vap", "hydrogen"].fix(F_liq_non_zero / F_vap_I101)
m.fs.I101.mole_frac_phase_comp[0, "Vap", "methane"].fix(F_liq_non_zero / F_vap_I101)
m.fs.I101.mole_frac_phase_comp[0, "Liq", "benzene"].fix(F_liq_non_zero / F_liq_I101)
m.fs.I101.mole_frac_phase_comp[0, "Liq", "toluene"].fix(F_liq_toluene / F_liq_I101)
m.fs.I101.temperature.fix(303.2)
m.fs.I101.pressure.fix(350000)

F_vap_hydrogen = 0.30
F_vap_methane = 0.020

F_vap_non_zero = 1e-5
F_liq_non_zero = F_vap_non_zero

F_vap_I102 = F_vap_hydrogen + F_vap_methane + 2 * F_vap_non_zero
F_liq_I102 = 2 * F_vap_non_zero

m.fs.I102.flow_mol_phase[0, "Vap"].fix(F_vap_I102)
m.fs.I102.flow_mol_phase[0, "Liq"].fix(F_liq_I102)
m.fs.I102.mole_frac_phase_comp[0, "Vap", "benzene"].fix(F_vap_non_zero / F_vap_I102)
m.fs.I102.mole_frac_phase_comp[0, "Vap", "toluene"].fix(F_vap_non_zero / F_vap_I102)
m.fs.I102.mole_frac_phase_comp[0, "Vap", "hydrogen"].fix(F_vap_hydrogen / F_vap_I102)
m.fs.I102.mole_frac_phase_comp[0, "Vap", "methane"].fix(F_vap_methane / F_vap_I102)
m.fs.I102.mole_frac_phase_comp[0, "Liq", "benzene"].fix(F_liq_non_zero / F_liq_I102)
m.fs.I102.mole_frac_phase_comp[0, "Liq", "toluene"].fix(F_liq_non_zero / F_liq_I102)

m.fs.I102.temperature.fix(303.2)
m.fs.I102.pressure.fix(350000)

m.fs.H101.outlet.temperature.fix(600)

m.fs.R101.conversion = Var(initialize=0.75, bounds=(0, 1))

m.fs.R101.conv_constraint = Constraint(
    expr=m.fs.R101.conversion
    * (m.fs.R101.control_volume.properties_in[0].flow_mol_phase_comp["Vap", "toluene"])
    == (
        m.fs.R101.control_volume.properties_in[0].flow_mol_phase_comp["Vap", "toluene"]
        - m.fs.R101.control_volume.properties_out[0].flow_mol_phase_comp[
            "Vap", "toluene"
        ]
    )
)

m.fs.R101.conversion.fix(0.75)
m.fs.R101.heat_duty.fix(0)

m.fs.F101.vap_outlet.temperature.fix(325.0)
m.fs.F101.deltaP.fix(0)

m.fs.F102.vap_outlet.temperature.fix(375)
m.fs.F102.deltaP.fix(-200000)

m.fs.S101.split_fraction[0, "purge"].fix(0.2)
m.fs.C101.outlet.pressure.fix(350000)

seq = SequentialDecomposition()
seq.options.select_tear_method = "heuristic"
seq.options.tear_method = "Wegstein"
seq.options.iterLim = 3

# Using the SD tool
G = seq.create_graph(m)
heuristic_tear_set = seq.tear_set_arcs(G, method="heuristic")
order = seq.calculation_order(G)

for o in heuristic_tear_set:
    print(o.name)

for o in order:
    print(o[0].name)

tear_guesses = {
    "flow_mol_phase": {
        (0, "Liq"): F_liq_I101,
        (0, "Vap"): F_vap_I102,
    },
    "mole_frac_phase_comp": {
        (0, "Liq", "benzene"): 1e-5 / F_liq_I101,
        (0, "Liq", "toluene"): 0.30 / F_liq_I101,
        (0, "Vap", "benzene"): 1e-5 / F_vap_I102,
        (0, "Vap", "toluene"): 1e-5 / F_vap_I102,
        (0, "Vap", "methane"): 0.02 / F_vap_I102,
        (0, "Vap", "hydrogen"): 0.30 / F_vap_I102,
    },
    "temperature": {0: 303},
    "pressure": {0: 350000},
}

# Pass the tear_guess to the SD tool
seq.set_guesses_for(m.fs.H101.inlet, tear_guesses)


def function(unit):
    try:
        initializer = unit.default_initializer()
        initializer.initialize(unit, output_level=idaeslog.INFO)
    except InitializationError:
        solver = get_solver()
        solver.solve(unit)


seq.run(m, function)

# from idaes.core.util.initialization import propagate_state
#
# print(f"The DOF is {degrees_of_freedom(m)} initially")
# m.fs.s03_expanded.deactivate()
# print(f"The DOF is {degrees_of_freedom(m)} after deactivating the tear stream")
#
# tear_guesses = {
#     "flow_mol_phase": {
#         (0, "Liq"): F_liq_I101,
#         (0, "Vap"): F_vap_I102,
#
#     },
#     "mole_frac_phase_comp": {
#         (0, "Liq", "benzene"): 1e-5 / F_liq_I101,
#         (0, "Liq", "toluene"): 0.30 / F_liq_I101,
#         (0, "Vap", "benzene"): 1e-5 / F_vap_I102,
#         (0, "Vap", "toluene"): 1e-5 / F_vap_I102,
#         (0, "Vap", "methane"): 0.02 / F_vap_I102,
#         (0, "Vap", "hydrogen"): 0.30 / F_vap_I102,
#     },
#     "temperature": {0: 303},
#     "pressure": {0: 350000},
# }
#
# for k, v in tear_guesses.items():
#     for k1, v1 in v.items():
#         getattr(m.fs.s03.destination, k)[k1].fix(v1)
#
# DOF_initial = degrees_of_freedom(m)
#
# print(f"The DOF is {degrees_of_freedom(m)} after setting the tear stream")
#
# m.fs.H101.default_initializer().initialize(m.fs.H101)
# propagate_state(m.fs.s04)  # Establish connection between Heater and Reactor
# m.fs.R101.default_initializer().initialize(m.fs.R101)  # Initialize Reactor
# propagate_state(m.fs.s05)  # Establish connection between Reactor and First Flash Unit
# m.fs.F101.default_initializer().initialize(m.fs.F101)  # Initialize First Flash Unit
# propagate_state(m.fs.s06)  # Establish connection between First Flash Unit and Splitter
# propagate_state(m.fs.s07)
# m.fs.S101.default_initializer().initialize(m.fs.S101)  # Initialize Splitter
# propagate_state(m.fs.s08)  # Establish connection between Splitter and Compressor
# m.fs.C101.default_initializer().initialize(m.fs.C101)  # Initialize Compressor
# propagate_state(m.fs.s09)  # Establish connection between Compressor and Mixer
# m.fs.I101.default_initializer().initialize(m.fs.I101)  # Initialize Toluene Inlet
# propagate_state(m.fs.s01)  # Establish connection between Toluene Inlet and Mixer
# m.fs.I102.default_initializer().initialize(m.fs.I102)  # Initialize Hydrogen Inlet
# propagate_state(m.fs.s02)  # Establish connection between Hydrogen Inlet and Mixer
# m.fs.M101.default_initializer().initialize(m.fs.M101)  # Initialize Mixer
# propagate_state(m.fs.s03)  # Establish connection between Mixer and Heater
# m.fs.F102.default_initializer().initialize(m.fs.F102)  # Initialize Second Flash Unit
# propagate_state(m.fs.s10)  # Establish connection between Second Flash Unit and Benzene Product
# propagate_state(m.fs.s11)  # Establish connection between Second Flash Unit and Toluene Product
# propagate_state(m.fs.s12)  # Establish connection between Splitter and Purge Product

optarg = {
    "nlp_scaling_method": "user-scaling",
    "OF_ma57_automatic_scaling": "yes",
    "max_iter": 300,
    "tol": 1e-8,
}
solver = get_solver("ipopt_v2", options=optarg)
results = solver.solve(m, tee=True)

for k, v in tear_guesses.items():
    for k1, v1 in v.items():
        getattr(m.fs.H101.inlet, k)[k1].unfix()

m.fs.s03_expanded.activate()
print(
    f"The DOF is {degrees_of_freedom(m)} after unfixing the values and reactivating the tear stream"
)
# %% md
# ## 6 Solving the Model
# %% md
# We have now initialized the flowsheet. Lets set up some solving options before simulating the flowsheet. We want to specify the scaling method, number of iterations, and tolerance. More specific or advanced options can be found at the documentation for IPOPT https://coin-or.github.io/Ipopt/OPTIONS.html
# %%
optarg = {
    "nlp_scaling_method": "user-scaling",
    "OF_ma57_automatic_scaling": "yes",
    "max_iter": 1000,
    "tol": 1e-8,
}
# %% md
# <div class="alert alert-block alert-info">
# <b>Inline Exercise:</b>
# Let us run the flowsheet in a simulation mode to look at the results. To do this, complete the last line of code where we pass the model to the solver. You will need to type the following:
#
# solver = get_solver(solver_options=optarg)<br>
# results = solver.solve(m, tee=True)
#
# Use Shift+Enter to run the cell once you have typed in your code.
# </div>
#
# %%
# Create the solver object

# Solve the model
# %%
# Create the solver object
solver = get_solver("ipopt_v2", options=optarg)

# Solve the model
results = solver.solve(m, tee=False)

print(f"Solver result: {results}")
# %%
# Check solver solve status
from pyomo.environ import TerminationCondition

assert results.solver.termination_condition == TerminationCondition.optimal
# %% md
# ## 7 Analyze the results
#
#
#
# %% md
# If the IDAES UI package was installed with the `idaes-pse` installation or installed separately, you can run the flowsheet visualizer to see a full diagram of the full process that is generated and displayed on a browser window.
#
# %%
# m.fs.visualize("HDA-Flowsheet")
# %% md
# Otherwise, we can run the `m.fs.report()` method to see a full summary of the solved flowsheet. It is recommended to adjust the width of the output as much as possible for the cleanest display.
# %%
m.fs.report()
# %% md
# What is the total operating cost?
# %%
print("operating cost = $", value(m.fs.operating_cost))
# %%
import pytest

# assert value(m.fs.operating_cost) == pytest.approx(424513.9645, abs=1e-3)
# %% md
# For this operating cost, what is the amount of benzene we are able to produce and what purity we are able to achieve?  We can look at a specific unit models stream table with the same `report()` method.
# %%
m.fs.F102.report()

print()
print("benzene purity = ", value(m.fs.purity))
# %%
assert value(m.fs.purity) == pytest.approx(0.82429, abs=1e-3)
assert value(m.fs.F102.heat_duty[0]) == pytest.approx(7346.03097, abs=1e-3)
assert value(m.fs.F102.vap_outlet.pressure[0]) == pytest.approx(1.5000e05, abs=1e-3)
# %% md
# Next, let's look at how much benzene we are losing with the light gases out of F101. IDAES has tools for creating stream tables based on the `Arcs` and/or `Ports` in a flowsheet. Let us create and print a simple stream table showing the stream leaving the reactor and the vapor stream from F101.
# %%
from idaes.core.util.tables import (
    create_stream_table_dataframe,
    stream_table_dataframe_to_string,
)

st = create_stream_table_dataframe({"Reactor": m.fs.s05, "Light Gases": m.fs.s06})
print(stream_table_dataframe_to_string(st))
# %% md
# ## 8 Optimization
#
#
# We saw from the results above that the total operating cost for the base case was $419,122 per year. We are producing 0.142 mol/s of benzene at a purity of 82\%. However, we are losing around 42\% of benzene in F101 vapor outlet stream.
#
# Let us try to minimize this cost such that:
# - we are producing at least 0.15 mol/s of benzene in F102 vapor outlet i.e. our product stream
# - purity of benzene i.e. the mole fraction of benzene in F102 vapor outlet is at least 80%
# - restricting the benzene loss in F101 vapor outlet to less than 20%
#
# For this problem, our decision variables are as follows:
# - H101 outlet temperature
# - R101 cooling duty provided
# - F101 outlet temperature
# - F102 outlet temperature
# - F102 deltaP in the flash tank
#
# %% md
# Let us declare our objective function for this problem.
# %%
m.fs.objective = Objective(expr=m.fs.operating_cost)
# %% md
# Now, we need to unfix the decision variables as we had solved a square problem (degrees of freedom = 0) until now.
# %%
m.fs.H101.outlet.temperature.unfix()
m.fs.R101.heat_duty.unfix()
m.fs.F101.vap_outlet.temperature.unfix()
m.fs.F102.vap_outlet.temperature.unfix()
# %% md
# <div class="alert alert-block alert-info">
# <b>Inline Exercise:</b>
# Let us now unfix the remaining variable which is F102 pressure drop (F102.deltaP)
#
# Use Shift+Enter to run the cell once you have typed in your code.
# </div>
#
#
# %%
# Todo: Unfix deltaP for F102
# %%
# Todo: Unfix deltaP for F102
m.fs.F102.deltaP.unfix()
# %%
assert degrees_of_freedom(m) == 5
# %% md
# Next, we need to set bounds on these decision variables to values shown below:
#
#  - H101 outlet temperature [500, 600] K
#  - R101 outlet temperature [600, 800] K
#  - F101 outlet temperature [298, 450] K
#  - F102 outlet temperature [298, 450] K
#  - F102 outlet pressure [105000, 110000] Pa
#
# Let us first set the variable bound for the H101 outlet temperature as shown below:
# %%
m.fs.H101.outlet.temperature[0].setlb(500)
m.fs.H101.outlet.temperature[0].setub(600)
# %% md
# <div class="alert alert-block alert-info">
# <b>Inline Exercise:</b>
# Now, set the variable bound for the R101 outlet temperature.
#
# Use Shift+Enter to run the cell once you have typed in your code.
# </div>
# %%
# Todo: Set the bounds for reactor outlet temperature
# %%
# Todo: Set the bounds for reactor outlet temperature
m.fs.R101.outlet.temperature[0].setlb(600)
m.fs.R101.outlet.temperature[0].setub(800)
# %% md
# Let us fix the bounds for the rest of the decision variables.
# %%
m.fs.F101.vap_outlet.temperature[0].setlb(298.0)
m.fs.F101.vap_outlet.temperature[0].setub(450.0)
m.fs.F102.vap_outlet.temperature[0].setlb(298.0)
m.fs.F102.vap_outlet.temperature[0].setub(450.0)
m.fs.F102.vap_outlet.pressure[0].setlb(105000)
m.fs.F102.vap_outlet.pressure[0].setub(110000)
# %% md
# Now, the only things left to define are our constraints on overhead loss in F101, product flow rate and purity in F102. Let us first look at defining a constraint for the overhead loss in F101 where we are restricting the benzene leaving the vapor stream to less than 20 \% of the benzene available in the reactor outlet.
# %%
m.fs.overhead_loss = Constraint(
    expr=m.fs.F101.control_volume.properties_out[0].flow_mol_phase_comp[
        "Vap", "benzene"
    ]
    <= 0.20
    * m.fs.R101.control_volume.properties_out[0].flow_mol_phase_comp["Vap", "benzene"]
)
# %% md
# <div class="alert alert-block alert-info">
# <b>Inline Exercise:</b>
# Now, add the constraint such that we are producing at least 0.15 mol/s of benzene in the product stream which is the vapor outlet of F102. Let us name this constraint as m.fs.product_flow.
#
# Use Shift+Enter to run the cell once you have typed in your code.
# </div>
# %%
# Todo: Add minimum product flow constraint
# %%
# Todo: Add minimum product flow constraint
m.fs.product_flow = Constraint(
    expr=m.fs.F102.control_volume.properties_out[0].flow_mol_phase_comp[
        "Vap", "benzene"
    ]
    >= 0.15
)
# %% md
# Let us add the final constraint on product purity or the mole fraction of benzene in the product stream such that it is at least greater than 80%.
# %%
m.fs.product_purity = Constraint(expr=m.fs.purity >= 0.80)
# %% md
#
# We have now defined the optimization problem and we are now ready to solve this problem.
#
#
#
# %%
results = solver.solve(m, tee=True)
# %%
# Check for solver solve status
from pyomo.environ import TerminationCondition

assert results.solver.termination_condition == TerminationCondition.optimal
# %% md
# ### 8.1 Optimization Results
#
# Display the results and product specifications
# %%
print("operating cost = $", value(m.fs.operating_cost))

print()
print("Product flow rate and purity in F102")

m.fs.F102.report()

print()
print("benzene purity = ", value(m.fs.purity))

print()
print("Overhead loss in F101")
m.fs.F101.report()
# %%

assert value(m.fs.operating_cost) == pytest.approx(318024.909, abs=1e-3)
assert value(m.fs.purity) == pytest.approx(0.818827, abs=1e-3)
# %% md
# Display optimal values for the decision variables
# %%
print(
    f"""Optimal Values:

H101 outlet temperature = {value(m.fs.H101.outlet.temperature[0]):.3f} K

R101 outlet temperature = {value(m.fs.R101.outlet.temperature[0]):.3f} K

F101 outlet temperature = {value(m.fs.F101.vap_outlet.temperature[0]):.3f} K

F102 outlet temperature = {value(m.fs.F102.vap_outlet.temperature[0]):.3f} K
F102 outlet pressure = {value(m.fs.F102.vap_outlet.pressure[0]):.3f} Pa
"""
)
# %%
assert value(m.fs.H101.outlet.temperature[0]) == pytest.approx(500, abs=1e-3)
# assert value(m.fs.R101.outlet.temperature[0]) == pytest.approx(696.112, abs=1e-3)
assert value(m.fs.R101.outlet.temperature[0]) == pytest.approx(763.484, abs=1e-3)
assert value(m.fs.F101.vap_outlet.temperature[0]) == pytest.approx(301.881, abs=1e-3)
assert value(m.fs.F102.vap_outlet.temperature[0]) == pytest.approx(362.935, abs=1e-3)
assert value(m.fs.F102.vap_outlet.pressure[0]) == pytest.approx(105000, abs=1e-2)
