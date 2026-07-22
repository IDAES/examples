#!/usr/bin/env python
# coding: utf-8

# In[1]:


###############################################################################
# The Institute for the Design of Advanced Energy Systems Integrated Platform
# Framework (idaes IP) was produced under the DOE Institute for the
# Design of Advanced Energy Systems (IDAES).
#
# Copyright (c) 2018-2026 by the software owners: The Regents of the
# University of California, through Lawrence Berkeley National Laboratory,
# National Technology & Engineering Solutions of Sandia, LLC, Carnegie Mellon
# University, West Virginia University Research Corporation, et al.
# All rights reserved.  Please see the files COPYRIGHT.md and LICENSE.md
# for full copyright and license information.
###############################################################################


# 
# # HDA Flowsheet Simulation and Optimization
# 
# Author: Jaffer Ghouse<br>
# Maintainer: Tanner Polley<br>
# Updated: 2026-1-12
# 
# ## Learning outcomes
# 
# 
# - Construct a steady-state flowsheet using the IDAES unit model library
# - Connecting unit models in a flowsheet using Arcs
# - Using the SequentialDecomposition tool to initialize a flowsheet with recycle
# - Formulate and solve an optimization problem
#     - Defining an objective function
#     - Setting variable bounds
#     - Adding additional constraints
# 
# 
# The general workflow of setting up an IDAES flowsheet is the following:
# 
# &nbsp;&nbsp;&nbsp;&nbsp; 1 Importing Modules <br>
# &nbsp;&nbsp;&nbsp;&nbsp; 2 Building a Model <br>
# &nbsp;&nbsp;&nbsp;&nbsp; 3 Scaling the Model <br>
# &nbsp;&nbsp;&nbsp;&nbsp; 4 Specifying the Model <br>
# &nbsp;&nbsp;&nbsp;&nbsp; 5 Initializing the Model <br>
# &nbsp;&nbsp;&nbsp;&nbsp; 6 Solving the Model <br>
# &nbsp;&nbsp;&nbsp;&nbsp; 7 Analyzing and Visualizing the Results <br>
# &nbsp;&nbsp;&nbsp;&nbsp; 8 Optimizing the Model <br>
# 
# We will complete each of these steps as well as demonstrate analyses on this model through some examples and exercises.
# 
# 
# ## Problem Statement
# 
# Hydrodealkylation is a chemical reaction that often involves reacting
# an aromatic hydrocarbon in the presence of hydrogen gas to form a
# simpler aromatic hydrocarbon devoid of functional groups. In this
# example, toluene will be reacted with hydrogen gas at high temperatures
#  to form benzene via the following reaction:
# 
# **C<sub>6</sub>H<sub>5</sub>CH<sub>3</sub> + H<sub>2</sub> → C<sub>6</sub>H<sub>6</sub> + CH<sub>4</sub>**
# 
# 
# This reaction is often accompanied by an equilibrium side reaction
# which forms diphenyl, which we will neglect for this example.
# 
# This example is based on the 1967 AIChE Student Contest problem as
# present by Douglas, J.M., Chemical  Design of Chemical Processes, 1988,
# McGraw-Hill.
# 
# The flowsheet that we will be using for this module is shown below with the stream conditions. We will be processing toluene and hydrogen to produce at least 370 TPY of benzene. As shown in the flowsheet, there are two flash tanks, F101 to separate out the non-condensibles and F102 to further separate the benzene-toluene mixture to improve the benzene purity.  Note that typically a distillation column is required to obtain high purity benzene but that is beyond the scope of this workshop. The non-condensibles separated out in F101 will be partially recycled back to M101 and the rest will be either purged or combusted for power generation.We will assume ideal gas for this flowsheet. The properties required for this module are available in the same directory:
# 
# - hda_ideal_VLE.py
# - hda_reaction.py
# 
# The state variables chosen for the property package are **flows of component by phase, temperature and pressure**. The components considered are: **toluene, hydrogen, benzene and methane**. Therefore, every stream has 8 flow variables, 1 temperature and 1 pressure variable. 
# 
# ![](HDA_flowsheet.png)
# 
# 

