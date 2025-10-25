# Gpuck

A pretty basic, yet real-time Nvidia GPU monitor using GTK3.

## Features

* Graphs GPU metrics:
  - Temperature
  - Memory usage (%)
  - GPU utilization (%)
  - Power (W)
  - Fan speed (%)

## Requirements

* Python 3
* PyGObject (`python3-gi`)
* Cairo (`python3-cairo`)
* NVIDIA GPU
* Either `pynvml` Python package or `nvidia-smi` CLI

## Installation

```bash
sudo apt install python3-gi python3-cairo
pip install pynvml  # optional but recommended
```

## Usage

```bash
python3 gpuck.py
```

## Notes

* Supports Linux only.
* Uses NVML for accurate metrics if available; falls back to `nvidia-smi`.

## License

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
