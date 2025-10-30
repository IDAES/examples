import numpy as np

import pyomo.environ as pyo
from pyomo.core.base.componentuid import ComponentUID

from idaes_examples.mod.power_gen.soc_nmpc.nmpc_tracking_LMP_settings import time_mark_list, scenario_names, df

class SocAttr:
    def __init__(self):
        self.alias_dict = {
            "fs.lmp": "lmp",
            "fs.total_electric_power": "total_electric_power",
            "fs.h2_mass_production": "h2_production_rate",
            "fs.h2_mass_consumption": "h2_consumption_rate",
            "fs.soc_module.potential_cell": "potential",
            "fs.soc_module.fuel_outlet_mole_frac_comp_H2": "soc_fuel_outlet_mole_frac_comp_H2",
            "fs.makeup_mix._flow_mol_makeup_ref": "makeup_feed_rate",
            "fs.sweep_blower._flow_mol_inlet_ref": "sweep_feed_rate",
            "fs.feed_heater.electric_heat_duty": "feed_heater_duty",
            "fs.feed_heater._temperature_outlet_ref": "feed_heater_outlet_temperature",
            "fs.soc_module._temperature_fuel_outlet_ref": "fuel_outlet_temperature",
            "fs.sweep_heater.electric_heat_duty": "sweep_heater_duty",
            "fs.sweep_heater._temperature_outlet_ref": "sweep_heater_outlet_temperature",
            "fs.soc_module._temperature_oxygen_outlet_ref": "sweep_outlet_temperature",
            "fs.stack_core_temperature": "stack_core_temperature",
            "fs.feed_recycle_split.recycle_ratio": "fuel_recycle_ratio",
            "fs.sweep_recycle_split.recycle_ratio": "sweep_recycle_ratio",
            "fs.sweep_recycle_split.mixed_state.mole_frac_comp[O2]": "oxygen_out",
            "fs.feed_recycle_mix.mixed_state.mole_frac_comp[H2]": "hydrogen_in",
            "fs.condenser_split.recycle_ratio": "vgr_recycle_ratio",
            "fs.makeup_mix.makeup_mole_frac_comp_H2": "makeup_mole_frac_comp_H2",
        }

        self.setpoint_params = {
            "fs.lmp":"lmp",
            "fs.total_electric_power_sp": "total_electric_power",
            "fs.h2_target_sp": "h2_production_rate",
            "fs.h2_consumption_target_sp": "h2_consumption_rate",
            "fs.potential_sp": "potential",
            "fs.soc_fuel_outlet_mole_frac_comp_H2_sp": "soc_fuel_outlet_mole_frac_comp_H2",
            "fs.makeup_feed_rate_sp": "makeup_feed_rate",
            "fs.sweep_feed_rate_sp": "sweep_feed_rate",
            "fs.feed_heater_duty_sp": "feed_heater_duty",
            "fs.feed_heater_outlet_temperature_sp": "feed_heater_outlet_temperature",
            "fs.fuel_outlet_temperature_sp": "fuel_outlet_temperature",
            "fs.sweep_heater_duty_sp": "sweep_heater_duty",
            "fs.sweep_heater_outlet_temperature_sp": "sweep_heater_outlet_temperature",
            "fs.sweep_outlet_temperature_sp": "sweep_outlet_temperature",
            "fs.stack_core_temperature_sp": "stack_core_temperature",
            "fs.fuel_recycle_ratio_sp": "fuel_recycle_ratio",
            "fs.sweep_recycle_ratio_sp": "sweep_recycle_ratio",
            "fs.oxygen_out_sp": "oxygen_out",
            "fs.hydrogen_in_sp": "hydrogen_in",
            "fs.vgr_recycle_ratio_sp": "vgr_recycle_ratio",
            "fs.makeup_mole_frac_comp_H2_sp": "makeup_mole_frac_comp_H2",
        }
        return None

    def make_sp_trajs(self, tset):
        """
        Function to create setpoint trajectories for all variables
        """
        def make_one_var_traj(alias, tset):
            """
            Function to write a trajectory for a variable 
            """
            def make_traj_point(t, t1, t2, y1, y2):
                """
                Interpolation between two time points
                """
                a = (y2 - y1) / (t2 - t1)
                return y1 + (t - t1) * a

            var_target = {t: 0.0 for t in tset}
            for t in tset:
                for i in range(len(time_mark_list)):
                    if t < time_mark_list[i]:
                        lmp_sp_index = np.floor(i / 2) 
                        scenario_index = i - 1
                        current_scenario = scenario_names[scenario_index]

                        if current_scenario == "t_ramp":
                            var_target[t] = make_traj_point(t,
                                                            time_mark_list[i - 1], time_mark_list[i],
                                                            df[alias][lmp_sp_index - 1], df[alias][lmp_sp_index])
                        elif current_scenario == "t_settle":
                            var_target[t] = df[alias][lmp_sp_index]
                        elif current_scenario == "t_start":
                            var_target[t] = df[alias][0]
                        break
                    else:
                        var_target[t] = df[alias].iloc[-1]

            return var_target

        var_trajs = {alias: {} for alias in self.alias_dict.values()}
        for alias in var_trajs:
            var_trajs[alias] = make_one_var_traj(alias, tset)

        return var_trajs
    
    def update_sp(self, m , t_base, var_targets):
        for key, val in self.setpoint_params.items():
            component = ComponentUID(key).find_component_on(m)
            component_targets = var_targets[val]
            for t in m.fs.time:
                component[t].value = component_targets[t_base + t]
       
    def update_coeff(self, m):
        def adapt_sp_order(var):
            if np.sqrt(pyo.value(var)) <= 1e-5:
                return 1e+5
            nearest_order = int(np.round(np.log10(np.sqrt(pyo.value(var)))))
            return np.round(np.power(1e-01, nearest_order), decimals=nearest_order)

        for t in m.fs.time:
            m.fs.makeup_feed_rate_coeff[t] = adapt_sp_order(
                (m.fs.makeup_mix.makeup.flow_mol[t] - m.fs.makeup_feed_rate_sp[t]) ** 2
            )
            m.fs.sweep_feed_rate_coeff[t] = adapt_sp_order(
                (m.fs.sweep_blower.inlet.flow_mol[t] - m.fs.sweep_feed_rate_sp[t]) ** 2
            )
            m.fs.potential_coeff[t] = adapt_sp_order(
                (m.fs.soc_module.potential_cell[t] - m.fs.potential_sp[t]) ** 2
            )
            m.fs.fuel_recycle_ratio_coeff[t] = adapt_sp_order(
                (m.fs.feed_recycle_split.recycle_ratio[t] - m.fs.fuel_recycle_ratio_sp[t]) ** 2
            )
            m.fs.sweep_recycle_ratio_coeff[t] = adapt_sp_order(
                (m.fs.sweep_recycle_split.recycle_ratio[t] - m.fs.sweep_recycle_ratio_sp[t]) ** 2
            )
            m.fs.vgr_recycle_ratio_coeff[t] = adapt_sp_order(
                (m.fs.condenser_split.recycle_ratio[t] - m.fs.vgr_recycle_ratio_sp[t]) ** 2
            )
        
            m.fs.makeup_mole_frac_comp_H2_coeff[t] = adapt_sp_order(
                (m.fs.makeup_mix.makeup_mole_frac_comp_H2[t] - m.fs.makeup_mole_frac_comp_H2_sp[t]) ** 2
            )
            
            m.fs.soc_fuel_outlet_mole_frac_comp_H2_coeff[t] = adapt_sp_order(
                (m.fs.soc_module.fuel_outlet_mole_frac_comp_H2[t] - m.fs.soc_fuel_outlet_mole_frac_comp_H2_sp[t]) ** 2
            )
            m.fs.feed_heater_outlet_temperature_coeff[t] = adapt_sp_order(
                (m.fs.feed_heater.outlet.temperature[t] - m.fs.feed_heater_outlet_temperature_sp[t]) ** 2
            )
            m.fs.sweep_heater_outlet_temperature_coeff[t] = adapt_sp_order(
                (m.fs.sweep_heater.outlet.temperature[t] - m.fs.sweep_heater_outlet_temperature_sp[t]) ** 2
            )
            m.fs.fuel_outlet_temperature_coeff[t] = adapt_sp_order(
                (m.fs.soc_module.fuel_outlet.temperature[t] - m.fs.fuel_outlet_temperature_sp[t]) ** 2
            )
            m.fs.sweep_outlet_temperature_coeff[t] = adapt_sp_order(
                (m.fs.soc_module.oxygen_outlet.temperature[t] - m.fs.sweep_outlet_temperature_sp[t]) ** 2
            )
            m.fs.stack_core_temperature_coeff[t] = adapt_sp_order(
                (m.fs.stack_core_temperature[t] - m.fs.stack_core_temperature_sp[t]) ** 2
            )
            m.fs.oxygen_out_coeff[t] = adapt_sp_order(
                (m.fs.sweep_recycle_split.mixed_state[t].mole_frac_comp['O2'] - m.fs.oxygen_out_sp[t]) ** 2
            )
            m.fs.hydrogen_in_coeff[t] = adapt_sp_order(
                (m.fs.feed_recycle_mix.mixed_state[t].mole_frac_comp['H2'] - m.fs.hydrogen_in_sp[t]) ** 2
            )


    