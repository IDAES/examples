import pyomo.environ as pyo
def create_tracking_obj_expr(m):
        t0 = m.fs.time.first()
        soec = m.fs.soc_module.solid_oxide_cell
        # Economic term
        # We need to minimize consumption when H2 is being consumed 
        # and maximize production when h2 is being produced 
        m.h2_consumption_param = pyo.Param(m.fs.time, initialize = 0, mutable = True)
        m.h2_production_param = pyo.Param(m.fs.time, initialize = 0, mutable = True)
        expr = 0

        expr += sum(
            m.h2_production_param[t]*(m.fs.h2_mass_production[t] - m.fs.h2_target_sp[t]) ** 2
            + m.h2_consumption_param[t]*(m.fs.h2_mass_consumption[t] - m.fs.h2_consumption_target_sp[t]) ** 2
            for t in m.fs.time if t != t0)
        
        m.weight_power = pyo.Param(initialize = 10, mutable = True)
        expr += m.weight_power * 1e-8 * sum(m.fs.p[t]-m.fs.n[t] for t in m.fs.time if t != t0)  

        # Penalties on maniplated variable deviations
        premultiplier = 1e-02
        expr += premultiplier * sum(m.fs.makeup_feed_rate_coeff[t] *
                                    (m.fs.makeup_mix.makeup.flow_mol[t] - m.fs.makeup_feed_rate_sp[t]) ** 2
                                    for t in list(m.fs.time)[1:])
        expr += premultiplier * sum(m.fs.sweep_feed_rate_coeff[t] *
                                    (m.fs.sweep_blower.inlet.flow_mol[t] - m.fs.sweep_feed_rate_sp[t]) ** 2
                                    for t in list(m.fs.time)[1:])
        expr += premultiplier * sum(m.fs.potential_coeff[t] *
                                    (m.fs.soc_module.potential_cell[t] - m.fs.potential_sp[t]) ** 2
                                    for t in list(m.fs.time)[1:])
        expr += premultiplier * sum(m.fs.fuel_recycle_ratio_coeff[t] *
                                    (m.fs.feed_recycle_split.recycle_ratio[t] - m.fs.fuel_recycle_ratio_sp[t]) ** 2
                                    for t in list(m.fs.time)[1:])
        expr += premultiplier * sum(m.fs.sweep_recycle_ratio_coeff[t] *
                                    (m.fs.sweep_recycle_split.recycle_ratio[t] - m.fs.sweep_recycle_ratio_sp[t]) ** 2
                                    for t in list(m.fs.time)[1:])
        expr += premultiplier * sum(m.fs.vgr_recycle_ratio_coeff[t] *
                                    (m.fs.condenser_split.recycle_ratio[t] - m.fs.vgr_recycle_ratio_sp[t]) ** 2
                                    for t in list(m.fs.time)[1:])
    
        expr += premultiplier * sum(m.fs.makeup_mole_frac_comp_H2_coeff[t] *
                                    (m.fs.makeup_mix.makeup_mole_frac_comp_H2[t] - m.fs.makeup_mole_frac_comp_H2_sp[t]) ** 2
                                    for t in list(m.fs.time)[1:])
        expr += premultiplier * sum(1e-12 *
                                    (m.fs.sweep_heater.electric_heat_duty[t] - m.fs.sweep_heater.electric_heat_duty[
                                        m.fs.time.prev(t)]) ** 2
                                    for t in list(m.fs.time)[1:])
        expr += premultiplier * sum(1e-12 *
                                    (m.fs.feed_heater.electric_heat_duty[t] - m.fs.feed_heater.electric_heat_duty[
                                        m.fs.time.prev(t)]) ** 2
                                    for t in list(m.fs.time)[1:])

        expr += premultiplier * sum(m.fs.soc_fuel_outlet_mole_frac_comp_H2_coeff[t] *
                                    (m.fs.soc_module.fuel_outlet_mole_frac_comp_H2[t] -
                                    m.fs.soc_fuel_outlet_mole_frac_comp_H2_sp[t]) ** 2
                                    for t in list(m.fs.time)[1:])
        expr += premultiplier * sum(m.fs.feed_heater_outlet_temperature_coeff[t] *
                                    (m.fs.feed_heater.outlet.temperature[t] - m.fs.feed_heater_outlet_temperature_sp[
                                        t]) ** 2
                                    for t in list(m.fs.time)[1:])
        expr += premultiplier * sum(m.fs.sweep_heater_outlet_temperature_coeff[t] *
                                    (m.fs.sweep_heater.outlet.temperature[t] - m.fs.sweep_heater_outlet_temperature_sp[
                                        t]) ** 2
                                    for t in list(m.fs.time)[1:])
        expr += premultiplier * sum(m.fs.fuel_outlet_temperature_coeff[t] *
                                    (m.fs.soc_module.fuel_outlet.temperature[t] - m.fs.fuel_outlet_temperature_sp[t]) ** 2
                                    for t in list(m.fs.time)[1:])
        expr += premultiplier * sum(m.fs.sweep_outlet_temperature_coeff[t] *
                                    (m.fs.soc_module.oxygen_outlet.temperature[t] - m.fs.sweep_outlet_temperature_sp[
                                        t]) ** 2
                                    for t in list(m.fs.time)[1:])
        expr += premultiplier * sum(m.fs.stack_core_temperature_coeff[t] *
                                    (m.fs.stack_core_temperature[t] - m.fs.stack_core_temperature_sp[t]) ** 2
                                    for t in list(m.fs.time)[1:])
        expr += premultiplier * sum(m.fs.oxygen_out_coeff[t] *
                                    (m.fs.sweep_recycle_split.mixed_state[t].mole_frac_comp['O2'] - m.fs.oxygen_out_sp[
                                        t]) ** 2
                                    for t in list(m.fs.time)[1:])
        expr += premultiplier * sum(m.fs.hydrogen_in_coeff[t] *
                                    (m.fs.feed_recycle_mix.mixed_state[t].mole_frac_comp['H2'] - m.fs.hydrogen_in_sp[
                                        t]) ** 2
                                    for t in list(m.fs.time)[1:])
        
        m.lyapunov_function = pyo.Expression(expr = expr)
        #Penalty on avg current density
        # expr += 1e-02 * sum(m.fs.avg_curr_density_p[t] - m.fs.avg_curr_density_n[t] for t in list(m.fs.time)[1:])
        # expr += 1e-02 * sum(sum(m.fs.pointwise_curr_density_p[t, iz] - m.fs.pointwise_curr_density_n[t, iz] for t in list(m.fs.time)[1:]) for iz in m.fs.soc_module.solid_oxide_cell.iznodes)
        return expr