# ## 1 Importing Modules
# ### 1.1 Importing required Pyomo and IDAES components
# 
# 
# To construct a flowsheet, we will need several components from the Pyomo and IDAES package. Let us first import the following components from Pyomo:
# - Constraint (to write constraints)
# - Var (to declare variables)
# - ConcreteModel (to create the concrete model object)
# - Expression (to evaluate values as a function of variables defined in the model)
# - Objective (to define an objective function for optimization)
# - SolverFactory (to solve the problem)
# - TransformationFactory (to apply certain transformations)
# - Arc (to connect two unit models)
# - SequentialDecomposition (to initialize the flowsheet in a sequential mode)
# 
# For further details on these components, please refer to the Pyomo documentation: https://Pyomo.readthedocs.io/en/stable/
# 

# In[2]:


from pyomo.environ import (
    Constraint,
    Var,
    ConcreteModel,
    Expression,
    Objective,
    TransformationFactory,
    value,
)
from pyomo.network import Arc


# From IDAES, we will be needing the FlowsheetBlock and the following unit models:
# - Feed
# - Mixer
# - Heater
# - StoichiometricReactor
# - <span style="color:blue">**Flash**</span>
# - Separator (splitter) 
# - PressureChanger
# - Product

# In[3]:


from idaes.core import FlowsheetBlock


# In[4]:


from idaes.models.unit_models import (
    PressureChanger,
    Mixer,
    Separator as Splitter,
    Heater,
    StoichiometricReactor,
    Feed,
    Product,
)


# <div class="alert alert-block alert-info">
# <b>Inline Exercise:</b>
# Now, import the remaining unit models highlighted in blue above and run the cell using `Shift+Enter` after typing in the code. 
# </div>
# 

# In[5]:


# Todo: import flash model from idaes.models.unit_models


# In[6]:


# Todo: import flash model from idaes.models.unit_models
from idaes.models.unit_models import Flash


# We will also be needing some utility tools to put together the flowsheet and calculate the degrees of freedom. 

# In[7]:


from idaes.models.unit_models.pressure_changer import ThermodynamicAssumption
from idaes.core.util.model_statistics import degrees_of_freedom

# Import idaes logger to set output levels
from idaes.core.solvers import get_solver


# ### 1.2 Importing required thermo and reaction package
# 
# The final set of imports are to import the thermo and reaction package for the HDA process. We have created a custom thermo package that assumes Ideal Gas with support for VLE. 
# 
# The reaction package here is very simple as we will be using only a StochiometricReactor and the reaction package consists of the stochiometric coefficients for the reaction and the parameter for the heat of reaction. 
# 
# Let us import the following modules and they are in the same directory as this jupyter notebook:
#       <ul>
#          <li>hda_ideal_VLE as thermo_props</li>
#          <li>hda_reaction as reaction_props </li>
#       </ul>
# </div>

# In[8]:


from idaes.models.properties.modular_properties.base.generic_property import (
    GenericParameterBlock,
)
from idaes.models.properties.modular_properties.base.generic_reaction import (
    GenericReactionParameterBlock,
)
from idaes_examples.mod.hda.hda_ideal_VLE_modular import thermo_config
from idaes_examples.mod.hda.hda_reaction_modular import reaction_config


# ## 2 Constructing the Flowsheet
# 
# We have now imported all the components, unit models, and property modules we need to construct a flowsheet. Let us create a ConcreteModel and add the flowsheet block.

# In[9]:


m = ConcreteModel()
m.fs = FlowsheetBlock(dynamic=False)


# We now need to add the property packages to the flowsheet. Unlike Module 1, where we only had a thermo property package, for this flowsheet we will also need to add a reaction property package. 

# In[10]:


m.fs.thermo_params = GenericParameterBlock(**thermo_config)
m.fs.reaction_params = GenericReactionParameterBlock(
    property_package=m.fs.thermo_params, **reaction_config
)


# ### 2.1 Adding Unit Models
# 
# Let us start adding the unit models we have imported to the flowsheet. Here, we are adding the Feed (assigned a name `I101` for Inlet), `Mixer` (assigned a name `M101`) and a `Heater` (assigned a name `H101`). Note that, all unit models need to be given a property package argument. In addition to that, there are several arguments depending on the unit model, please refer to the documentation for more details (https://idaes-pse.readthedocs.io/en/stable/reference_guides/model_libraries/generic/unit_models/index.html). For example, the `Mixer` unit model here must be specified the number of inlets that it will take in and the `Heater` can have specific settings enabled such as `has_pressure_change` or `has_phase_equilibrium`.

