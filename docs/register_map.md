# Protocol mapping table (register map)

_Generated from `config/register_map.csv` by `tools/gen_docs.py` - edit the CSV, not this file._

Conventions:

- **Address** is the 0-based protocol address on the wire; **Ref** is the classic Modicon reference (30001 + address for input registers / FC04, 40001 + address for holding registers / FC03, FC06, FC16).
- **Byte order**: `AB`/`ABCD` big-endian, `CDAB` word-swapped, `BADC` byte-swapped, `DCBA` little-endian.
- **Engineering value = raw x scale.** Signed power: + discharge / export, - charge / import.

## Device instances

| Device | Profile | IP:port | Unit ID |
|---|---|---|---|
| pcs01 | pcs | 10.10.10.11:502 | 1 |
| bms01 | bms | 10.10.10.12:502 | 1 |
| hvac01 | hvac | 10.10.10.13:502 | 1 |
| meter_poi | meter | 10.10.10.14:502 | 1 |
| meter_aux | meter | 10.10.10.14:502 | 2 |

## PCS - power conversion system

**Input registers** (FC04) - polled in 1 block read(s): 0..21

| Ref | Addr | Name | Type | Order | Scale | Unit | Access | Description | Values |
|---|---|---|---|---|---|---|---|---|---|
| 30001 | 0 | `heartbeat` | uint16 | AB | 1 |  | R | Increments every second (watchdog) |  |
| 30002 | 1 | `state` | uint16 | AB | 1 |  | R | PCS operating state | 0=STOPPED; 1=STANDBY; 2=CHARGING; 3=DISCHARGING; 4=FAULT |
| 30003 | 2 | `fault_word` | uint16 | AB | 1 |  | R | Active fault bitfield | bit0=IGBT_OVERTEMP; bit1=GRID_OVERVOLTAGE; bit2=GRID_UNDERVOLTAGE; bit3=GRID_FREQUENCY; bit4=DC_OVERVOLTAGE; bit5=INSULATION_FAULT; bit6=BMS_COMMS_LOST; bit7=EMERGENCY_STOP |
| 30004 | 3 | `warning_word` | uint16 | AB | 1 |  | R | Active warning bitfield | bit0=POWER_DERATED; bit1=HIGH_TEMPERATURE; bit2=SETPOINT_CLAMPED |
| 30005 | 4-5 | `active_power_kw` | float32 | ABCD | 1 | kW | R | AC active power (+ discharge / - charge) |  |
| 30007 | 6-7 | `reactive_power_kvar` | float32 | ABCD | 1 | kvar | R | AC reactive power |  |
| 30009 | 8-9 | `ac_voltage_v` | float32 | ABCD | 1 | V | R | AC line-to-line voltage (LV side) |  |
| 30011 | 10-11 | `ac_current_a` | float32 | ABCD | 1 | A | R | AC phase current |  |
| 30013 | 12 | `frequency_hz` | uint16 | AB | 0.01 | Hz | R | Grid frequency |  |
| 30014 | 13 | `dc_voltage_v` | uint16 | AB | 0.1 | V | R | DC link voltage |  |
| 30015 | 14 | `dc_current_a` | int16 | AB | 0.1 | A | R | DC current (+ discharge) |  |
| 30016 | 15 | `igbt_temp_c` | int16 | AB | 0.1 | degC | R | IGBT module temperature |  |
| 30017 | 16 | `available_charge_kw` | uint16 | AB | 1 | kW | R | Charge power currently available |  |
| 30018 | 17 | `available_discharge_kw` | uint16 | AB | 1 | kW | R | Discharge power currently available |  |
| 30019 | 18-19 | `energy_charged_kwh` | uint32 | ABCD | 1 | kWh | R | Lifetime AC energy charged |  |
| 30021 | 20-21 | `energy_discharged_kwh` | uint32 | ABCD | 1 | kWh | R | Lifetime AC energy discharged |  |
**Holding registers** (FC03 / FC06 / FC16) - polled in 1 block read(s): 0..7