def create_economic_obj_expr(m):
    t0 = m.fs.time.first()
    expr = 0
    
    # Economic term
    # We need to minimize consumption when H2 is being consumed 
    # and maximize production when h2 is being produced 
    m.h2_consumption_param = pyo.Param(m.fs.time, initialize = 0, mutable = True)
    m.h2_production_param = pyo.Param(m.fs.time, initialize = 0, mutable = True)
    
    expr += sum(m.h2_consumption_param[t]*m.fs.h2_mass_consumption[t] 
                - m.h2_production_param[t]*m.fs.h2_mass_production[t] 
                for t in m.fs.time if t != t0)
    
    # Penalty on power deviation
    # m.weight_power = pyo.Param(initialize = 10, mutable = True)
    
    # expr += m.weight_power * 1e-8*sum(m.fs.p[t]-m.fs.n[t] for t in m.fs.time if t != t0)

    # Battery term
    # expr += 1e-8 * sum((m.fs.total_electric_power_new[t]-m.fs.total_electric_power_sp)**2 for t in m.fs.time if t != t0)

    m.weight_power = pyo.Param(initialize = 10, mutable = True)

    expr += m.weight_power * 1e-8 * sum(m.fs.p[t]-m.fs.n[t] for t in m.fs.time if t != t0)  

    # Penalties on manipulated variable deviations
    premultiplier = 1e-2
    expr += premultiplier * sum(m.fs.makeup_feed_rate_coeff[t] *
                                (m.fs.makeup_mix.makeup.flow_mol[t] - m.fs.makeup_feed_rate_sp[t]) ** 2
                                for t in list(m.fs.time)[1:])
    expr += premultiplier * sum(m.fs.sweep_feed_rate_coeff[t] *
                                (m.fs.sweep_blower.inlet.flow_mol[t] - m.fs.sweep_feed_rate_sp[t]) ** 2
                                for t in list(m.fs.time)[1:])
    expr += premultiplier * sum(m.fs.potential_coeff[t] *
                                (m.fs.soc_module.potential_cell[t] - m.fs.potential_sp[t]) ** 2
                                for t in list(m.fs.time)[1:])
    expr += premultiplier * sum(m.fs.fuel_recycle_ratio_coeff[t] *
                                (m.fs.feed_recycle_split.recycle_ratio[t] - m.fs.fuel_recycle_ratio_sp[t]) ** 2
                                for t in list(m.fs.time)[1:])
    expr += premultiplier * sum(m.fs.sweep_recycle_ratio_coeff[t] *
                                (m.fs.sweep_recycle_split.recycle_ratio[t] - m.fs.sweep_recycle_ratio_sp[t]) ** 2
                                for t in list(m.fs.time)[1:])    
    
    expr += premultiplier * sum(m.fs.vgr_recycle_ratio_coeff[t] *
                                (m.fs.condenser_split.recycle_ratio[t] - m.fs.vgr_recycle_ratio_sp[t]) ** 2
                                for t in list(m.fs.time)[1:])

    expr += premultiplier * sum(m.fs.makeup_mole_frac_comp_H2_coeff[t] *
                                (m.fs.makeup_mix.makeup_mole_frac_comp_H2[t] - m.fs.makeup_mole_frac_comp_H2_sp[t]) ** 2
                                for t in list(m.fs.time)[1:])
    
    expr += premultiplier * sum(1e-12 *
                                (m.fs.sweep_heater.electric_heat_duty[t] - m.fs.sweep_heater.electric_heat_duty[
                                    m.fs.time.prev(t)]) ** 2
                                for t in list(m.fs.time)[1:])
    expr += premultiplier * sum(1e-12 *
                                (m.fs.feed_heater.electric_heat_duty[t] - m.fs.feed_heater.electric_heat_duty[
                                    m.fs.time.prev(t)]) ** 2
                                for t in list(m.fs.time)[1:])

    expr += premultiplier * sum(m.fs.soc_fuel_outlet_mole_frac_comp_H2_coeff[t] *
                                (m.fs.soc_module.fuel_outlet_mole_frac_comp_H2[t] -
                                m.fs.soc_fuel_outlet_mole_frac_comp_H2_sp[t]) ** 2
                                for t in list(m.fs.time)[1:])
    expr += premultiplier * sum(m.fs.feed_heater_outlet_temperature_coeff[t] *
                                (m.fs.feed_heater.outlet.temperature[t] - m.fs.feed_heater_outlet_temperature_sp[
                                    t]) ** 2
                                for t in list(m.fs.time)[1:])
    expr += premultiplier * sum(m.fs.sweep_heater_outlet_temperature_coeff[t] *
                                (m.fs.sweep_heater.outlet.temperature[t] - m.fs.sweep_heater_outlet_temperature_sp[
                                    t]) ** 2
                                for t in list(m.fs.time)[1:])
    expr += premultiplier * sum(m.fs.fuel_outlet_temperature_coeff[t] *
                                (m.fs.soc_module.fuel_outlet.temperature[t] - m.fs.fuel_outlet_temperature_sp[t]) ** 2
                                for t in list(m.fs.time)[1:])
    expr += premultiplier * sum(m.fs.sweep_outlet_temperature_coeff[t] *
                                (m.fs.soc_module.oxygen_outlet.temperature[t] - m.fs.sweep_outlet_temperature_sp[
                                    t]) ** 2
                                for t in list(m.fs.time)[1:])
    expr += premultiplier * sum(m.fs.stack_core_temperature_coeff[t] *
                                (m.fs.stack_core_temperature[t] - m.fs.stack_core_temperature_sp[t]) ** 2
                                for t in list(m.fs.time)[1:])
    expr += premultiplier * sum(m.fs.oxygen_out_coeff[t] *
                                (m.fs.sweep_recycle_split.mixed_state[t].mole_frac_comp['O2'] - m.fs.oxygen_out_sp[
                                    t]) ** 2
                                for t in list(m.fs.time)[1:])
    expr += premultiplier * sum(m.fs.hydrogen_in_coeff[t] *
                                (m.fs.feed_recycle_mix.mixed_state[t].mole_frac_comp['H2'] - m.fs.hydrogen_in_sp[
                                    t]) ** 2
                                for t in list(m.fs.time)[1:])
    
    #Penalty on avg current density
    # expr += 1 * sum(m.fs.avg_curr_density_p[t] - m.fs.avg_curr_density_n[t] for t in m.fs.time)
    # expr += 1 * sum(sum(m.fs.pointwise_curr_density_p[t, iz] - m.fs.pointwise_curr_density_n[t, iz] for t in list(m.fs.time)[1:]) for iz in m.fs.soc_module.solid_oxide_cell.iznodes)
    return expr