# In[11]:


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


# <div class="alert alert-block alert-info">
# <b>Inline Exercise:</b>
# Let us now add the StoichiometricReactor(assign the name R101) and pass the following arguments:
#       <ul>
#          <li>"property_package": m.fs.thermo_params</li>
#          <li>"reaction_package": m.fs.reaction_params </li>
#          <li>"has_heat_of_reaction": True </li>
#          <li>"has_heat_transfer": True</li>
#          <li>"has_pressure_change": False</li>
#       </ul>
# </div>

# In[12]:


# Todo: Add reactor with the specifications above


# In[13]:


# Todo: Add reactor with the specifications above
m.fs.R101 = StoichiometricReactor(
    property_package=m.fs.thermo_params,
    reaction_package=m.fs.reaction_params,
    has_heat_of_reaction=True,
    has_heat_transfer=True,
    has_pressure_change=False,
)


# Let us now add the Flash(assign the name F101) and pass the following arguments:
#       <ul>
#          <li>"property_package": m.fs.thermo_params</li>
#          <li>"has_heat_transfer": True</li>
#          <li>"has_pressure_change": False</li>
#       </ul>

# In[14]:


m.fs.F101 = Flash(
    property_package=m.fs.thermo_params,
    has_heat_transfer=True,
    has_pressure_change=True,
)


# Let us now add the Splitter(S101) with specific names for its output (purge and recycle), PressureChanger(C101) and the second Flash(F102).

# In[15]:


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


# Last, we will add the three Product blocks (P101, P102, P103). We use `Feed` blocks and `Product` blocks for convenience with reporting stream summaries and consistency

# In[16]:


m.fs.P101 = Product(property_package=m.fs.thermo_params)
m.fs.P102 = Product(property_package=m.fs.thermo_params)
m.fs.P103 = Product(property_package=m.fs.thermo_params)


# ### 2.2 Connecting Unit Models using Arcs
# 
# We have now added all the unit models we need to the flowsheet. However, we have not yet specified how the units are to be connected. To do this, we will be using the `Arc` which is a Pyomo component that takes in two arguments: `source` and `destination`. Let us connect the outlet of the inlets (I101, I102) to the inlet of the mixer (M101) and outlet of the mixer to the inlet of the heater(H101).

# ![](HDA_flowsheet.png)

# In[17]:


m.fs.s01 = Arc(source=m.fs.I101.outlet, destination=m.fs.M101.inlet_1)
m.fs.s02 = Arc(source=m.fs.I102.outlet, destination=m.fs.M101.inlet_2)
m.fs.s03 = Arc(source=m.fs.M101.outlet, destination=m.fs.H101.inlet)


# <div class="alert alert-block alert-info">
# <b>Inline Exercise:</b>
# Now, connect the H101 outlet to the R101 inlet using the cell above as a guide.
# </div>

# In[18]:


# Todo: Connect the H101 outlet to R101 inlet


# In[19]:


# Todo: Connect the H101 outlet to R101 inlet
m.fs.s04 = Arc(source=m.fs.H101.outlet, destination=m.fs.R101.inlet)


# We will now be connecting the rest of the flowsheet as shown below. Notice how the outlet names are different for the flash tanks F101 and F102 as they have a vapor and a liquid outlet. 

# In[20]:


m.fs.s05 = Arc(source=m.fs.R101.outlet, destination=m.fs.F101.inlet)
m.fs.s06 = Arc(source=m.fs.F101.vap_outlet, destination=m.fs.S101.inlet)
m.fs.s07 = Arc(source=m.fs.F101.liq_outlet, destination=m.fs.F102.inlet)
m.fs.s08 = Arc(source=m.fs.S101.recycle, destination=m.fs.C101.inlet)
m.fs.s09 = Arc(source=m.fs.C101.outlet, destination=m.fs.M101.inlet_3)


# Last we will connect the outlet streams to the inlets of the Product blocks (P101, P102, P103)

# In[21]:


m.fs.s10 = Arc(source=m.fs.F102.vap_outlet, destination=m.fs.P101.inlet)
m.fs.s11 = Arc(source=m.fs.F102.liq_outlet, destination=m.fs.P102.inlet)
m.fs.s12 = Arc(source=m.fs.S101.purge, destination=m.fs.P103.inlet)


