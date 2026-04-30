# nvidia

| In Use | Still Fixing |
|--------|--------------|
| ✅     | ❌           |

Real-time GTK3 GPU and CPU monitor with smooth scrolling graphs.

## gpuck.py

Displays live graphs for GPU temperature, memory, utilization, power draw, and fan speed, plus CPU temperature and utilization. Uses NVML (pynvml) when available, falls back to nvidia-smi. Supports EMA smoothing, hover-to-inspect stats, dots mode, and metric filtering via CLI flags.

See [gpuck.md](gpuck.md) for full usage and CLI options.

### Requirements

- Python 3, PyGObject, Cairo
- NVIDIA GPU with pynvml or nvidia-smi
- psutil (optional, for CPU metrics)
