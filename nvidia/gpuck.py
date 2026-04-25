#!/usr/bin/env python3
"""
gpuck.py
Real-time GTK GPU monitor with smooth scrolling graphs.

Features:
- Embedded SVG icon
- Gridlines for metric visualization
- Centered legend text in dark cyan
- Bottom status summary for current GPU stats
"""

# ---------------------------
# GTK Window constants
# ---------------------------
WINDOW_SECONDS = 300  # Show last 5 minutes of data
SAMPLE_INTERVAL = 0.2  # seconds between GPU metric reads
RENDER_FPS = 30  # frames per second for drawing

# ---------------------------
# GTK imports
# ---------------------------
import gi
gi.require_version("Gtk", "3.0")  # Force PyGObject to use GTK 3
from gi.repository import Gtk, GdkPixbuf, GLib, Gdk  # Import GTK classes for GUI
import cairo  # For drawing the graphs
import time, math, collections, subprocess, threading  # Standard utilities

# ---------------------------
# NVIDIA GPU monitoring (pynvml)
# ---------------------------
try:
    import pynvml  # NVIDIA Management Library for GPU stats
    pynvml.nvmlInit()  # Initialize NVML
    PYNVML = True
except Exception:
    PYNVML = False  # Fallback if pynvml is not installed

# ---------------------------
# CPU monitoring (psutil)
# ---------------------------
try:
    import psutil  # For CPU and system metrics
    PSUTIL = True
except Exception:
    PSUTIL = False  # Fallback if psutil is not installed

# ---------------------------
# Embedded SVG icon (stored as bytes)
# ---------------------------
ICON_SVG = b"""
<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <rect x="16" y="16" width="96" height="96" rx="8" ry="8"
        fill="#1a1a1a" stroke="#00ff6a" stroke-width="4"/>
  <path d="M32 64 L48 64 L56 40 L72 88 L80 64 L96 64"
        fill="none" stroke="#00ff6a" stroke-width="5"
        stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="8" y="32" width="8" height="16" fill="#00ff6a"/>
  <rect x="8" y="80" width="8" height="16" fill="#00ff6a"/>
  <rect x="112" y="32" width="8" height="16" fill="#00ff6a"/>
  <rect x="112" y="80" width="8" height="16" fill="#00ff6a"/>
</svg>
"""

def svg_to_pixbuf(svg_bytes, width=None, height=None):
    """Convert SVG bytes to GdkPixbuf."""
    loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
    if width and height:
        loader.set_size(width, height)
    loader.write(svg_bytes)
    loader.close()
    return loader.get_pixbuf()

def get_embedded_icon_pixbuf():
    """Return a GdkPixbuf to use as GTK window icon."""
    return svg_to_pixbuf(ICON_SVG)

# ---------------------------
# Metric buffer: stores historical values
# ---------------------------
class MetricBuffer:
    """
    Stores time-series metric data with optional maximum length.
    Used for smooth scrolling graphs in the GTK window.
    Supports exponential moving average (EMA) smoothing.
    """
    def __init__(self, maxlen=600, ema_alpha=1.0):
        self.samples = collections.deque(maxlen=maxlen)  # Efficient FIFO buffer
        self.ema_alpha = ema_alpha  # 1.0 = no smoothing, lower = smoother
        self._ema_value = None

    def append(self, t, v):
        """
        Add a new sample with optional EMA smoothing.
        If time is non-monotonic, increment slightly to prevent issues.
        """
        if self.samples and t <= self.samples[-1][0]:
            t = self.samples[-1][0] + 1e-6
        v = float(v)
        if not math.isnan(v):
            if self._ema_value is None:
                self._ema_value = v
            else:
                self._ema_value += self.ema_alpha * (v - self._ema_value)
            v = self._ema_value
        self.samples.append((t, v))

    def prune(self, cutoff):
        """Remove old samples older than cutoff time to limit memory usage."""
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

    def get_value_at(self, t):
        """
        Linearly interpolate value at time t.
        Ensures smooth plotting even if samples are discrete.
        """
        if not self.samples:
            return float("nan")
        if t <= self.samples[0][0]:
            return self.samples[0][1]
        if t >= self.samples[-1][0]:
            return self.samples[-1][1]

        # Binary search for surrounding samples
        lo, hi = 0, len(self.samples) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.samples[mid][0] <= t:
                lo = mid + 1
            else:
                hi = mid - 1

        t0, v0 = self.samples[hi]
        t1, v1 = self.samples[hi + 1]
        frac = (t - t0) / (t1 - t0)
        return v0 + frac * (v1 - v0)