# We have now connected the unit model block using the arcs. However, each of these arcs link to ports on the two unit models that are connected. In this case, the ports consist of the state variables that need to be linked between the unit models. Pyomo provides a convenient method to write these equality constraints for us between two ports and this is done as follows:

# In[22]:


TransformationFactory("network.expand_arcs").apply_to(m)


# ### 2.3 Adding expressions to compute purity and operating costs
# 
# In this section, we will add a few Expressions that allows us to evaluate the performance. Expressions provide a convenient way of calculating certain values that are a function of the variables defined in the model. For more details on Expressions, please refer to: https://pyomo.readthedocs.io/en/stable/explanation/modeling/network.html.
# 
# For this flowsheet, we are interested in computing the purity of the product Benzene stream (i.e. the mole fraction) and the operating cost which is a sum of the cooling and heating cost. 

# Let us first add an Expression to compute the mole fraction of benzene in the `vap_outlet` of F102 which is our product stream. Please note that the var flow_mol_phase_comp has the index - [time, phase, component]. As this is a steady-state flowsheet, the time index by default is 0. The valid phases are ["Liq", "Vap"]. Similarly the valid component list is ["benzene", "toluene", "hydrogen", "methane"].

# In[23]:


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


# Now, let us add an expression to compute the cooling cost assuming a cost of 0.212E-4 $/kW. Note that cooling utility is required for the reactor (R101) and the first flash (F101). 

# In[24]:


m.fs.cooling_cost = Expression(
    expr=0.212e-7 * (-m.fs.F101.heat_duty[0]) + 0.212e-7 * (-m.fs.R101.heat_duty[0])
)


# 
# Now, let us add an expression to compute the heating cost assuming the utility cost as follows:
#       <ul>
#          <li>2.2E-4 dollars/kW for H101</li>
#          <li>1.9E-4 dollars/kW for F102</li>
#       </ul>
# Note that the heat duty is in units of watt (J/s). 

# In[25]:


m.fs.heating_cost = Expression(
    expr=2.2e-7 * m.fs.H101.heat_duty[0] + 1.9e-7 * m.fs.F102.heat_duty[0]
)


# Let us now add an expression to compute the total operating cost per year which is basically the sum of the cooling and heating cost we defined above. 

# In[26]:


m.fs.operating_cost = Expression(
    expr=(3600 * 24 * 365 * (m.fs.heating_cost + m.fs.cooling_cost))
)


# ## 4 Specifying the Model
# ### 4.1 Fixing feed conditions
# 
# Let us first check how many degrees of freedom exist for this flowsheet using the `degrees_of_freedom` tool we imported earlier. 

# In[27]:


print(degrees_of_freedom(m))


# In[28]:


# Check the degrees of freedom
assert degrees_of_freedom(m) == 29


# We will now be fixing the toluene feed (`I101`) stream to the conditions shown in the flowsheet above. Please note
# that though this is a pure toluene feed, the remaining components are still assigned a very small non-zero value to
# help with convergence and initializing. We will be importing a function that will specify the inlet conditions for
# this example.

# In[29]:


from idaes_examples.mod.hda.hda_flowsheet_extras import fix_inlet_states

tear_guesses = fix_inlet_states(m)


# ### 4.2 Fixing unit model specifications
# 
# Now that we have fixed our inlet feed conditions, we will now be fixing the operating conditions for the unit models in the flowsheet. Let us set set the H101 outlet temperature to 600 K. 

# In[30]:


m.fs.H101.outlet.temperature.fix(600)


# For the StoichiometricReactor, we have to define the conversion in terms of toluene. This requires us to create a new variable for specifying the conversion and adding a Constraint that defines the conversion with respect to toluene. The second degree of freedom for the reactor is to define the heat duty. In this case, let us assume the reactor to be adiabatic i.e. Q = 0. 

# In[31]:


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


# The Flash conditions for F101 can be set as follows. 

# In[32]:


m.fs.F101.vap_outlet.temperature.fix(325.0)
m.fs.F101.deltaP.fix(0)


# <div class="alert alert-block alert-info">
# <b>Inline Exercise:</b>
# Set the conditions for Flash F102 to the following conditions:
#       <ul>
#          <li>T = 375 K</li>
#          <li>deltaP = -200000</li>
#       </ul>
# 
# Use Shift+Enter to run the cell once you have typed in your code. 
# </div>

