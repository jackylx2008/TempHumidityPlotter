# TempHumidityPlotter

Generate a temperature comparison plot from two input files.

The script supports:
- cleaned `.csv` files with columns `datetime`, `temperature_C`, `humidity_RH`
- raw device-exported `.TXT` reports

It reads two files, filters by optional time range, removes invalid temperature rows such as `FF`, and outputs:
- one or more comparison images in `output/`
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
INPUT_FILE=D:\CloudStation\国会二期\02 备忘录\2026-04-013_主体抖音新风竖井数据
OUTPUT_PATH=./output
INPUT_FILE_TYPE=auto
RANGE_START=2020-04-08 15:55:00
RANGE_END=2020-04-13 15:20:00
MAX_SPAN_DAYS=2
HIGHLIGHT_START_TIME=08:00
HIGHLIGHT_END_TIME=18:00
```

Key options:

| Key | Meaning |
|:---:|:---:|
| `INPUT_FILE` | Input directory in `batch` mode |
| `INPUT_FILE_TYPE` | `auto`, `csv`, or `txt` |
| `INPUT_MODE` | `batch` or `single` |
| `INPUT_TARGET_FILE` | Two explicit files in `single` mode |
| `RANGE_START` | Optional start time |
| `RANGE_END` | Optional end time |
| `MAX_SPAN_DAYS` | Max natural days per image page |
| `HIGHLIGHT_START_TIME` | Daily highlight start time |
| `HIGHLIGHT_END_TIME` | Daily highlight end time |
| `OUTPUT_PATH` | Output directory |

## Usage

Run:

```powershell
python -u temp_humidity_plotter.py
```

## Notes

- `batch` mode requires exactly 2 input files.
- TXT parsing starts from the device report header row and skips invalid rows.
- Rows with temperature value `FF` are removed and will not be drawn.
- If data exceeds `MAX_SPAN_DAYS`, the script splits output into multiple PNG pages.
- Page splitting follows natural day boundaries, so one day will not appear in two images.
- `HIGHLIGHT_START_TIME` and `HIGHLIGHT_END_TIME` add a light blue daily background band behind the curves.
- Warnings and errors are written to the Markdown diagnostics report.
