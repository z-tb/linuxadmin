# Gpuck

Real-time GPU and CPU monitor using GTK3 with smooth scrolling graphs.

## Features

- Graphs GPU metrics: temperature, memory usage (%), utilization (%), power (W), GPU fan speed (%)
- Graphs CPU metrics: temperature, utilization (%)
- EMA (exponential moving average) smoothing to reduce noise, especially on CPU utilization
- Sliding 5-minute window with automatic buffer sizing
- Hover any graph to see current, high, low, and average values in the status bar
- View menu to toggle individual metrics on/off
- Dots mode for plotting raw data points instead of lines
- Embedded SVG icon
- Gridlines with numeric labels

## Requirements

- Python 3
- PyGObject (`python3-gi`)
- Cairo (`python3-cairo`)
- NVIDIA GPU with either `pynvml` Python package or `nvidia-smi` CLI
- `psutil` for CPU metrics (optional but recommended)

## Installation

```bash
sudo apt install python3-gi python3-cairo
pip install pynvml psutil
```

## Usage

```bash
python3 gpuck.py                          # all metrics as lines
python3 gpuck.py --dots cpu_utilization_% # CPU util as dots
python3 gpuck.py --dots                   # all metrics as dots
python3 gpuck.py --stime 0.5             # sample every 0.5s
python3 gpuck.py --metrics gtemp gutil    # show only GPU temp and utilization
```

### CLI Options

| Flag | Description |
|------|-------------|
| `--dots [METRIC ...]` | Plot specified metrics as dots. No args = all dots. |
| `--stime SECONDS` | Sample interval (default: 0.2s) |
| `--buffer-size N` | History buffer size (default: auto-sized to fill window) |
| `--metrics METRIC [...]` | Show only specified metrics |

### Metric Shorthands (for --metrics)

| Shorthand | Metric |
|-----------|--------|
| `gtemp` | GPU temperature |
| `gmem` | GPU memory % |
| `gutil` | GPU utilization % |
| `gwatt` | GPU power (watts) |
| `gfan` | GPU fan speed % |
| `ctemp` | CPU temperature |
| `cutil` | CPU utilization % |

## Notes

- Linux only
- Uses NVML for GPU metrics if available, falls back to `nvidia-smi`
- Uses `psutil` for CPU metrics; CPU graphs are hidden if `psutil` is not installed
- GPU fan speed reports the GPU cooler fan, not system/chassis fans
- CPU utilization is system-wide average across all cores

## License

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