# In[33]:


# Todo: Set conditions for Flash F102


# In[34]:


m.fs.F102.vap_outlet.temperature.fix(375)
m.fs.F102.deltaP.fix(-200000)


# Let us fix the purge split fraction to 20% and the outlet pressure of the compressor is set to 350000 Pa. 

# In[35]:


m.fs.S101.split_fraction[0, "purge"].fix(0.2)
m.fs.C101.outlet.pressure.fix(350000)


# <div class="alert alert-block alert-info">
# <b>Inline Exercise:</b>
# We have now defined all the feed conditions and the inputs required for the unit models. The system should now have 0 degrees of freedom i.e. should be a square problem. Please check that the degrees of freedom is 0. 
# 
# Use Shift+Enter to run the cell once you have typed in your code. 
# </div>

# In[36]:


# Todo: print the degrees of freedom


# In[37]:


print(degrees_of_freedom(m))


# In[38]:


# Check the degrees of freedom
assert degrees_of_freedom(m) == 0


# ## 5 Initializing the Model
# 
# 
# 
# When a flowsheet contains a recycle loop, the outlet of a downstream unit becomes the inlet of an upstream unit, creating a cyclic dependency that prevents straightforward calculation of all stream conditions. The tear‐stream method is necessary because it “breaks” this loop: you select one recycle stream as the tear, assign it an initial guess, and then solve the rest of the flowsheet as if it were acyclic. Once the downstream units compute their outputs, you compare the calculated value of the torn stream to your initial guess and iteratively adjust until they coincide. Without tearing, the solver cannot establish a proper topological sequence or drive the recycle to convergence, making initialization—and ultimately steady‐state convergence—impossible.
# 
# It is important to determine the tear stream for a flowsheet which will be demonstrated below.
# 
# 
# ![](HDA_tear_stream.png)
# 
# Currently, there are two methods of initializing a full flowsheet: using the sequential decomposition tool, or
# manually propagating through the flowsheet. The tear stream in this example will be the stream from the mixer to the heater since that is where the
# recycle stream first enters back into the main process.
# 
# 

# First, we will highlight some helpful functions that are used in the initialization process.

# In[39]:


def initialize_unit(unit):
    from idaes.core.util.exceptions import InitializationError
    import idaes.logger as idaeslog

    optarg = {
        "OF_ma57_automatic_scaling": "yes",
        "max_iter": 1000,
        "tol": 1e-8,
    }

    try:
        initializer = unit.default_initializer(solver_options=optarg)
        initializer.initialize(unit, output_level=idaeslog.INFO_LOW)
    except InitializationError:
        solver = get_solver(solver_options=optarg)
        solver.solve(unit)


# This first function will take any unit model and can either initialize the model with its respective default
# initializer, or use a generic solver and the solve the current state of the unit model. Often times a direct
# initialization method will fail while a solving method will converge so having the option for both is helpful.
# 
# 
# ### 5.1 Sequential Decomposition
# 
# This section will demonstrate how to use the built-in sequential decomposition tool to initialize our flowsheet. Sequential Decomposition is a tool from Pyomo where the documentation can be found here https://Pyomo.readthedocs.io/en/stable/explanation/modeling/network.html#sequential-decomposition

# In[40]:


def automatic_propagation(m, tear_guesses):

    from pyomo.network import SequentialDecomposition

    seq = SequentialDecomposition()
    seq.options.select_tear_method = "heuristic"
    seq.options.tear_method = "Wegstein"
    seq.options.iterLim = 5

    # Using the SD tool
    G = seq.create_graph(m)
    heuristic_tear_set = seq.tear_set_arcs(G, method="heuristic")
    order = seq.calculation_order(G)

    # Pass the tear_guess to the SD tool
    seq.set_guesses_for(heuristic_tear_set[0].destination, tear_guesses)

    print(f"Tear Stream starts at: {heuristic_tear_set[0].destination.name}")

    for o in order:
        print(o[0].name)

    seq.run(m, initialize_unit)


# We are now ready to initialize our flowsheet in a sequential mode. Note that we specifically set the iteration limit
# to be 5 as we are trying to use this tool only to get a good set of initial values such that IPOPT can then take over
#  and solve this flowsheet for us. Uncomment this function call to run the automatic propagation method

