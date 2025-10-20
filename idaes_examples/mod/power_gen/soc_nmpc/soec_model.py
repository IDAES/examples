import pyomo.environ as pyo
from pyomo.dae import DerivativeVar
from pyomo.dae.flatten import flatten_dae_components

import idaes.core.util.scaling as iscale
import idaes.core.util.model_serializer as ms
from idaes.core.util.model_statistics import degrees_of_freedom

from idaes_examples.mod.power_gen.soc_dynamic_flowsheet import SocStandaloneFlowsheet
from idaes_examples.mod.power_gen.soc_nmpc.nmpc_tracking_LMP_settings import t_step

def get_CVs(m):
        return [
            m.fs.soc_module.fuel_outlet_mole_frac_comp_H2,
            m.fs.feed_heater._temperature_outlet_ref,
            m.fs.soc_module._temperature_fuel_outlet_ref,
            m.fs.sweep_heater._temperature_outlet_ref,
            m.fs.soc_module._temperature_oxygen_outlet_ref,
            m.fs.stack_core_temperature,
        ]
    
def get_MVs(m):
    return [
        m.fs.soc_module.potential_cell,
        m.fs.makeup_mix._flow_mol_makeup_ref,
        m.fs.sweep_blower._flow_mol_inlet_ref,
        m.fs.condenser_split.recycle_ratio,
        m.fs.feed_heater.electric_heat_duty,
        m.fs.sweep_heater.electric_heat_duty,
        m.fs.feed_recycle_split.recycle_ratio,
        m.fs.sweep_recycle_split.recycle_ratio,
        m.fs.makeup_mix.makeup_mole_frac_comp_H2,
    ]
    
def get_dMVs(m):
    return [
        m.fs.soc_module.dpotential_cell,
        m.fs.makeup_mix.dmakeup_flow_mol,
        m.fs.sweep_blower.dinlet_flow_mol,
        m.fs.condenser_split.drecycle_ratio,
        m.fs.feed_heater.delectric_heat_duty,
        m.fs.sweep_heater.delectric_heat_duty,
        m.fs.feed_recycle_split.drecycle_ratio,
        m.fs.sweep_recycle_split.drecycle_ratio,
        m.fs.makeup_mix.dmakeup_mole_frac_comp_H2,
    ]

def get_state_vars(m):
    soec = m.fs.soc_module.solid_oxide_cell
    state_vars = [
        soec.fuel_electrode.int_energy_density_solid,
        soec.interconnect.int_energy_density_solid,
        m.fs.sweep_exchanger.heat_holdup,
        m.fs.feed_medium_exchanger.heat_holdup,
        m.fs.feed_hot_exchanger.heat_holdup,
        m.fs.feed_heater.heat_holdup,
        m.fs.sweep_heater.heat_holdup,
    ]

    time_derivative_vars = [
        var for var in m.component_objects(pyo.Var)
        if isinstance(var, DerivativeVar)
    ]
    state_vars_temp = [
        dv.get_state_var() for dv in time_derivative_vars
        if (m.fs.time in dv.index_set().subsets()) and (dv.get_state_var() not in get_MVs(m))
    ]
    state_vars.extend(state_vars_temp)
    
    time_indexed_state_vars = []
    for v in state_vars:
        not_time_sets = None
        idx_sets = v.index_set().subsets()
        for s in idx_sets:
            if s not in [m.fs.time]:
                if not_time_sets is None:
                    not_time_sets = s
                else:
                    not_time_sets *= s
        
        if not_time_sets is not None:
            for ts in not_time_sets:
                time_indexed_state_vars.append(v[:, ts])       
    return time_indexed_state_vars