| Ref | Addr | Name | Type | Order | Scale | Unit | Access | Description | Values |
|---|---|---|---|---|---|---|---|---|---|
| 40001 | 0 | `run_command` | uint16 | AB | 1 |  | RW | 0=stop 1=run | 0=STOP; 1=RUN |
| 40002 | 1-2 | `p_setpoint_kw` | int32 | ABCD | 0.1 | kW | RW | Active power setpoint (+ discharge / - charge) |  |
| 40004 | 3-4 | `q_setpoint_kvar` | int32 | ABCD | 0.1 | kvar | RW | Reactive power setpoint |  |
| 40006 | 5 | `fault_reset` | uint16 | AB | 1 |  | RW | Write 1 to reset latched faults |  |
| 40007 | 6 | `control_mode` | uint16 | AB | 1 |  | RW | 0=local 1=remote (SCADA) | 0=LOCAL; 1=REMOTE |
| 40008 | 7 | `test_fault_inject` | uint16 | AB | 1 |  | RW | FAT only: bits 0-7 OR-ed into fault_word; bit 14 freezes heartbeat |  |

## BMS - battery management system

**Input registers** (FC04) - polled in 1 block read(s): 0..17

| Ref | Addr | Name | Type | Order | Scale | Unit | Access | Description | Values |
|---|---|---|---|---|---|---|---|---|---|
| 30001 | 0 | `heartbeat` | uint16 | AB | 1 |  | R | Increments every second (watchdog) |  |
| 30002 | 1 | `status` | uint16 | AB | 1 |  | R | BMS status | 0=INIT; 1=READY; 2=CHARGING; 3=DISCHARGING; 4=FAULT |
| 30003 | 2 | `alarm_word` | uint16 | AB | 1 |  | R | Active alarm bitfield | bit0=CELL_OVERVOLTAGE; bit1=CELL_UNDERVOLTAGE; bit2=CELL_OVERTEMP; bit3=CELL_UNDERTEMP; bit4=CELL_IMBALANCE; bit5=INSULATION_LOW; bit6=CONTACTOR_FAULT; bit7=FIRE_DETECTION |
| 30004 | 3 | `soc_pct` | uint16 | AB | 0.1 | % | R | State of charge |  |
| 30005 | 4 | `soh_pct` | uint16 | AB | 0.1 | % | R | State of health |  |
| 30006 | 5-6 | `pack_voltage_v` | uint32 | CDAB | 0.01 | V | R | DC pack voltage |  |
| 30008 | 7-8 | `pack_current_a` | int32 | CDAB | 0.01 | A | R | DC pack current (+ discharge) |  |
| 30010 | 9 | `max_cell_voltage_v` | uint16 | AB | 0.001 | V | R | Highest cell voltage |  |
| 30011 | 10 | `min_cell_voltage_v` | uint16 | AB | 0.001 | V | R | Lowest cell voltage |  |
| 30012 | 11 | `max_cell_temp_c` | int16 | AB | 0.1 | degC | R | Highest cell temperature |  |
| 30013 | 12 | `min_cell_temp_c` | int16 | AB | 0.1 | degC | R | Lowest cell temperature |  |
| 30014 | 13 | `max_charge_power_kw` | uint16 | AB | 1 | kW | R | BMS charge power limit |  |
| 30015 | 14 | `max_discharge_power_kw` | uint16 | AB | 1 | kW | R | BMS discharge power limit |  |
| 30016 | 15 | `contactor_closed` | uint16 | AB | 1 |  | R | Main DC contactor state | 0=OPEN; 1=CLOSED |
| 30017 | 16 | `cycle_count` | uint16 | AB | 1 |  | R | Equivalent full cycles |  |
| 30018 | 17 | `insulation_kohm` | uint16 | AB | 1 | kOhm | R | DC insulation resistance |  |
**Holding registers** (FC03 / FC06 / FC16) - polled in 1 block read(s): 0..1

| Ref | Addr | Name | Type | Order | Scale | Unit | Access | Description | Values |
|---|---|---|---|---|---|---|---|---|---|
| 40001 | 0 | `contactor_command` | uint16 | AB | 1 |  | RW | 0=open 1=close | 0=OPEN; 1=CLOSE |
| 40002 | 1 | `test_fault_inject` | uint16 | AB | 1 |  | RW | FAT only: bits 0-7 OR-ed into alarm_word; bit 14 freezes heartbeat |  |

