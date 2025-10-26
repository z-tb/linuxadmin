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
from gi.repository import Gtk, GdkPixbuf, GLib  # Import GTK classes for GUI
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
    """
    def __init__(self, maxlen=600):
        self.samples = collections.deque(maxlen=maxlen)  # Efficient FIFO buffer

    def append(self, t, v):
        """
        Add a new sample. If time is non-monotonic, increment slightly
        to prevent issues in interpolation.
        """
        if self.samples and t <= self.samples[-1][0]:
            t = self.samples[-1][0] + 1e-6
        self.samples.append((t, float(v)))

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
            "Power_watts": power,
            "fan_%": fan,
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
                "Power_watts": pwr,
                "fan_%": fan,
            }
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
    def __init__(self, dots_mode=None):
        super().__init__(title="gpuck")
        self.set_icon(get_embedded_icon_pixbuf())  # Set window icon
        self.set_default_size(1000, 600)  # Initial size

        self.dots_mode = set(dots_mode) if dots_mode else set()  # Metrics to plot as dots only
        self.reader = GPUReader()  # GPU reader instance
        self.metrics = {k: MetricBuffer() for k in
                        ["gpu_temp", "Gpu_Memory_%", "gpu_utilization_%", "Power_watts", "fan_%"]}

        vbox = Gtk.VBox(spacing=6)
        self.add(vbox)

        # All metrics visible by default
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
        vbox.pack_start(self.da, True, True, 0)

        # Status label at bottom
        self.status = Gtk.Label(label="Initializing…")
        self.status.set_xalign(0)
        vbox.pack_end(self.status, False, False, 4)

        # Setup periodic GPU sampling and drawing refresh
        GLib.timeout_add(int(SAMPLE_INTERVAL * 1000), self.sample)
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

    def sample(self):
        """Read GPU metrics, append to buffers, prune old samples, update status label."""
        data = self.reader.read()
        t = time.time()
        if not data:
            self.status.set_text("No NVIDIA GPU detected.")
            return True
        for k in self.metrics:
            self.metrics[k].append(t, data.get(k, float("nan")))
            self.metrics[k].prune(t - WINDOW_SECONDS)
        self.status.set_text(
            f"Temp: {data.get('gpu_temp','?'):.0f}°C | "
            f"Util: {data.get('gpu_utilization_%','?'):.0f}% | "
            f"Power: {data.get('Power_watts','?'):.1f} W | "
            f"Mem: {data.get('Gpu_Memory_%','?'):.2f}% | "
            f"Fan: {data.get('fan_%','?'):.0f}%"
        )
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
        # Use wall-clock time for continuous smooth scrolling
        now = time.time()
        start = now - WINDOW_SECONDS

        colors = {
            "gpu_temp": (1, 0.4, 0.3),
            "Gpu_Memory_%": (0.3, 0.7, 1.0),
            "gpu_utilization_%": (0.4, 1.0, 0.4),
            "Power_watts": (1.0, 0.8, 0.2),
            "fan_%": (0.8, 0.5, 1.0),
        }

        for i, k in enumerate(keys):
            y0 = margin + i * (row_h + margin)
            plot_x0, plot_y0 = margin + 40, y0 + 10
            plot_x1, plot_y1 = w - margin - 5, y0 + row_h
            cr.set_source_rgb(0.15, 0.15, 0.15)
            cr.rectangle(plot_x0, plot_y0, plot_x1 - plot_x0, plot_y1 - plot_y0)
            cr.fill()

            # ranges per metric
            if k == "gpu_temp":
                ymin, ymax = 20, 100
            elif k == "Power_watts":
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
                    # Keep Y as float - let Cairo handle the rendering smoothly
                    y = plot_y1 - (v - ymin) / (ymax - ymin) * (plot_y1 - plot_y0)

                    if first_point:
                        cr.move_to(px, y)
                        first_point = False
                    else:
                        cr.line_to(px, y)

                cr.stroke()

            # Draw legend text in center of graph (dark cyan)
            cr.set_source_rgb(0.0, 0.55, 0.55)
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(12)
            legend = k.replace("_", " ").capitalize()
            extents = cr.text_extents(legend)
            cx = (plot_x0 + plot_x1) / 2 - extents.width / 2
            cy = (plot_y0 + plot_y1) / 2 + extents.height / 2
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
  %(prog)s                                    # Show all metrics as lines
  %(prog)s --dots gpu_temp                   # Show gpu_temp as dots only
  %(prog)s --dots gpu_temp gpu_utilization_% # Show both as dots
        """
    )
    parser.add_argument("--dots", nargs="*", default=None,
                        help="Metrics to plot as dots only (space-separated). If --dots is specified with no metrics, all metrics will be dots.")
    args = parser.parse_args()

    # Handle --dots argument
    dots_mode = None
    if args.dots is not None:
        if len(args.dots) == 0:
            # --dots with no arguments means all metrics as dots
            dots_mode = ["gpu_temp", "Gpu_Memory_%", "gpu_utilization_%", "Power_watts", "fan_%"]
        else:
            dots_mode = args.dots

    win = GPUWindow(dots_mode=dots_mode)
    win.connect("destroy", Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    main()