# In[41]:


# automatic_propagation(m, tear_guesses)


# ### 5.2 Manual Propagation Method
# 
# This method uses a more direct approach to initialize the flowsheet, using the updated initializer method and propagating manually through the flowsheet and solving for the tear stream directly.
# Lets define the function that will help us manually propagate and step through the flowsheet

# In[42]:


def manual_propagation(m, tear_guesses):
    from idaes.core.util.initialization import propagate_state

    print(f"The DOF is {degrees_of_freedom(m)} initially")
    m.fs.s03_expanded.deactivate()
    print(f"The DOF is {degrees_of_freedom(m)} after deactivating the tear stream")

    for k, v in tear_guesses.items():
        for k1, v1 in v.items():
            getattr(m.fs.s03.destination, k)[k1].fix(v1)

    print(f"The DOF is {degrees_of_freedom(m)} after setting the tear stream")

    optarg = {
        "OF_ma57_automatic_scaling": "yes",
        "max_iter": 300,
        # "tol": 1e-10,
    }

    solver = get_solver(solver_options=optarg)

    initialize_unit(m.fs.H101)  # Initialize Heater
    propagate_state(m.fs.s04)  # Establish connection between Heater and Reactor
    initialize_unit(m.fs.R101)  # Initialize Reactor
    propagate_state(
        m.fs.s05
    )  # Establish connection between Reactor and First Flash Unit
    initialize_unit(m.fs.F101)  # Initialize First Flash Unit
    propagate_state(
        m.fs.s06
    )  # Establish connection between First Flash Unit and Splitter
    propagate_state(
        m.fs.s07
    )  # Establish connection between First Flash Unit and Second Flash Unit
    initialize_unit(m.fs.S101)  # Initialize Splitter
    propagate_state(m.fs.s08)  # Establish connection between Splitter and Compressor
    initialize_unit(m.fs.C101)  # Initialize Compressor
    propagate_state(m.fs.s09)  # Establish connection between Compressor and Mixer
    initialize_unit(m.fs.I101)  # Initialize Toluene Inlet
    propagate_state(m.fs.s01)  # Establish connection between Toluene Inlet and Mixer
    initialize_unit(m.fs.I102)  # Initialize Hydrogen Inlet
    propagate_state(m.fs.s02)  # Establish connection between Hydrogen Inlet and Mixer
    initialize_unit(m.fs.M101)  # Initialize Mixer
    propagate_state(m.fs.s03)  # Establish connection between Mixer and Heater
    solver.solve(m.fs.F102)
    propagate_state(
        m.fs.s10
    )  # Establish connection between Second Flash Unit and Benzene Product
    propagate_state(
        m.fs.s11
    )  # Establish connection between Second Flash Unit and Toluene Product
    propagate_state(m.fs.s12)  # Establish connection between Splitter and Purge Product

    optarg = {
        "OF_ma57_automatic_scaling": "yes",
        "max_iter": 300,
        "tol": 1e-8,
    }
    solver = get_solver("ipopt_v2", options=optarg)
    solver.solve(m, tee=False)

    for k, v in tear_guesses.items():
        for k1, v1 in v.items():
            getattr(m.fs.H101.inlet, k)[k1].unfix()

    m.fs.s03_expanded.activate()
    print(
        f"The DOF is {degrees_of_freedom(m)} after unfixing the values and reactivating the tear stream"
    )


# It will first show that the degrees of freedom is correctly at 0 before any streams are deactivated. Once the tear
# stream is deactivated though, the degrees of freedom will be 10. That means 10 variables will have to be defined with
#  the tear guesses `tear_guesses`. Then each unit model can be initialized with our same helper function and then can
#  propagate the corresponding connection to the following unit models. At the end, the whole flowsheet is solved,
#  giving a much better chance for the recycle stream to be used correctly the flowsheet to converge.

# In[43]:


manual_propagation(m, tear_guesses)


# ## 6 Solving the Model

# We have now initialized the flowsheet. Lets set up some solving options before simulating the flowsheet. We want to specify the scaling method, number of iterations, and tolerance. More specific or advanced options can be found at the documentation for IPOPT https://coin-or.github.io/Ipopt/OPTIONS.html

# In[44]:


optarg = {
    "OF_ma57_automatic_scaling": "yes",
    "max_iter": 300,
    "tol": 1e-8,
}


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

