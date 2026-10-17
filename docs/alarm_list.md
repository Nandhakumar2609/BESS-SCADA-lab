# Alarm list

_Generated from `config/alarms.yaml` by `tools/gen_docs.py`. Bitfield alarms are expanded per bit._

46 alarm instances. Severity: critical = trip / loss of function, major = action today, minor = action this week, warning = information.

| Alarm ID | Device | Severity | Type | Condition | Deadband | On-delay | Message |
|---|---|---|---|---|---|---|---|
| BMS_ALARM_CELL_OVERTEMP | bms01 | critical | bitfield | `alarm_word` bit 2 |  | 0 s | BMS alarm: CELL_OVERTEMP |
| BMS_ALARM_CELL_OVERVOLTAGE | bms01 | critical | bitfield | `alarm_word` bit 0 |  | 0 s | BMS alarm: CELL_OVERVOLTAGE |
| BMS_ALARM_CELL_UNDERVOLTAGE | bms01 | critical | bitfield | `alarm_word` bit 1 |  | 0 s | BMS alarm: CELL_UNDERVOLTAGE |
| BMS_ALARM_CONTACTOR_FAULT | bms01 | critical | bitfield | `alarm_word` bit 6 |  | 0 s | BMS alarm: CONTACTOR_FAULT |
| BMS_ALARM_FIRE_DETECTION | bms01 | critical | bitfield | `alarm_word` bit 7 |  | 0 s | BMS alarm: FIRE_DETECTION |
| BMS_CELL_OV | bms01 | critical | high | `max_cell_voltage_v` > 3.6 | 0.03 | 4 s | Cell over-voltage |
| BMS_CELL_UV | bms01 | critical | low | `min_cell_voltage_v` < 2.8 | 0.05 | 4 s | Cell under-voltage |
| COMMS_LOSS | bms01 | critical | comms | no Modbus response |  | 6 s | Modbus communication lost |
| COMMS_LOSS | hvac01 | critical | comms | no Modbus response |  | 6 s | Modbus communication lost |
| COMMS_LOSS | meter_aux | critical | comms | no Modbus response |  | 6 s | Modbus communication lost |
| COMMS_LOSS | meter_poi | critical | comms | no Modbus response |  | 6 s | Modbus communication lost |
| COMMS_LOSS | pcs01 | critical | comms | no Modbus response |  | 6 s | Modbus communication lost |
| PCS_FAULT_DC_OVERVOLTAGE | pcs01 | critical | bitfield | `fault_word` bit 4 |  | 0 s | PCS fault: DC_OVERVOLTAGE |
| PCS_FAULT_EMERGENCY_STOP | pcs01 | critical | bitfield | `fault_word` bit 7 |  | 0 s | PCS fault: EMERGENCY_STOP |
| PCS_FAULT_GRID_OVERVOLTAGE | pcs01 | critical | bitfield | `fault_word` bit 1 |  | 0 s | PCS fault: GRID_OVERVOLTAGE |
| PCS_FAULT_GRID_UNDERVOLTAGE | pcs01 | critical | bitfield | `fault_word` bit 2 |  | 0 s | PCS fault: GRID_UNDERVOLTAGE |
| PCS_FAULT_IGBT_OVERTEMP | pcs01 | critical | bitfield | `fault_word` bit 0 |  | 0 s | PCS fault: IGBT_OVERTEMP |
| PCS_FAULT_INSULATION_FAULT | pcs01 | critical | bitfield | `fault_word` bit 5 |  | 0 s | PCS fault: INSULATION_FAULT |
| BMS_ALARM_CELL_UNDERTEMP | bms01 | major | bitfield | `alarm_word` bit 3 |  | 0 s | BMS alarm: CELL_UNDERTEMP |
| BMS_ALARM_INSULATION_LOW | bms01 | major | bitfield | `alarm_word` bit 5 |  | 0 s | BMS alarm: INSULATION_LOW |
| BMS_CELL_OT | bms01 | major | high | `max_cell_temp_c` > 45 | 3 | 4 s | Cell temperature high |
| BMS_INSULATION_LOW | bms01 | major | low | `insulation_kohm` < 500 | 50 | 4 s | DC insulation resistance low |
| HEARTBEAT_STALE | bms01 | major | stale | `heartbeat` frozen |  | 4 s | Device heartbeat frozen (stale data) |
| CONTAINER_TEMP_HIGH | hvac01 | major | high | `container_temp_c` > 35 | 2 | 30 s | Container temperature high |
| HEARTBEAT_STALE | hvac01 | major | stale | `heartbeat` frozen |  | 4 s | Device heartbeat frozen (stale data) |
| HVAC_FAULT_COMPRESSOR_FAULT | hvac01 | major | bitfield | `fault_word` bit 0 |  | 2 s | HVAC fault: COMPRESSOR_FAULT |
| HVAC_FAULT_FAN_FAULT | hvac01 | major | bitfield | `fault_word` bit 3 |  | 2 s | HVAC fault: FAN_FAULT |
| HVAC_FAULT_HIGH_PRESSURE | hvac01 | major | bitfield | `fault_word` bit 1 |  | 2 s | HVAC fault: HIGH_PRESSURE |
| HVAC_FAULT_LOW_PRESSURE | hvac01 | major | bitfield | `fault_word` bit 2 |  | 2 s | HVAC fault: LOW_PRESSURE |
| HVAC_FAULT_SENSOR_FAULT | hvac01 | major | bitfield | `fault_word` bit 4 |  | 2 s | HVAC fault: SENSOR_FAULT |
| HEARTBEAT_STALE | pcs01 | major | stale | `heartbeat` frozen |  | 4 s | Device heartbeat frozen (stale data) |
| PCS_FAULT_BMS_COMMS_LOST | pcs01 | major | bitfield | `fault_word` bit 6 |  | 0 s | PCS fault: BMS_COMMS_LOST |
| PCS_FAULT_GRID_FREQUENCY | pcs01 | major | bitfield | `fault_word` bit 3 |  | 0 s | PCS fault: GRID_FREQUENCY |
| PCS_IGBT_TEMP_HIGH | pcs01 | major | high | `igbt_temp_c` > 80 | 5 | 4 s | IGBT temperature high |
| BMS_ALARM_CELL_IMBALANCE | bms01 | minor | bitfield | `alarm_word` bit 4 |  | 0 s | BMS alarm: CELL_IMBALANCE |
| BMS_CELL_IMBALANCE | bms01 | minor | spread | `max_cell_voltage_v` - `min_cell_voltage_v` > 0.06 | 0.01 | 10 s | Cell voltage imbalance |
| BMS_SOC_LOW | bms01 | minor | low | `soc_pct` < 10 | 2 | 4 s | State of charge low |
| CONTAINER_HUMIDITY_HIGH | hvac01 | minor | high | `humidity_pct` > 80 | 5 | 60 s | Container humidity high |
| BMS_SOC_HIGH | bms01 | warning | high | `soc_pct` > 95 | 2 | 4 s | State of charge high |
| POI_EXPORT_LIMIT | meter_poi | warning | high | `p_total_kw` > 1000 | 20 | 5 s | POI export above grid-connection limit |
| POI_IMPORT_LIMIT | meter_poi | warning | low | `p_total_kw` < -1050 | 20 | 5 s | POI import above grid-connection limit |
| GRID_FREQ_HIGH | pcs01 | warning | high | `frequency_hz` > 50.5 | 0.05 | 4 s | Grid frequency high |
| GRID_FREQ_LOW | pcs01 | warning | low | `frequency_hz` < 49.5 | 0.05 | 4 s | Grid frequency low |
| PCS_WARNING_HIGH_TEMPERATURE | pcs01 | warning | bitfield | `warning_word` bit 1 |  | 2 s | PCS warning: HIGH_TEMPERATURE |
| PCS_WARNING_POWER_DERATED | pcs01 | warning | bitfield | `warning_word` bit 0 |  | 2 s | PCS warning: POWER_DERATED |
| PCS_WARNING_SETPOINT_CLAMPED | pcs01 | warning | bitfield | `warning_word` bit 2 |  | 2 s | PCS warning: SETPOINT_CLAMPED |