## HVAC - container climate

**Input registers** (FC04) - polled in 1 block read(s): 0..9

| Ref | Addr | Name | Type | Order | Scale | Unit | Access | Description | Values |
|---|---|---|---|---|---|---|---|---|---|
| 30001 | 0 | `heartbeat` | uint16 | AB | 1 |  | R | Increments every second (watchdog) |  |
| 30002 | 1 | `mode` | uint16 | AB | 1 |  | R | HVAC operating mode | 0=OFF; 1=COOLING; 2=HEATING; 3=FAN_ONLY |
| 30003 | 2 | `fault_word` | uint16 | AB | 1 |  | R | Active fault bitfield | bit0=COMPRESSOR_FAULT; bit1=HIGH_PRESSURE; bit2=LOW_PRESSURE; bit3=FAN_FAULT; bit4=SENSOR_FAULT |
| 30004 | 3 | `container_temp_c` | int16 | AB | 0.1 | degC | R | Battery container air temperature |  |
| 30005 | 4 | `humidity_pct` | uint16 | AB | 0.1 | % | R | Container relative humidity |  |
| 30006 | 5 | `ambient_temp_c` | int16 | AB | 0.1 | degC | R | Outdoor ambient temperature |  |
| 30007 | 6 | `supply_air_temp_c` | int16 | AB | 0.1 | degC | R | Supply air temperature |  |
| 30008 | 7 | `compressor_on` | uint16 | AB | 1 |  | R | Compressor running | 0=OFF; 1=ON |
| 30009 | 8-9 | `power_kw` | float32 | DCBA | 1 | kW | R | HVAC electrical consumption (little-endian device) |  |
**Holding registers** (FC03 / FC06 / FC16) - polled in 1 block read(s): 0..3

| Ref | Addr | Name | Type | Order | Scale | Unit | Access | Description | Values |
|---|---|---|---|---|---|---|---|---|---|
| 40001 | 0 | `enable` | uint16 | AB | 1 |  | RW | 0=disabled 1=enabled | 0=DISABLED; 1=ENABLED |
| 40002 | 1 | `cooling_setpoint_c` | int16 | AB | 0.1 | degC | RW | Cooling setpoint |  |
| 40003 | 2 | `heating_setpoint_c` | int16 | AB | 0.1 | degC | RW | Heating setpoint |  |
| 40004 | 3 | `test_fault_inject` | uint16 | AB | 1 |  | RW | FAT only: bits 0-7 OR-ed into fault_word; bit 14 freezes heartbeat |  |

## Power meters (POI and auxiliary)

**Input registers** (FC04) - polled in 1 block read(s): 0..19

| Ref | Addr | Name | Type | Order | Scale | Unit | Access | Description | Values |
|---|---|---|---|---|---|---|---|---|---|
| 30001 | 0-1 | `p_total_kw` | float32 | CDAB | 1 | kW | R | Total active power (POI: + export / AUX: + consumption) |  |
| 30003 | 2-3 | `q_total_kvar` | float32 | CDAB | 1 | kvar | R | Total reactive power |  |
| 30005 | 4-5 | `s_total_kva` | float32 | CDAB | 1 | kVA | R | Total apparent power |  |
| 30007 | 6-7 | `power_factor` | float32 | CDAB | 1 |  | R | Power factor |  |
| 30009 | 8-9 | `voltage_ll_v` | float32 | CDAB | 1 | V | R | Average line-to-line voltage |  |
| 30011 | 10-11 | `current_avg_a` | float32 | CDAB | 1 | A | R | Average phase current |  |
| 30013 | 12-13 | `frequency_hz` | float32 | CDAB | 1 | Hz | R | Frequency |  |
| 30015 | 14-15 | `energy_import_kwh` | uint32 | CDAB | 0.1 | kWh | R | Imported energy counter |  |
| 30017 | 16-17 | `energy_export_kwh` | uint32 | CDAB | 0.1 | kWh | R | Exported energy counter |  |
| 30019 | 18-19 | `energy_check` | float32 | BADC | 1 | kWh | R | Byte-swapped copy of net energy (codec test point) |  |