# In[45]:


# Create the solver object

# Solve the model


# In[46]:


# Create the solver object
solver = get_solver("ipopt_v2", options=optarg)

# Solve the model
results = solver.solve(m, tee=True)


# In[47]:


# Check solver solve status
from pyomo.environ import TerminationCondition

assert results.solver.termination_condition == TerminationCondition.optimal


# ## 7 Analyze the results
# 
# 
# 

# If the IDAES UI package was installed with the `idaes-pse` installation or installed separately, you can run the flowsheet visualizer to see a full diagram of the full process that is generated and displayed on a browser window.
# 

# In[48]:


# m.fs.visualize("HDA-Flowsheet")


# Otherwise, we can run the `m.fs.report()` method to see a full summary of the solved flowsheet. It is recommended to adjust the width of the output as much as possible for the cleanest display.

# In[49]:


m.fs.report()


# What is the total operating cost?

# In[50]:


print("operating cost = $", value(m.fs.operating_cost))


# In[51]:


import pytest

assert value(m.fs.operating_cost) == pytest.approx(419008.28189, rel=1e-6)


# For this operating cost, what is the amount of benzene we are able to produce and what purity we are able to achieve?  We can look at a specific unit models stream table with the same `report()` method.

# In[52]:


m.fs.F102.report()

print()
print("benzene purity = ", value(m.fs.purity))


# In[53]:


assert value(m.fs.purity) == pytest.approx(0.82429, abs=1e-3)
assert value(m.fs.F102.heat_duty[0]) == pytest.approx(7346.67441, abs=1e-3)
assert value(m.fs.F102.vap_outlet.pressure[0]) == pytest.approx(1.5000e05, abs=1e-3)


# Next, let's look at how much benzene we are losing with the light gases out of F101. IDAES has tools for creating stream tables based on the `Arcs` and/or `Ports` in a flowsheet. Let us create and print a simple stream table showing the stream leaving the reactor and the vapor stream from F101.

# In[54]:


from idaes.core.util.tables import (
    create_stream_table_dataframe,
    stream_table_dataframe_to_string,
)

st = create_stream_table_dataframe({"Reactor": m.fs.s05, "Light Gases": m.fs.s06})
print(stream_table_dataframe_to_string(st))


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

# Let us declare our objective function for this problem. 

# In[55]:


m.fs.objective = Objective(expr=m.fs.operating_cost)


# Now, we need to unfix the decision variables as we had solved a square problem (degrees of freedom = 0) until now.
# 
# Because we are using a stoichiometric reactor, the reactor temperature has no effect on the reaction yield. Additionally, we are using the same cost for heat removal from both the reactor and flash units. Therefore, the optimization algorithm has no reason to prefer heat removal in one place or the other; the solution returned is not locally unique. To remove this indeterminancy and ensure that a consistent solution is returned, we fix the outlet temperature of the reactor.

# In[56]:


m.fs.H101.outlet.temperature.unfix()
m.fs.R101.heat_duty.unfix()
m.fs.R101.outlet.temperature.fix(600)
m.fs.F101.vap_outlet.temperature.unfix()
m.fs.F102.vap_outlet.temperature.unfix()


# <div class="alert alert-block alert-info">
# <b>Inline Exercise:</b>
# Let us now unfix the remaining variable which is F102 pressure drop (F102.deltaP) 
# 
# Use Shift+Enter to run the cell once you have typed in your code. 
# </div>
# 
# 

# In[57]:


# Todo: Unfix deltaP for F102


# In[58]:


# Todo: Unfix deltaP for F102
m.fs.F102.deltaP.unfix()


# In[59]:


assert degrees_of_freedom(m) == 4


# Next, we need to set bounds on these decision variables to values shown below:
# 
#  - H101 outlet temperature [500, 600] K
#  - F101 outlet temperature [298, 450] K
#  - F102 outlet temperature [298, 450] K
#  - F102 outlet pressure [105000, 110000] Pa
# 
# Let us first set the variable bound for the H101 outlet temperature as shown below:

# In[60]:


m.fs.H101.outlet.temperature[0].setlb(500)
m.fs.H101.outlet.temperature[0].setub(600)