def create_model(tset, nfe, plant, init_fname):
        m = pyo.ConcreteModel()
        m.fs = SocStandaloneFlowsheet(
            dynamic=True,
            time_set=tset,
            time_units=pyo.units.s,
            thin_electrolyte_and_oxygen_electrode=True,
            include_interconnect=True,
        )
        t0 = m.fs.time.first()
        soec = m.fs.soc_module.solid_oxide_cell

        m.fs.soc_module.Dpotential_cell = DerivativeVar(m.fs.soc_module.potential_cell, wrt=m.fs.time, initialize=0)
        m.fs.makeup_mix.Dmakeup_flow_mol = DerivativeVar(m.fs.makeup_mix._flow_mol_makeup_ref, wrt=m.fs.time, initialize=0)
        m.fs.sweep_blower.Dinlet_flow_mol = DerivativeVar(m.fs.sweep_blower._flow_mol_inlet_ref, wrt=m.fs.time, initialize=0)
        m.fs.condenser_split.Drecycle_ratio = DerivativeVar(m.fs.condenser_split.recycle_ratio, wrt=m.fs.time, initialize=0)
        m.fs.feed_heater.Delectric_heat_duty = DerivativeVar(m.fs.feed_heater.electric_heat_duty, wrt=m.fs.time, initialize=0)
        m.fs.sweep_heater.Delectric_heat_duty = DerivativeVar(m.fs.sweep_heater.electric_heat_duty, wrt=m.fs.time, initialize=0)
        m.fs.feed_recycle_split.Drecycle_ratio = DerivativeVar(m.fs.feed_recycle_split.recycle_ratio, wrt=m.fs.time, initialize=0)
        m.fs.sweep_recycle_split.Drecycle_ratio = DerivativeVar(m.fs.sweep_recycle_split.recycle_ratio, wrt=m.fs.time, initialize=0)
        m.fs.makeup_mix.Dmakeup_mole_frac_comp_H2 = DerivativeVar(m.fs.makeup_mix.makeup_mole_frac_comp_H2, wrt=m.fs.time, initialize=0)

        m.fs.soc_module.dpotential_cell = pyo.Var(m.fs.time, initialize=0)
        m.fs.makeup_mix.dmakeup_flow_mol = pyo.Var(m.fs.time, initialize=0)
        m.fs.sweep_blower.dinlet_flow_mol = pyo.Var(m.fs.time, initialize=0)
        m.fs.condenser_split.drecycle_ratio = pyo.Var(m.fs.time, initialize=0)
        m.fs.feed_heater.delectric_heat_duty = pyo.Var(m.fs.time, initialize=0)
        m.fs.sweep_heater.delectric_heat_duty = pyo.Var(m.fs.time, initialize=0)
        m.fs.feed_recycle_split.drecycle_ratio = pyo.Var(m.fs.time, initialize=0)
        m.fs.sweep_recycle_split.drecycle_ratio = pyo.Var(m.fs.time, initialize=0)
        m.fs.makeup_mix.dmakeup_mole_frac_comp_H2 = pyo.Var(m.fs.time, initialize=0)


        @m.fs.soc_module.Constraint(m.fs.time)
        def dpotential_cell_eqn(b, t):
            return b.dpotential_cell[t] == b.Dpotential_cell[t]

        @m.fs.makeup_mix.Constraint(m.fs.time)
        def dmakeup_flow_mol_eqn(b, t):
            return b.dmakeup_flow_mol[t] == b.Dmakeup_flow_mol[t]

        @m.fs.sweep_blower.Constraint(m.fs.time)
        def dinlet_flow_mol_eqn(b, t):
            return b.dinlet_flow_mol[t] == b.Dinlet_flow_mol[t]

        @m.fs.condenser_split.Constraint(m.fs.time)
        def dcondenser_recycle_ratio_eqn(b, t):
            return b.drecycle_ratio[t] == b.Drecycle_ratio[t]

        @m.fs.feed_heater.Constraint(m.fs.time)
        def dfeed_electric_heat_duty_eqn(b, t):
            return b.delectric_heat_duty[t] == b.Delectric_heat_duty[t]

        @m.fs.sweep_heater.Constraint(m.fs.time)
        def dsweep_electric_heat_duty_eqn(b, t):
            return b.delectric_heat_duty[t] == b.Delectric_heat_duty[t]

        @m.fs.feed_recycle_split.Constraint(m.fs.time)
        def dfeed_recycle_ratio_eqn(b, t):
            return b.drecycle_ratio[t] == b.Drecycle_ratio[t]

        @m.fs.sweep_recycle_split.Constraint(m.fs.time)
        def dsweep_recycle_ratio_eqn(b, t):
            return b.drecycle_ratio[t] == b.Drecycle_ratio[t]

        @m.fs.makeup_mix.Constraint(m.fs.time)
        def dmakeup_mole_frac_comp_H2_eqn(b, t):
            return b.dmakeup_mole_frac_comp_H2[t] == b.Dmakeup_mole_frac_comp_H2[t]

        # Remove bounds on certain variables to reduce the chance of restoration.
        for t in m.fs.time:
            m.fs.condenser_flash.control_volume.properties_in[t].flow_mol_phase["Liq"].domain = pyo.Reals
            m.fs.condenser_flash.control_volume.properties_in[t].flow_mol_phase["Liq"].bounds = (None, None)
            m.fs.condenser_flash.control_volume.properties_in[t].phase_frac["Liq"].domain = pyo.Reals
            m.fs.condenser_flash.control_volume.properties_in[t].phase_frac["Liq"].bounds = (None, None)
            m.fs.condenser_flash.control_volume.properties_in[t].mole_frac_phase_comp["Liq","H2O"].domain = pyo.Reals
            m.fs.condenser_flash.control_volume.properties_in[t].mole_frac_phase_comp["Liq","H2O"].bounds = (None, None)
            m.fs.condenser_flash.control_volume.properties_in[t].log_mole_frac_phase_comp["Liq","H2O"].domain = pyo.Reals
            m.fs.condenser_flash.control_volume.properties_in[t].log_mole_frac_phase_comp["Liq","H2O"].bounds = (None, None)
            m.fs.condenser_flash.control_volume.properties_out[t].mole_frac_phase_comp["Liq","H2O"].domain = pyo.Reals
            m.fs.condenser_flash.control_volume.properties_out[t].mole_frac_phase_comp["Liq","H2O"].bounds = (None, None)
            m.fs.condenser_flash.control_volume.properties_out[t].log_mole_frac_phase_comp["Liq","H2O"].domain = pyo.Reals
            m.fs.condenser_flash.control_volume.properties_out[t].log_mole_frac_phase_comp["Liq","H2O"].bounds = (None, None)

            # m.fs.condenser_flash.control_volume.properties_in[t].log_mole_frac_comp[:].setlb(-28)
            # m.fs.condenser_flash.control_volume.properties_in[t].log_mole_frac_phase_comp["Vap",:].setlb(-28)
            # m.fs.condenser_flash.control_volume.properties_out[t].log_mole_frac_comp[:].setlb(-28)
            # m.fs.condenser_flash.control_volume.properties_out[t].log_mole_frac_phase_comp["Vap",:].setlb(-28)
            # m.fs.condenser_flash.control_volume.properties_in[t].mole_frac_comp[:].setlb(1e-12)
            # m.fs.condenser_flash.control_volume.properties_in[t].mole_frac_phase_comp["Vap",:].setlb(1e-12)
            # m.fs.condenser_flash.control_volume.properties_out[t].mole_frac_comp[:].setlb(1e-12)
            # m.fs.condenser_flash.control_volume.properties_out[t].mole_frac_phase_comp["Vap",:].setlb(1e-12)

            for var in [
                m.fs.condenser_flash.control_volume.properties_in[t]._mole_frac_tdew,
                m.fs.condenser_flash.control_volume.properties_in[t].log_mole_frac_tdew,
                m.fs.condenser_flash.control_volume.properties_out[t]._mole_frac_tdew,
                m.fs.condenser_flash.control_volume.properties_out[t].log_mole_frac_tdew,
            ]:
                for idx in var.index_set():
                    var[idx].domain = pyo.Reals
                    var[idx].bounds = (None, None)

        #Define soft constraints in controller model
        #@m.fs.Constraint(m.fs.time)
        #def makeup_mole_frac_sum_eqn(b, t):
        #    return b.makeup_mix.makeup_mole_frac_comp_H2[t] + b.makeup_mix.makeup_mole_frac_comp_H2O[t] == 0.99
        @m.fs.Constraint(m.fs.time)
        def sum_mole_frac_eqn(b, t):
            return 1 == sum(
                b.makeup_mix.makeup_state[t].mole_frac_comp[j]
                for j in b.makeup_mix.makeup_state[t].mole_frac_comp.index_set()
            )
        
       
        if not plant:
            #Define setpoints as mutable parameters.
            m.fs.lmp = pyo.Param(m.fs.time, initialize = 1e-6, mutable = True)
            m.fs.total_electric_power_sp = pyo.Param(m.fs.time, initialize = 1e-6, mutable = True)
            m.fs.h2_target_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.h2_consumption_target_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.potential_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.soc_fuel_outlet_mole_frac_comp_H2_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.makeup_feed_rate_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.sweep_feed_rate_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.feed_heater_duty_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.feed_heater_outlet_temperature_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.fuel_outlet_temperature_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.sweep_heater_duty_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.sweep_heater_outlet_temperature_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.sweep_outlet_temperature_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.stack_core_temperature_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.fuel_recycle_ratio_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.sweep_recycle_ratio_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.oxygen_out_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.hydrogen_in_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.vgr_recycle_ratio_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.makeup_mole_frac_comp_H2_sp = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)

            m.fs.potential_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.soc_fuel_outlet_mole_frac_comp_H2_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.makeup_feed_rate_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.sweep_feed_rate_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.feed_heater_duty_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.feed_heater_outlet_temperature_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.fuel_outlet_temperature_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.sweep_heater_duty_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.sweep_heater_outlet_temperature_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.sweep_outlet_temperature_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.stack_core_temperature_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.fuel_recycle_ratio_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.sweep_recycle_ratio_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.oxygen_out_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.hydrogen_in_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.vgr_recycle_ratio_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)
            m.fs.makeup_mole_frac_comp_H2_coeff = pyo.Param(m.fs.time, initialize=1e-6, mutable=True)

            
            # Constraints on avg current density as soft constraints(L1) penalty in objective function
            # m.fs.avg_curr_density_p = pyo.Var(m.fs.time, initialize = 0, domain=pyo.NonNegativeReals)
            # m.fs.avg_curr_density_n = pyo.Var(m.fs.time, initialize = 0, domain=pyo.NonPositiveReals)

            # m.fs.pointwise_curr_density_p = pyo.Var(m.fs.time, m.fs.soc_module.solid_oxide_cell.iznodes, initialize = 0, domain=pyo.NonNegativeReals)
            # m.fs.pointwise_curr_density_n = pyo.Var(m.fs.time, m.fs.soc_module.solid_oxide_cell.iznodes, initialize = 0, domain=pyo.NonPositiveReals)
            # @m.fs.Constraint(m.fs.time)
            # def current_density_average_limit_eqn_fuelcell_mode(b, t):
            #     return sum([b.soc_module.solid_oxide_cell.current_density[t, iz]
            #                 for iz in b.soc_module.solid_oxide_cell.iznodes]
            #             ) / 10 <= 4e3 #+ b.avg_curr_density_p[t]
            
            # @m.fs.Constraint(m.fs.time)
            # def current_density_average_limit_eqn_electrolysis(b, t):
            #     return sum([b.soc_module.solid_oxide_cell.current_density[t, iz]
            #                 for iz in b.soc_module.solid_oxide_cell.iznodes]
            #             ) / 10 >= -1e4 #+ b.avg_curr_density_n[t]
            
            # @m.fs.Constraint(m.fs.time, m.fs.soc_module.solid_oxide_cell.iznodes)
            # def current_density_pointwise_limit_eqn_fuelcell_mode(b, t, iz):
            #     return b.soc_module.solid_oxide_cell.current_density[t, iz]<= 5.2e3 + b.pointwise_curr_density_p[t, iz]
            
            # @m.fs.Constraint(m.fs.time, m.fs.soc_module.solid_oxide_cell.iznodes)
            # def current_density_pointwise_limit_eqn_electrolysis(b, t, iz):
            #     return b.soc_module.solid_oxide_cell.current_density[t, iz] >= -1.3e4 + b.pointwise_curr_density_n[t, iz]

            # m.fs.soc_module.solid_oxide_cell.current_density[:, :].setlb(-1.3e4)
            # m.fs.soc_module.solid_oxide_cell.current_density[:, :].setub(5.2e3)
            m.fs.sweep_heater.electric_heat_duty[:].setlb(0)
            m.fs.feed_heater.electric_heat_duty[:].setlb(0)
            m.fs.sweep_heater.electric_heat_duty[:].setub(4e+06)
            m.fs.feed_heater.electric_heat_duty[:].setub(2e+06)
            
            m.fs.condenser_flash.control_volume.properties_in[:].log_mole_frac_comp[:].setlb(-19)
            m.fs.condenser_flash.control_volume.properties_in[:].log_mole_frac_phase_comp["Vap",:].setlb(-19)
            m.fs.condenser_flash.control_volume.properties_out[:].log_mole_frac_comp[:].setlb(-19)
            m.fs.condenser_flash.control_volume.properties_out[:].log_mole_frac_phase_comp["Vap",:].setlb(-19)

            m.fs.condenser_flash.control_volume.properties_in[:].mole_frac_comp[:].setlb(1e-8)
            m.fs.condenser_flash.control_volume.properties_in[:].mole_frac_phase_comp["Vap",:].setlb(1e-8)
            m.fs.condenser_flash.control_volume.properties_out[:].mole_frac_comp[:].setlb(1e-8)
            m.fs.condenser_flash.control_volume.properties_out[:].mole_frac_phase_comp["Vap",:].setlb(1e-8)

    
        iscale.calculate_scaling_factors(m)

        pyo.TransformationFactory("dae.finite_difference").apply_to(
            m.fs, nfe=nfe, wrt=m.fs.time, scheme="BACKWARD"
        )

        #Load saved steady state solution.
        ms.from_json(m, fname=init_fname, wts=ms.StoreSpec.value())

        #Copy initial conditions to the rest of the model for initialization.
        _, time_vars = flatten_dae_components(m, m.fs.time, pyo.Var)
        for t in m.fs.time:
            for v in time_vars:
                if not v[t].fixed:
                    if v[t0].value is None:
                        v[t].set_value(0.0)
                    else:
                        v[t].set_value(v[t0].value)

        #Fix initial conditions of certain variables.
        m.fs.fix_initial_conditions()

        m.fs.condenser_flash.vap_outlet.temperature.fix(323.15)

        for v in get_dMVs(m):
            if plant:
                v.fix(v[t0].value)
            else:
                v[:].set_value(v[t0].value)
                v.unfix()

        for v in get_MVs(m):
            if plant:
                v.unfix()
                v[t0].fix()
            else:
                v[:].set_value(v[t0].value)
                v.unfix()
        
        #Initialize controlled variables.
        for v in get_CVs(m):
            v[:].set_value(v[t0].value)
        m.fs.sweep_recycle_split.mixed_state[:].mole_frac_comp['O2'].set_value(
            m.fs.sweep_recycle_split.mixed_state[t0].mole_frac_comp['O2'].value
            )
        m.fs.feed_recycle_mix.mixed_state[:].mole_frac_comp['H2'].set_value(
            m.fs.feed_recycle_mix.mixed_state[t0].mole_frac_comp['H2'].value
            )

        if plant:
            assert degrees_of_freedom(m) == 0
        
        #Fix split fraction equation in the condenser
        m.fs.condenser_split.recycle_ratio_eqn.deactivate()
        def _condenser_split_recycle_ratio_con(m, t):
            s = m.fs.condenser_split.split_fraction[t, "recycle"]
            r = m.fs.condenser_split.recycle_ratio[t]
            return s*(r + 1) - r == 0
        m.condenser_split_recycle_ratio_con = pyo.Constraint(m.fs.time, rule = _condenser_split_recycle_ratio_con)
        m.fs.condenser_split.split_fraction[:, "recycle"].setlb(1e-4)
        m.fs.condenser_split.split_fraction[:, "recycle"].setub(1)

        #Fix split fraction equation in the feed
        m.fs.feed_recycle_split.recycle_ratio_eqn.deactivate()
        def _feed_split_recycle_ratio_con(m, t):
            s = m.fs.feed_recycle_split.split_fraction[t, "recycle"]
            r = m.fs.feed_recycle_split.recycle_ratio[t]
            return s*(r + 1) - r == 0
        m.feed_split_recycle_ratio_con = pyo.Constraint(m.fs.time, rule = _feed_split_recycle_ratio_con)
        m.fs.feed_recycle_split.split_fraction[:, "recycle"].setlb(1e-4)
        m.fs.feed_recycle_split.split_fraction[:, "recycle"].setub(1)

        #Fix split fraction equn in the sweep 
        m.fs.sweep_recycle_split.recycle_ratio_eqn.deactivate()
        def _sweep_split_recycle_ratio_con(m, t):
            s = m.fs.sweep_recycle_split.split_fraction[t, "recycle"]
            r = m.fs.sweep_recycle_split.recycle_ratio[t]
            return s*(r + 1) - r == 0
        m.sweep_split_recycle_ratio_con = pyo.Constraint(m.fs.time, rule = _sweep_split_recycle_ratio_con)
        m.fs.sweep_recycle_split.split_fraction[:, "recycle"].setlb(1e-4)
        m.fs.sweep_recycle_split.split_fraction[:, "recycle"].setub(1)

        return m

def create_scaled_model(m, plant):
    iscale.scale_time_discretization_equations(m, m.fs.time, 1 / t_step)

    m_scaled = pyo.TransformationFactory('core.scale_model').create_using(m, rename=False)

    if not plant:
        m_scaled.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT_EXPORT)
        m_scaled.ipopt_zL_out = pyo.Suffix(direction=pyo.Suffix.IMPORT)
        m_scaled.ipopt_zU_out = pyo.Suffix(direction=pyo.Suffix.IMPORT)
        m_scaled.ipopt_zL_in = pyo.Suffix(direction=pyo.Suffix.EXPORT)
        m_scaled.ipopt_zU_in = pyo.Suffix(direction=pyo.Suffix.EXPORT)
    
    return m_scaled
