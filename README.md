# TempHumidityPlotter

Generate comparison plots for temperature, humidity, and enthalpy from input files.

The script supports:
- cleaned `.csv` files with columns `datetime`, `temperature_C`, `humidity_RH`
- raw device-exported `.TXT` reports
- outdoor trend `.csv` reports containing paired temperature/humidity points

It reads indoor files plus an optional outdoor file, filters by optional time range, removes invalid rows such as `FF`, and outputs:
- one or more comparison charts in `output/`
- a Markdown diagnostics log in `output/temp_humidity_diagnostics.md`

## Requirements

- Python 3.11+
- `matplotlib`
- `pyyaml`
- `python-dateutil`

Install example:

```powershell
pip install matplotlib pyyaml python-dateutil
```

## Configuration

Main config is in [config.yaml](./config.yaml). Runtime values can be overridden in `common.env`.

Example `common.env`:

```env
LOG_LEVEL=INFO
INPUT_FILE=D:\CloudStation\国会二期\02 备忘录\2026-04-13_主体抖音新风竖井数据
OUTDOOR_TEMP_HUMIDITY_FILE=D:\CloudStation\国会二期\02 备忘录\outdoor_temp_humidity.csv
OUTPUT_PATH=./output
INPUT_FILE_TYPE=auto
RANGE_START=2020-04-08 15:55:00
RANGE_END=2020-04-13 15:20:00
ATMOSPHERIC_PRESSURE_KPA=101.325
MAX_SPAN_DAYS=2
HIGHLIGHT_START_TIME=08:00
HIGHLIGHT_END_TIME=18:00
PLOT_FORMAT=png
```

Key options:

| Key | Meaning |
|:---:|:---:|
| `INPUT_FILE` | Input directory in `batch` mode |
| `INPUT_FILE_TYPE` | `auto`, `csv`, or `txt` |
| `INPUT_MODE` | `batch` or `single` |
| `INPUT_TARGET_FILE` | Two explicit files in `single` mode |
| `OUTDOOR_TEMP_HUMIDITY_FILE` | Optional outdoor temperature/humidity source file path |
| `RANGE_START` | Optional start time |
| `RANGE_END` | Optional end time |
| `ATMOSPHERIC_PRESSURE_KPA` | Atmospheric pressure in `kPa`, used for enthalpy calculation |
| `MAX_SPAN_DAYS` | Max natural days per image page |
| `HIGHLIGHT_START_TIME` | Daily highlight start time |
| `HIGHLIGHT_END_TIME` | Daily highlight end time |
| `PLOT_FORMAT` | Output format such as `png` or `pdf` |
| `OUTPUT_PATH` | Output directory |

## Usage

Run:

```powershell
python -u temp_humidity_plotter.py
```

## Notes

- `batch` mode requires exactly 2 indoor input files.
- `OUTDOOR_TEMP_HUMIDITY_FILE` is optional and adds a third comparison series when present.
- TXT parsing starts from the device report header row and skips invalid rows.
- Rows with invalid values such as temperature `FF` are removed and will not be drawn.
- If data exceeds `MAX_SPAN_DAYS`, the script paginates by natural day boundaries, so one day will not appear in two pages.
- `HIGHLIGHT_START_TIME` and `HIGHLIGHT_END_TIME` add a light blue daily background band behind the curves.
- Each run generates temperature, humidity, and enthalpy comparison charts.
- When `PLOT_FORMAT=png`, each page is kept as an individual image.
- When `PLOT_FORMAT=pdf`, pages are merged into one PDF per metric and temporary `*_p01.pdf`, `*_p02.pdf` files are removed.
- Warnings and errors are written to the Markdown diagnostics report.