# ---------------------------
# GPUReader: reads NVIDIA GPU metrics
# ---------------------------
class GPUReader:
    """
    Reads GPU metrics using either pynvml (preferred) or nvidia-smi as fallback.
    Thread-safe to avoid conflicts with GTK GUI.
    """
    def __init__(self):
        self.lock = threading.Lock()  # Ensure single read at a time
        if PYNVML:
            try:
                self.count = pynvml.nvmlDeviceGetCount()  # Number of GPUs
            except Exception:
                self.count = 0
        else:
            self.count = self._count_via_nvidia_smi()

    def _count_via_nvidia_smi(self):
        """Fallback GPU count using nvidia-smi CLI."""
        try:
            out = subprocess.check_output(["nvidia-smi", "-L"], encoding="utf-8")
            return len([l for l in out.splitlines() if l.strip()])
        except Exception:
            return 0

    def read(self):
        """Return current GPU metrics as a dictionary."""
        with self.lock:
            if PYNVML and self.count > 0:
                return self._read_pynvml()
            return self._read_nvidia_smi()

    def _read_pynvml(self):
        """Read metrics using NVIDIA NVML API."""
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        mem_pct = (mem.used / mem.total) * 100 if mem.total else 0
        util = pynvml.nvmlDeviceGetUtilizationRates(h).gpu
        power = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0
        fan = pynvml.nvmlDeviceGetFanSpeed(h)
        return {
            "gpu_temp": temp,
            "Gpu_Memory_%": mem_pct,
            "gpu_utilization_%": util,
            "gpu_watts": power,
            "gpu_fan_%": fan,
        }

    def _read_nvidia_smi(self):
        """Fallback read using nvidia-smi CLI if NVML unavailable."""
        try:
            query = [
                "nvidia-smi",
                "--query-gpu=temperature.gpu,utilization.gpu,power.draw,fan.speed,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ]
            out = subprocess.check_output(query, encoding="utf-8")
            vals = [v.strip() for v in out.split(",")]
            t, util, pwr, fan, used, total = map(float, vals)
            mem_pct = (used / total) * 100 if total else 0
            return {
                "gpu_temp": t,
                "Gpu_Memory_%": mem_pct,
                "gpu_utilization_%": util,
                "gpu_watts": pwr,
                "gpu_fan_%": fan,
            }
        except Exception:
            return {}

# ---------------------------
# CPU monitoring
# ---------------------------
class CPUReader:
    """
    Reads CPU metrics using psutil.
    Thread-safe to avoid conflicts with GTK GUI.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.available = PSUTIL

    def read(self):
        """Return current CPU metrics as a dictionary."""
        with self.lock:
            if not self.available:
                return {}
            try:
                cpu_percent = psutil.cpu_percent(interval=0)
                cpu_temp = None
                cpu_watts = None

                # Try to get CPU temperature if available
                try:
                    temps = psutil.sensors_temperatures()
                    if 'coretemp' in temps:
                        cpu_temp = temps['coretemp'][0].current
                    elif 'acpitz' in temps:
                        cpu_temp = temps['acpitz'][0].current
                    else:
                        # Use first available temperature sensor
                        for sensor_name, readings in temps.items():
                            if readings:
                                cpu_temp = readings[0].current
                                break
                except Exception:
                    cpu_temp = None

                result = {"cpu_utilization_%": cpu_percent}
                if cpu_temp is not None:
                    result["cpu_temp"] = cpu_temp
                return result
            except Exception:
                return {}

# ---------------------------
# GPUWindow: GTK main window
# ---------------------------
class GPUWindow(Gtk.Window):
    """
    Main GTK application window.
    Draws live graphs for GPU metrics, shows bottom status summary.
    Provides File, View, Help menus.
    """
    def __init__(self, dots_mode=None, sample_interval=SAMPLE_INTERVAL, buffer_size=600, metric_visibility=None):
        super().__init__(title="gpuck")
        self.set_icon(get_embedded_icon_pixbuf())  # Set window icon
        self.set_default_size(1000, 600)  # Initial size

        self.dots_mode = set(dots_mode) if dots_mode else set()  # Metrics to plot as dots only
        self.sample_interval = sample_interval  # Sampling interval in seconds
        self.buffer_size = buffer_size  # Number of samples to keep

        self.gpu_reader = GPUReader()  # GPU reader instance
        self.cpu_reader = CPUReader()  # CPU reader instance

        # EMA alpha per metric: lower = smoother. CPU util is noisy, needs more smoothing.
        ema_alphas = {
            "gpu_temp": 0.5,
            "Gpu_Memory_%": 0.5,
            "gpu_utilization_%": 0.3,
            "gpu_watts": 0.5,
            "gpu_fan_%": 0.5,
            "cpu_temp": 0.4,
            "cpu_utilization_%": 0.2,
        }

        self.metrics = {k: MetricBuffer(maxlen=buffer_size, ema_alpha=ema_alphas.get(k, 0.5))
                        for k in ["gpu_temp", "Gpu_Memory_%", "gpu_utilization_%", "gpu_watts", "gpu_fan_%",
                                  "cpu_temp", "cpu_utilization_%"]}

        vbox = Gtk.VBox(spacing=6)
        self.add(vbox)

        # Metric visibility: use provided visibility or default to all visible
        if metric_visibility is not None:
            self.metric_visibility = metric_visibility
        else:
            self.metric_visibility = {k: True for k in self.metrics}

        # -------------------------------
        # Menubar setup
        # -------------------------------
        menubar = Gtk.MenuBar()
        # File menu
        filemenu = Gtk.Menu()
        file_item = Gtk.MenuItem(label="File")
        file_item.set_submenu(filemenu)
        exit_item = Gtk.MenuItem(label="Exit")
        exit_item.connect("activate", lambda w: Gtk.main_quit())
        filemenu.append(exit_item)
        menubar.append(file_item)

        # View menu (toggle metrics)
        viewmenu = Gtk.Menu()
        view_item = Gtk.MenuItem(label="View")
        view_item.set_submenu(viewmenu)
        self.view_menu_items = {}
        for k in self.metrics:
            check = Gtk.CheckMenuItem(label=k.replace("_", " ").capitalize())
            check.set_active(True)
            check.connect("toggled", self.on_toggle_metric, k)
            viewmenu.append(check)
            self.view_menu_items[k] = check
        menubar.append(view_item)

        # Help menu (About dialog)
        helpmenu = Gtk.Menu()
        help_item = Gtk.MenuItem(label="Help")
        help_item.set_submenu(helpmenu)
        about_item = Gtk.MenuItem(label="About")
        about_item.connect("activate", self.show_about)
        helpmenu.append(about_item)
        menubar.append(help_item)

        # Insert menubar at top of vbox
        vbox.pack_start(menubar, False, False, 0)

        # Drawing area for GPU graphs
        self.da = Gtk.DrawingArea()
        self.da.connect("draw", self.on_draw)
        self.da.connect("motion-notify-event", self.on_mouse_move)
        self.da.connect("leave-notify-event", self.on_mouse_leave)
        self.da.set_events(self.da.get_events() |
                          Gdk.EventMask.POINTER_MOTION_MASK |
                          Gdk.EventMask.LEAVE_NOTIFY_MASK)
        vbox.pack_start(self.da, True, True, 0)

        # Status label at bottom with Pango markup support for colors
        self.status = Gtk.Label(label="gpuck v1.0")
        self.status.set_use_markup(True)  # Enable Pango markup for colorization
        self.status.set_xalign(0)
        vbox.pack_end(self.status, False, False, 4)

        # Mouse tracking state
        self.hovered_metric = None  # Currently hovered metric
        self.hover_x = 0
        self.hover_y = 0
        self.graph_areas = {}  # Map metric name to (x0, y0, x1, y1) coordinates

        # Setup periodic GPU sampling and drawing refresh
        GLib.timeout_add(int(self.sample_interval * 1000), self.sample)
        GLib.timeout_add(int(1000 / RENDER_FPS), self.refresh)
        self.show_all()

    def on_toggle_metric(self, widget, key):
        """Update visibility of individual metrics based on the checkbox state."""
        self.metric_visibility[key] = widget.get_active()
        self.da.queue_draw()  # Trigger redraw

    def show_about(self, widget):
        """Show About dialog with version and mascot info."""
        dialog = Gtk.AboutDialog()
        dialog.set_transient_for(self)
        dialog.set_program_name("gpuck")
        dialog.set_version("1.0")
        dialog.set_comments("Gpuck is an Nvidia GPU monitor for Linux.")
        
        # Load and set the SVG logo
        try:
            pixbuf = svg_to_pixbuf(ICON_SVG, 128, 128)
            dialog.set_logo(pixbuf)
        except Exception as e:
            print(f"Failed to load icon: {e}")
        
        dialog.run()
        dialog.destroy()

    def on_mouse_move(self, widget, event):
        """Handle mouse movement over the graph area."""
        self.hover_x = event.x
        self.hover_y = event.y

        # Check which graph is being hovered
        hovered = None
        for metric_name, (x0, y0, x1, y1) in self.graph_areas.items():
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                hovered = metric_name
                break

        if hovered != self.hovered_metric:
            self.hovered_metric = hovered
            self.update_status_for_hover()

        return False

    def on_mouse_leave(self, widget, event):
        """Handle mouse leaving the graph area."""
        self.hovered_metric = None
        self.status.set_markup("gpuck v1.0")
        return False

    def update_status_for_hover(self):
        """Update status bar based on currently hovered metric."""
        if not self.hovered_metric:
            self.status.set_markup("gpuck v1.0")
            return

        metric_name = self.hovered_metric
        samples = self.metrics[metric_name].samples

        if not samples:
            metric_display = metric_name.replace("_", " ").capitalize()
            self.status.set_markup(f"{metric_display}: No data")
            return

        # Extract values from samples
        values = [v for t, v in samples]
        if not values:
            return

        current = values[-1]
        high = max(values)
        low = min(values)
        avg = sum(values) / len(values)

        # Get color for this metric (RGB tuple to hex)
        colors = {
            "gpu_temp": (1, 0.4, 0.3),
            "Gpu_Memory_%": (0.3, 0.7, 1.0),
            "gpu_utilization_%": (0.4, 1.0, 0.4),
            "gpu_watts": (1.0, 0.8, 0.2),
            "gpu_fan_%": (0.8, 0.5, 1.0),
            "cpu_temp": (1.0, 0.6, 0.0),
            "cpu_utilization_%": (0.6, 0.8, 1.0),
        }

        if metric_name in colors:
            r, g, b = colors[metric_name]
            hex_color = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
        else:
            hex_color = "#00ffff"  # Default cyan

        # Format based on metric type
        metric_display = metric_name.replace("_", " ").capitalize()

        if "%" in metric_name:
            status_text = f"<span foreground='{hex_color}'><b>{metric_display}:</b> {current:.0f}% | <b>High:</b> {high:.0f}% | <b>Low:</b> {low:.0f}% | <b>Avg:</b> {avg:.0f}%</span>"
        elif "temp" in metric_name:
            status_text = f"<span foreground='{hex_color}'><b>{metric_display}:</b> {current:.0f}°C | <b>High:</b> {high:.0f}°C | <b>Low:</b> {low:.0f}°C | <b>Avg:</b> {avg:.0f}°C</span>"
        elif "watts" in metric_name:
            status_text = f"<span foreground='{hex_color}'><b>{metric_display}:</b> {current:.1f}W | <b>High:</b> {high:.1f}W | <b>Low:</b> {low:.1f}W | <b>Avg:</b> {avg:.1f}W</span>"
        else:
            status_text = f"<span foreground='{hex_color}'><b>{metric_display}:</b> {current:.1f} | <b>High:</b> {high:.1f} | <b>Low:</b> {low:.1f} | <b>Avg:</b> {avg:.1f}</span>"

        self.status.set_markup(status_text)

    def sample(self):
        """Read GPU and CPU metrics, append to buffers, prune old samples."""
        gpu_data = self.gpu_reader.read()
        cpu_data = self.cpu_reader.read()

        # Merge GPU and CPU data
        data = {}
        data.update(gpu_data)
        data.update(cpu_data)

        t = time.time()
        if not gpu_data:
            self.status.set_markup("<span foreground='#ff6666'><b>No NVIDIA GPU detected.</b></span>")
            return True

        # Append all metrics to their buffers
        for k in self.metrics:
            self.metrics[k].append(t, data.get(k, float("nan")))
            self.metrics[k].prune(t - WINDOW_SECONDS)

        return True

    def refresh(self):
        """Redraw graphs at fixed FPS."""
        self.da.queue_draw()
        return True

    def draw_grid(self, cr, x0, y0, x1, y1, ymin, ymax):
        """Draw horizontal gridlines and numeric labels for metric graphs."""
        cr.set_line_width(1)
        cr.set_source_rgb(0.25, 0.25, 0.25)
        values = [ymin, (ymin + ymax) / 2, ymax]
        for v in values:
            y = y1 - (v - ymin) / (ymax - ymin) * (y1 - y0)
            cr.move_to(x0, y)
            cr.line_to(x1, y)
            cr.stroke()
            # numeric label inside graph
            cr.set_source_rgb(0.25, 0.25, 0.25)
            cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(10)
            text = f"{int(v)}"
            extents = cr.text_extents(text)
            cr.move_to(x0 + 2, min(max(y, y0 + extents.height), y1 - 2))
            cr.show_text(text)
            
    def on_draw(self, widget, cr):
        """Draw all visible metrics as scrolling graphs with legends."""
        alloc = widget.get_allocation()
        w, h = alloc.width, alloc.height
        cr.set_source_rgb(0.08, 0.08, 0.08)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        keys = [k for k in self.metrics if self.metric_visibility[k]]
        if not keys:
            return False

        margin, rows = 8, len(keys)
        row_h = (h - (rows + 1) * margin) / rows
        # Snap render time to sample grid to prevent interpolation jitter
        now = time.time()
        now = math.floor(now / self.sample_interval) * self.sample_interval
        start = now - WINDOW_SECONDS

        colors = {
            "gpu_temp": (1, 0.4, 0.3),
            "Gpu_Memory_%": (0.3, 0.7, 1.0),
            "gpu_utilization_%": (0.4, 1.0, 0.4),
            "gpu_watts": (1.0, 0.8, 0.2),
            "gpu_fan_%": (0.8, 0.5, 1.0),
            "cpu_temp": (1.0, 0.6, 0.0),       # Orange for CPU temp
            "cpu_utilization_%": (0.6, 0.8, 1.0),  # Light blue for CPU util
        }

        # Clear graph areas for hover detection
        self.graph_areas = {}

        for i, k in enumerate(keys):
            y0 = margin + i * (row_h + margin)
            plot_x0, plot_y0 = margin + 40, y0 + 10
            plot_x1, plot_y1 = w - margin - 5, y0 + row_h

            # Store graph area for hover detection
            self.graph_areas[k] = (plot_x0, plot_y0, plot_x1, plot_y1)

            cr.set_source_rgb(0.15, 0.15, 0.15)
            cr.rectangle(plot_x0, plot_y0, plot_x1 - plot_x0, plot_y1 - plot_y0)
            cr.fill()

            # ranges per metric
            if k == "gpu_temp":
                ymin, ymax = 20, 100
            elif k == "cpu_temp":
                ymin, ymax = 20, 100
            elif k == "gpu_watts":
                ymin, ymax = 0, 300
            else:
                ymin, ymax = 0, 100

            self.draw_grid(cr, plot_x0, plot_y0, plot_x1, plot_y1, ymin, ymax)

            cr.set_source_rgb(*colors[k])
            plot_width = plot_x1 - plot_x0

            # Draw either dots or lines depending on dots_mode
            if k in self.dots_mode:
                # Plot only dots at data points
                cr.set_line_width(1.0)
                for t_sample, v_sample in self.metrics[k].samples:
                    if t_sample < start or t_sample > start + WINDOW_SECONDS:
                        continue
                    v = max(ymin, min(ymax, v_sample))
                    x = plot_x0 + ((t_sample - start) / WINDOW_SECONDS) * plot_width
                    y = plot_y1 - (v - ymin) / (ymax - ymin) * (plot_y1 - plot_y0)
                    # Draw a small dot (3x3 pixels)
                    cr.arc(x, y, 1.5, 0, 2 * math.pi)
                    cr.fill()
            else:
                # Draw metric line with per-pixel sampling for smooth curves
                # Sample at every pixel for maximum smoothness without jiggling
                cr.set_line_width(2.0)
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)

                first_point = True
                for px in range(int(plot_x0), int(plot_x1) + 1):
                    # Map pixel to time, keeping fractional precision for smooth interpolation
                    t = start + ((px - plot_x0) / plot_width) * WINDOW_SECONDS
                    v = self.metrics[k].get_value_at(t)

                    if math.isnan(v):
                        first_point = True
                        continue

                    v = max(ymin, min(ymax, v))
                    # Snap Y to nearest half-pixel to prevent anti-aliasing shimmer
                    y = plot_y1 - (v - ymin) / (ymax - ymin) * (plot_y1 - plot_y0)
                    y = round(y * 2) / 2

                    if first_point:
                        cr.move_to(px, y)
                        first_point = False
                    else:
                        cr.line_to(px, y)

                cr.stroke()

            # Draw legend text with current value at top of graph (dark cyan)
            cr.set_source_rgb(0.0, 0.55, 0.55)
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(12)

            # Get the current (most recent) value for this metric
            if self.metrics[k].samples:
                current_value = self.metrics[k].samples[-1][1]
                # Format value with appropriate precision
                if "%" in k:
                    value_str = f"{current_value:.0f}%"
                elif "temp" in k:
                    value_str = f"{current_value:.0f}°C"
                elif "watts" in k:
                    value_str = f"{current_value:.1f}W"
                else:
                    value_str = f"{current_value:.1f}"

                legend = f"{k.replace('_', ' ').capitalize()}: {value_str}"
            else:
                legend = k.replace("_", " ").capitalize()

            extents = cr.text_extents(legend)
            # Place at top-left of graph area with small padding
            cx = plot_x0 + 4
            cy = plot_y0 + extents.height + 2
            cr.move_to(cx, cy)
            cr.show_text(legend)

        return False

# ---------------------------
# Entry point
# ---------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="gpuck - Real-time GTK GPU monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                      # Show all metrics as lines
  %(prog)s --dots gpu_temp                     # Show gpu_temp as dots only
  %(prog)s --dots gpu_temp gpu_utilization_%% # Show both as dots
        """
    )
    parser.add_argument("--dots", nargs="*", default=None,
                        help="Metrics to plot as dots only (space-separated). If --dots is specified with no metrics, all metrics will be dots.")
    parser.add_argument("--stime", type=float, default=SAMPLE_INTERVAL,
                        metavar="SECONDS",
                        help=f"Sample time between readings in seconds (default: {SAMPLE_INTERVAL})")
    parser.add_argument("--buffer-size", type=int, default=600,
                        metavar="SAMPLES",
                        help="Number of samples to keep in history buffer (default: 600)")
    parser.add_argument("--metrics", nargs="+", default=None,
                        metavar="METRIC",
                        help="""Display only specified metrics (space-separated). Available metrics:
                        gtemp (GPU Temp), gmem (GPU Memory), gutil (GPU Utilization),
                        gwatt (GPU Watts), gfan (GPU Fan), ctemp (CPU Temp), cutil (CPU Utilization).
                        Example: --metrics gtemp gutil gmem""")
    args = parser.parse_args()

    # Handle --dots argument
    dots_mode = None
    if args.dots is not None:
        if len(args.dots) == 0:
            # --dots with no arguments means all metrics as dots
            dots_mode = ["gpu_temp", "Gpu_Memory_%", "gpu_utilization_%", "gpu_watts", "gpu_fan_%",
                         "cpu_temp", "cpu_utilization_%"]
        else:
            dots_mode = args.dots

    # Build metric visibility filter from --metrics argument
    metric_visibility = None
    if args.metrics:
        # Map shorthand names to full metric names
        metric_map = {
            "gtemp": "gpu_temp",
            "gmem": "Gpu_Memory_%",
            "gutil": "gpu_utilization_%",
            "gwatt": "gpu_watts",
            "gfan": "gpu_fan_%",
            "ctemp": "cpu_temp",
            "cutil": "cpu_utilization_%"
        }
        metric_visibility = {}
        for metric_key in metric_map.values():
            metric_visibility[metric_key] = False
        for shorthand in args.metrics:
            if shorthand in metric_map:
                metric_visibility[metric_map[shorthand]] = True
            else:
                print(f"Warning: Unknown metric '{shorthand}'. Use --help for available metrics.")

    win = GPUWindow(dots_mode=dots_mode, sample_interval=args.stime,
                    buffer_size=args.buffer_size, metric_visibility=metric_visibility)
    win.connect("destroy", Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    main()