# <div class="alert alert-block alert-info">
# <b>Inline Exercise:</b>
# Now, set the variable bound for the F101 outlet temperature.
# 
# Use Shift+Enter to run the cell once you have typed in your code. 
# </div>

# In[61]:


# Todo: Set the bounds for flash 101 outlet temperature


# In[62]:


# Todo: Set the bounds for reactor outlet temperature
m.fs.F101.vap_outlet.temperature[0].setlb(298.0)
m.fs.F101.vap_outlet.temperature[0].setub(450.0)


# Let us fix the bounds for the rest of the decision variables. 

# In[63]:


m.fs.F102.vap_outlet.temperature[0].setlb(298.0)
m.fs.F102.vap_outlet.temperature[0].setub(450.0)
m.fs.F102.vap_outlet.pressure[0].setlb(105000)
m.fs.F102.vap_outlet.pressure[0].setub(110000)


# Now, the only things left to define are our constraints on overhead loss in F101, product flow rate and purity in F102. Let us first look at defining a constraint for the overhead loss in F101 where we are restricting the benzene leaving the vapor stream to less than 20 \% of the benzene available in the reactor outlet. 

# In[64]:


m.fs.overhead_loss = Constraint(
    expr=m.fs.F101.control_volume.properties_out[0].flow_mol_phase_comp[
        "Vap", "benzene"
    ]
    <= 0.20
    * m.fs.R101.control_volume.properties_out[0].flow_mol_phase_comp["Vap", "benzene"]
)


# <div class="alert alert-block alert-info">
# <b>Inline Exercise:</b>
# Now, add the constraint such that we are producing at least 0.15 mol/s of benzene in the product stream which is the vapor outlet of F102. Let us name this constraint as m.fs.product_flow. 
# 
# Use Shift+Enter to run the cell once you have typed in your code. 
# </div>

# In[65]:


# Todo: Add minimum product flow constraint


# In[66]:


# Todo: Add minimum product flow constraint
m.fs.product_flow = Constraint(
    expr=m.fs.F102.control_volume.properties_out[0].flow_mol_phase_comp[
        "Vap", "benzene"
    ]
    >= 0.15
)


# Let us add the final constraint on product purity or the mole fraction of benzene in the product stream such that it is at least greater than 80%. 

# In[67]:


m.fs.product_purity = Constraint(expr=m.fs.purity >= 0.80)


# 
# We have now defined the optimization problem and we are now ready to solve this problem. 
# 
# 
# 

# In[68]:


results = solver.solve(m, tee=False)


# In[69]:


# Check for solver solve status
from pyomo.environ import TerminationCondition

assert results.solver.termination_condition == TerminationCondition.optimal


# ### 8.1 Optimization Results
# 
# Display the results and product specifications

# In[70]:


print("operating cost = $", value(m.fs.operating_cost))

print()
print("Product flow rate and purity in F102")

m.fs.F102.report()

print()
print("benzene purity = ", value(m.fs.purity))

print()
print("Overhead loss in F101")
m.fs.F101.report()


# In[71]:


assert value(m.fs.operating_cost) == pytest.approx(312674.236, rel=1e-4)
assert value(m.fs.purity) == pytest.approx(0.818827, rel=1e-4)


# Display optimal values for the decision variables

# In[72]:


print(
    f"""Optimal Values:

H101 outlet temperature = {value(m.fs.H101.outlet.temperature[0]):.3f} K

R101 heat duty = {value(m.fs.R101.heat_duty[0]):.3f} W

F101 outlet temperature = {value(m.fs.F101.vap_outlet.temperature[0]):.3f} K

F102 outlet temperature = {value(m.fs.F102.vap_outlet.temperature[0]):.3f} K
F102 outlet pressure = {value(m.fs.F102.vap_outlet.pressure[0]):.3f} Pa
"""
)


# In[73]:


assert value(m.fs.H101.outlet.temperature[0]) == pytest.approx(500, rel=1e-4)
assert value(m.fs.R101.heat_duty[0]) == pytest.approx(-13766.243, rel=1e-4)
assert value(m.fs.F101.vap_outlet.temperature[0]) == pytest.approx(301.881, rel=1e-4)
assert value(m.fs.F102.vap_outlet.temperature[0]) == pytest.approx(362.935, rel=1e-4)
assert value(m.fs.F102.vap_outlet.pressure[0]) == pytest.approx(105000, rel=1e-4)

