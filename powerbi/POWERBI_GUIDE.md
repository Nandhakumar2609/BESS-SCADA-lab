# Building the BESS dashboard in Power BI (about 20 minutes)

Files in this folder:

| File | What it is |
|---|---|
| `BESS_PowerBI_Data.xlsx` | 7 days of 1-minute site data, alarm occurrences, daily KPIs, devices, dates, register map |
| `bess-theme.json` | Report theme: grey HMI background, colour reserved for state and alarms (ISA-101 style) |
| `measures.dax` | All DAX measures below, ready to paste |

The data comes from the lab's own simulator model and alarm engine (`tools/export_powerbi.py`),
decoded from the Modbus register images, so it is consistent with the rest of the project.
Regenerate with other dates or length: `python tools/export_powerbi.py --days 14`.

## 1. Load the data

1. Power BI Desktop -> **Home -> Get data -> Excel workbook** -> `BESS_PowerBI_Data.xlsx`.
2. In the Navigator tick the **tables** (blue icon, names starting with `tbl`): `tblTelemetry`,
   `tblAlarms`, `tblDailyKPI`, `tblDevices`, `tblDates`, `tblRegisterMap` -> **Load**.
3. **View -> Themes -> Browse for themes** -> `bess-theme.json`.

## 2. Model (Model view)

1. Relationships (drag `Date` onto `Date`), all **many-to-one, single direction** from the date table:
   - `tblDates[Date]` 1 -> * `tblTelemetry[Date]`
   - `tblDates[Date]` 1 -> * `tblAlarms[Date]`
   - `tblDates[Date]` 1 -> * `tblDailyKPI[Date]`
   - `tblDevices[Device]` 1 -> * `tblAlarms[Device]`
2. Select `tblDates` -> **Table tools -> Mark as date table** -> column `Date`.
3. Sort `tblDates[Day]` by `tblDates[Date]` (Column tools -> Sort by column).
4. Optional: hide the `Date` columns on the fact tables so everyone slices with `tblDates`.

## 3. Measures

Create a measure table (**Home -> Enter data**, name it `_Measures`, load) and paste each measure
from `measures.dax` with **New measure**. Set the formats as noted in the comments.

## 4. Report page "Site overview" (16:9)

| Area | Visual | Fields |
|---|---|---|
| Top row | 5 **Cards** | `SoC Latest %`, `Availability %`, `Energy Discharged MWh`, `Equivalent Cycles`, `Round-trip Efficiency %` |
| Top right | **Slicer** (tile / between) | `tblDates[Date]` |
| Middle left (wide) | **Line chart** | X: `tblTelemetry[Timestamp]`; Y: `PCS_Power_kW`, `POI_Power_kW` (Average). Title "Power flow (kW): + discharge / export" |
| Middle right | **Line chart** | X: `tblTelemetry[Timestamp]`; Y: `SoC_pct` (Average); constant lines at 12 and 92 (Analytics pane) |
| Bottom left | **Clustered column** | X: `tblDates[Day]`; Y: `Energy Charged MWh`, `Energy Discharged MWh` |
| Bottom middle | **Line and clustered column** | X: `tblDates[Day]`; column: `Alarm Count`; line: `Availability %` |
| Bottom right | **Table** | `tblAlarms`: `Raised`, `Device`, `Alarm_ID`, `Severity`, `Duration_min`; conditional formatting on `Severity` (rules: critical red, major orange, minor yellow, warning blue) |

Tips: on the time-series visuals turn off "Concatenate labels" and set the X axis to **Continuous**.
Power BI samples very long series; filter to one or two days with the slicer for full detail.

## 5. Page "Battery & thermal"

- Line chart: `Cell_Vmax_V`, `Cell_Vmin_V` (Average) over `Timestamp` and a card `Max Cell Spread mV`.
- Line chart: `Cell_Tmax_C`, `Container_Temp_C`, `IGBT_Temp_C`, `Ambient_Temp_C` over `Timestamp`.
- Stacked column: `Auxiliary Energy kWh` by `tblDates[Day]`.
- Donut: `Minutes in State` by `tblTelemetry[PCS_State]`.

## 6. Page "Alarms & assets"

- Bar chart "Bad actors": `Alarm Count` by `tblAlarms[Alarm_ID]`, Top N = 10.
- Matrix: rows `Severity`, columns `tblDates[Day]`, values `Alarm Count`.
- Cards: `MTTR min`, `Fault Minutes`.
- Table: `tblDevices` (device, IP, unit ID) and `tblRegisterMap` (filtered by profile slicer) - shows
  the engineering behind the dashboard.

## 7. Share it with the recruiter

- **Without a Power BI licence:** File -> **Export -> PDF** (all pages) and send the PDF, or take
  screenshots of each page.
- **With a Power BI account:** File -> **Publish** to your workspace, then **Share** with the recruiter's
  e-mail (they need access to Power BI), or "Publish to web" for a public link (only for non-sensitive
  data - this data set is simulated, so that is acceptable).
- Save the `.pbix` into this folder and commit it so the project shows both Grafana and Power BI.

## What to say about it

"Grafana is the live operator HMI on top of the InfluxDB historian; Power BI is the management
reporting layer on daily/weekly aggregates - availability, throughput, cycles, efficiency and alarm
statistics. In production Power BI would read the historian through a scheduled export or a SQL
endpoint in the DMZ, never connect into the OT zones."
