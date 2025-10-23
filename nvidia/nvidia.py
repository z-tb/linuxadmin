#!/usr/bin/env python3
"""
gpuck.py
Real-time GTK GPU monitor with smooth scrolling graphs.
Embedded SVG icon, gridlines, centered legend text in dark cyan, and bottom summary.
"""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GdkPixbuf, GLib
import cairo
import time, math, collections, base64, subprocess, threading

try:
    import pynvml
    pynvml.nvmlInit()
    PYNVML = True
except Exception:
    PYNVML = False


# Embedded SVG icon
ICON_SVG_BASE64 = base64.b64encode(b"""
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
""").decode("ascii")


def get_embedded_icon_pixbuf():
    svg_bytes = base64.b64decode(ICON_SVG_BASE64)
    loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
    loader.write(svg_bytes)
    loader.close()
    return loader.get_pixbuf()


# =====================================================
# Metric buffer
# =====================================================
class MetricBuffer:
    def __init__(self, maxlen=600):
        self.samples = collections.deque(maxlen=maxlen)

    def append(self, t, v):
        if self.samples and t <= self.samples[-1][0]:
            t = self.samples[-1][0] + 1e-6
        self.samples.append((t, float(v)))

    def prune(self, cutoff):
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

    def get_value_at(self, t):
        if not self.samples:
            return float("nan")
        if t <= self.samples[0][0]:
            return self.samples[0][1]
        if t >= self.samples[-1][0]:
            return self.samples[-1][1]
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


# =====================================================
# GPU Reader
# =====================================================
class GPUReader:
    def __init__(self):
        self.lock = threading.Lock()
        if PYNVML:
            try:
                self.count = pynvml.nvmlDeviceGetCount()
            except Exception:
                self.count = 0
        else:
            self.count = self._count_via_nvidia_smi()

    def _count_via_nvidia_smi(self):
        try:
            out = subprocess.check_output(["nvidia-smi", "-L"], encoding="utf-8")
            return len([l for l in out.splitlines() if l.strip()])
        except Exception:
            return 0

    def read(self):
        with self.lock:
            if PYNVML and self.count > 0:
                return self._read_pynvml()
            return self._read_nvidia_smi()

    def _read_pynvml(self):
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        mem_pct = (mem.used / mem.total) * 100 if mem.total else 0
        util = pynvml.nvmlDeviceGetUtilizationRates(h).gpu
        power = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0
        fan = pynvml.nvmlDeviceGetFanSpeed(h)
        return {
            "temperature": temp,
            "memory_pct": mem_pct,
            "gpu_util_pct": util,
            "power_w": power,
            "fan_pct": fan,
        }

    def _read_nvidia_smi(self):
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
                "temperature": t,
                "memory_pct": mem_pct,
                "gpu_util_pct": util,
                "power_w": pwr,
                "fan_pct": fan,
            }
        except Exception:
            return {}


# =====================================================
# GTK Window
# =====================================================
WINDOW_SECONDS = 300
SAMPLE_INTERVAL = 0.5
RENDER_FPS = 30


class GPUWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="gpuck")
        self.set_icon(get_embedded_icon_pixbuf())
        self.set_default_size(1000, 600)

        self.reader = GPUReader()
        self.metrics = {k: MetricBuffer() for k in
                        ["temperature", "memory_pct", "gpu_util_pct", "power_w", "fan_pct"]}

        vbox = Gtk.VBox(spacing=6)
        self.add(vbox)

        self.metric_visibility = {k: True for k in self.metrics}

        menubar = Gtk.MenuBar()
        # File Menu
        filemenu = Gtk.Menu()
        file_item = Gtk.MenuItem(label="File")
        file_item.set_submenu(filemenu)
        exit_item = Gtk.MenuItem(label="Exit")
        exit_item.connect("activate", lambda w: Gtk.main_quit())
        filemenu.append(exit_item)
        menubar.append(file_item)

        # View Menu
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

        # Help Menu
        helpmenu = Gtk.Menu()
        help_item = Gtk.MenuItem(label="Help")
        help_item.set_submenu(helpmenu)
        about_item = Gtk.MenuItem(label="About")
        about_item.connect("activate", self.show_about)
        helpmenu.append(about_item)
        menubar.append(help_item)

        # Insert menubar at top of vbox
        vbox.pack_start(menubar, False, False, 0)
        self.da = Gtk.DrawingArea()
        self.da.connect("draw", self.on_draw)
        vbox.pack_start(self.da, True, True, 0)

        self.status = Gtk.Label(label="Initializing…")
        self.status.set_xalign(0)
        vbox.pack_end(self.status, False, False, 4)

        GLib.timeout_add(int(SAMPLE_INTERVAL * 1000), self.sample)
        GLib.timeout_add(int(1000 / RENDER_FPS), self.refresh)
        self.show_all()

    # Callback for toggling graph visibility
    def on_toggle_metric(self, widget, key):
        """
        Update visibility of individual metrics based on the checkbox state.
        Allows multiple metrics to be visible simultaneously.
        """
        # Each checkbox independently controls the metric
        self.metric_visibility[key] = widget.get_active()

        # Trigger redraw of the drawing area
        self.da.queue_draw()

    # About dialog
    def show_about(self, widget):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="gpuck",
        )
        dialog.format_secondary_text("Animal mascot: Red Panda 🦊\nVersion: 1.0")
        dialog.run()
        dialog.destroy()

    def sample(self):
        data = self.reader.read()
        t = time.time()
        if not data:
            self.status.set_text("No NVIDIA GPU detected.")
            return True
        for k in self.metrics:
            self.metrics[k].append(t, data.get(k, float("nan")))
            self.metrics[k].prune(t - WINDOW_SECONDS)
        self.status.set_text(
            f"Temp: {data.get('temperature','?'):.0f}°C | "
            f"Util: {data.get('gpu_util_pct','?'):.0f}% | "
            f"Power: {data.get('power_w','?'):.1f} W | "
            f"Mem: {data.get('memory_pct','?'):.2f}% | "
            f"Fan: {data.get('fan_pct','?'):.0f}%"
        )
        return True

    def refresh(self):
        self.da.queue_draw()
        return True

    def draw_grid(self, cr, x0, y0, x1, y1, ymin, ymax):
        cr.set_line_width(1)
        cr.set_source_rgb(0.25, 0.25, 0.25)
        # Only 3 lines: lower, middle, upper
        values = [ymin, (ymin + ymax) / 2, ymax]
        for v in values:
            y = y1 - (v - ymin) / (ymax - ymin) * (y1 - y0)
            # horizontal line
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
        now, start = time.time(), time.time() - WINDOW_SECONDS

        colors = {
            "temperature": (1, 0.4, 0.3),
            "memory_pct": (0.3, 0.7, 1.0),
            "gpu_util_pct": (0.4, 1.0, 0.4),
            "power_w": (1.0, 0.8, 0.2),
            "fan_pct": (0.8, 0.5, 1.0),
        }

        for i, k in enumerate(keys):
            y0 = margin + i * (row_h + margin)
            plot_x0, plot_y0 = margin + 40, y0 + 10
            plot_x1, plot_y1 = w - margin - 5, y0 + row_h
            cr.set_source_rgb(0.15, 0.15, 0.15)
            cr.rectangle(plot_x0, plot_y0, plot_x1 - plot_x0, plot_y1 - plot_y0)
            cr.fill()

            # ranges per metric
            if k == "temperature":
                ymin, ymax = 20, 100
            elif k == "power_w":
                ymin, ymax = 0, 300
            else:
                ymin, ymax = 0, 100

            self.draw_grid(cr, plot_x0, plot_y0, plot_x1, plot_y1, ymin, ymax)

            # draw metric line
            path = []
            for px in range(int(plot_x0), int(plot_x1)):
                t = start + ((px - plot_x0) / (plot_x1 - plot_x0)) * WINDOW_SECONDS
                v = self.metrics[k].get_value_at(t)
                if math.isnan(v): continue
                v = max(ymin, min(ymax, v))
                y = plot_y1 - (v - ymin) / (ymax - ymin) * (plot_y1 - plot_y0)
                path.append((px, y))
            if path:
                cr.set_source_rgb(*colors[k])
                cr.set_line_width(2.0)
                cr.move_to(*path[0])
                for x, y in path[1:]:
                    cr.line_to(x, y)
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


def main():
    win = GPUWindow()
    win.connect("destroy", Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    main()
