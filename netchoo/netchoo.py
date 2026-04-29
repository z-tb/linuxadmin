#!/usr/bin/env python3

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk
import cairo
import os
import time
import argparse
from collections import defaultdict, deque
import threading
import queue

# Global configuration (will be set from command line arguments)
MAX_INTERFACE_CHARS = 20
SERIES_TIME_WINDOW = 300  # seconds (5 minutes)
REVERSE_DOCKER_BRIDGE_COLORS = False
GRAPH_UPDATE_INTERVAL = 1000  # milliseconds

class NetworkStats:
    def __init__(self):
        self.interfaces = {}
        self.previous_stats = {}
        
    def get_active_interfaces(self):
        """Get list of active network interfaces"""
        interfaces = []
        try:
            with open('/proc/net/dev', 'r') as f:
                lines = f.readlines()
                for line in lines[2:]:  # Skip header lines
                    parts = line.split(':')
                    if len(parts) >= 2:
                        interface = parts[0].strip()
                        # Skip loopback but include all other interfaces
                        if interface != 'lo' and self.has_traffic_or_is_up(interface):
                            interfaces.append(interface)
        except Exception as e:
            print(f"Error reading interfaces: {e}")
        return interfaces
    
    def has_traffic_or_is_up(self, interface):
        """Check if interface has traffic or is up"""
        try:
            # Check if interface is up
            with open(f'/sys/class/net/{interface}/operstate', 'r') as f:
                state = f.read().strip()
                if state == 'up':
                    return True
            
            # Also check if interface has any traffic (for VPNs, etc.)
            rx_bytes, tx_bytes = self.get_interface_stats(interface)
            if rx_bytes > 0 or tx_bytes > 0:
                return True
                
            # Check if interface exists in /sys/class/net
            return os.path.exists(f'/sys/class/net/{interface}')
        except:
            return True  # If we can't check, include it anyway
    
    def get_interface_stats(self, interface):
        """Get RX/TX bytes for an interface"""
        try:
            with open('/proc/net/dev', 'r') as f:
                for line in f:
                    if interface + ':' in line:
                        parts = line.split()
                        rx_bytes = int(parts[1])
                        tx_bytes = int(parts[9])
                        return rx_bytes, tx_bytes
        except Exception as e:
            print(f"Error reading stats for {interface}: {e}")
        return 0, 0
    
    def get_traffic_rates(self):
        """Get current traffic rates for all interfaces"""
        current_time = time.time()
        current_stats = {}
        rates = {}
        
        for interface in self.get_active_interfaces():
            rx_bytes, tx_bytes = self.get_interface_stats(interface)
            current_stats[interface] = {
                'rx_bytes': rx_bytes,
                'tx_bytes': tx_bytes,
                'time': current_time
            }
            
            if interface in self.previous_stats:
                prev = self.previous_stats[interface]
                time_diff = current_time - prev['time']
                
                if time_diff > 0:
                    rx_rate = (rx_bytes - prev['rx_bytes']) / time_diff
                    tx_rate = (tx_bytes - prev['tx_bytes']) / time_diff
                    rates[interface] = {
                        'rx_rate': max(0, rx_rate),  # Ensure non-negative
                        'tx_rate': max(0, tx_rate)
                    }
        
        self.previous_stats = current_stats
        return rates

class TrafficGraph(Gtk.DrawingArea):
    def __init__(self, interface_name):
        super().__init__()
        self.interface_name = interface_name
        self.set_size_request(400, 80)
        
        # Data storage with timestamps
        self.data_points = deque()  # Store (timestamp, rx_rate, tx_rate)
        
        # Scale factors
        self.max_rate = 1024 * 1024  # Start with 1 MB/s scale
        self.auto_scale = True
        
        # Check if this is a Docker bridge interface
        self.is_docker_bridge = self.interface_name.startswith('docker') or self.interface_name.startswith('br-')
        
        self.connect('draw', self.on_draw)
        
    def add_data_point(self, rx_rate, tx_rate):
        """Add new data point with timestamp"""
        current_time = time.time()
        self.data_points.append((current_time, rx_rate, tx_rate))
        
        # Remove old data points outside the time window
        cutoff_time = current_time - SERIES_TIME_WINDOW
        while self.data_points and self.data_points[0][0] < cutoff_time:
            self.data_points.popleft()
        
        # Auto-scale if needed
        if self.auto_scale and self.data_points:
            all_rates = [rx for _, rx, _ in self.data_points] + [tx for _, _, tx in self.data_points]
            if all_rates:
                max_current = max(all_rates)
                if max_current > self.max_rate * 0.8:
                    self.max_rate = max_current * 1.2
                elif max_current < self.max_rate * 0.3 and self.max_rate > 1024:
                    self.max_rate = max(max_current * 1.5, 1024)
        
        self.queue_draw()
    
    def format_bytes(self, bytes_per_sec):
        """Format bytes/sec to human readable format"""
        if bytes_per_sec < 1024:
            return f"{bytes_per_sec:.0f} B/s"
        elif bytes_per_sec < 1024 * 1024:
            return f"{bytes_per_sec/1024:.1f} KB/s"
        elif bytes_per_sec < 1024 * 1024 * 1024:
            return f"{bytes_per_sec/(1024*1024):.1f} MB/s"
        else:
            return f"{bytes_per_sec/(1024*1024*1024):.1f} GB/s"
    
    def on_draw(self, widget, cr):
        """Draw the graph"""
        allocation = widget.get_allocation()
        width = allocation.width
        height = allocation.height
        
        # Clear background
        cr.set_source_rgb(0.1, 0.1, 0.1)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        
        # Draw grid
        cr.set_source_rgb(0.3, 0.3, 0.3)
        cr.set_line_width(0.5)
        
        # Horizontal grid lines
        for i in range(1, 4):
            y = height * i / 4
            cr.move_to(0, y)
            cr.line_to(width, y)
            cr.stroke()
        
        # Vertical grid lines
        for i in range(1, 8):
            x = width * i / 8
            cr.move_to(x, 0)
            cr.line_to(x, height)
            cr.stroke()
        
        if not self.data_points:
            return
        
        # Calculate time range for current window
        current_time = time.time()
        time_start = current_time - SERIES_TIME_WINDOW
        
        # Determine if we should reverse colors for Docker bridge interfaces
        reverse_colors = REVERSE_DOCKER_BRIDGE_COLORS and self.is_docker_bridge
        
        # Set colors based on configuration
        if reverse_colors:
            # For Docker bridges: RX becomes red, TX becomes green
            rx_color = (0.8, 0.2, 0.2)  # Red for RX (was green)
            tx_color = (0.2, 0.8, 0.2)  # Green for TX (was red)
        else:
            # Normal interfaces: RX is green, TX is red
            rx_color = (0.2, 0.8, 0.2)  # Green for RX
            tx_color = (0.8, 0.2, 0.2)  # Red for TX
        
        # Draw RX data
        cr.set_source_rgb(*rx_color)
        cr.set_line_width(1.5)
        
        if len(self.data_points) > 1:
            first_point = True
            for timestamp, rx_rate, tx_rate in self.data_points:
                # Calculate x position based on time
                x = ((timestamp - time_start) / SERIES_TIME_WINDOW) * width
                y = height - (rx_rate / self.max_rate) * height
                
                if first_point:
                    cr.move_to(x, y)
                    first_point = False
                else:
                    cr.line_to(x, y)
            
            cr.stroke()
        
        # Draw TX data
        cr.set_source_rgb(*tx_color)
        cr.set_line_width(1.5)
        
        if len(self.data_points) > 1:
            first_point = True
            for timestamp, rx_rate, tx_rate in self.data_points:
                # Calculate x position based on time
                x = ((timestamp - time_start) / SERIES_TIME_WINDOW) * width
                y = height - (tx_rate / self.max_rate) * height
                
                if first_point:
                    cr.move_to(x, y)
                    first_point = False
                else:
                    cr.line_to(x, y)
            
            cr.stroke()
        
        # Draw current values
        cr.set_source_rgb(1, 1, 1)
        cr.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10)
        
        if self.data_points:
            _, rx_rate, tx_rate = self.data_points[-1]
            
            # Show labels based on color scheme
            if reverse_colors:
                rx_text = f"RX: {self.format_bytes(rx_rate)} (to containers)"
                tx_text = f"TX: {self.format_bytes(tx_rate)} (from containers)"
            else:
                rx_text = f"RX: {self.format_bytes(rx_rate)}"
                tx_text = f"TX: {self.format_bytes(tx_rate)}"
            
            cr.move_to(5, 15)
            cr.show_text(rx_text)
            
            cr.move_to(5, 30)
            cr.show_text(tx_text)
        
        # Draw scale
        scale_text = f"Scale: {self.format_bytes(self.max_rate)}"
        cr.move_to(width - 100, 15)
        cr.show_text(scale_text)

class NetworkMonitor(Gtk.Window):
    
    def __init__(self):
        super().__init__()
        
        self.set_title("Netchoo")
        self.set_default_size(600, 400)
        self.set_border_width(10)
        self.ROW_HEIGHT = 100  # approximate height per interface row
        self.CHROME_HEIGHT = 80  # title, legend, padding
        
        # Create main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(main_box)
        
        # Title (clickable for About dialog)
        title_label = Gtk.Label()
        title_label.set_markup("Netchoo Traffic Monitor")
        title_event = Gtk.EventBox()
        title_event.add(title_label)
        title_event.connect('button-press-event', self.on_title_clicked)
        title_event.set_tooltip_text("Click for About")
        main_box.pack_start(title_event, False, False, 0)
        
        # Legend
        legend_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        main_box.pack_start(legend_box, False, False, 0)
        
        rx_label = Gtk.Label()
        rx_label.set_markup('<span foreground="green">■ RX (Ingress)</span>')
        legend_box.pack_start(rx_label, False, False, 0)
        
        tx_label = Gtk.Label()
        tx_label.set_markup('<span foreground="red">■ TX (Egress)</span>')
        legend_box.pack_start(tx_label, False, False, 0)
        
        # Docker bridge color reversal toggle
        self.docker_check = Gtk.CheckButton(label="Reverse Docker bridge colors")
        self.docker_check.set_active(REVERSE_DOCKER_BRIDGE_COLORS)
        self.docker_check.connect('toggled', self.on_docker_reverse_toggled)
        legend_box.pack_start(self.docker_check, False, False, 0)
        
        # Scrolled window for interfaces
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        main_box.pack_start(scrolled, True, True, 0)
        
        # Container for interface rows
        self.interfaces_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        scrolled.add(self.interfaces_box)
        
        # Network stats manager
        self.net_stats = NetworkStats()
        self.graphs = {}
        
        # Start monitoring
        self.update_interfaces()
        GLib.timeout_add(GRAPH_UPDATE_INTERVAL, self.update_traffic)  # Update every second
        
        self.connect('destroy', Gtk.main_quit)
    
    
    def on_docker_reverse_toggled(self, widget):
        """Handle Docker bridge color reversal toggle"""
        global REVERSE_DOCKER_BRIDGE_COLORS
        REVERSE_DOCKER_BRIDGE_COLORS = widget.get_active()
        # Update tooltips on all docker bridge graphs
        for interface, components in self.graphs.items():
            graph = components['graph']
            if graph.is_docker_bridge:
                graph.set_tooltip_text(self.get_docker_tooltip())
        # Force redraw of all graphs
        for components in self.graphs.values():
            components['graph'].queue_draw()
    
    def on_title_clicked(self, widget, event):
        """Show About dialog"""
        about = Gtk.AboutDialog(transient_for=self, modal=True)
        about.set_program_name("Netchoo")
        about.set_version("1.0")
        about.set_comments(
            "\U0001f443 Achoo!\n\n"
            "A network bandwidth monitor/sniffer.\n"
            "Real-time per-interface RX/TX monitoring via /proc/net/dev."
        )
        about.set_license_type(Gtk.License.GPL_3_0)
        about.set_website("https://github.com/z-tb/linuxadmin")
        about.set_website_label("GitHub")
        about.set_authors(["z-tb"])
        about.run()
        about.destroy()
    
    @staticmethod
    def get_docker_tooltip():
        """Return tooltip text for Docker bridge interfaces"""
        if REVERSE_DOCKER_BRIDGE_COLORS:
            return (
                "Docker bridge - container perspective.\n"
                "RX (green) = containers receiving\n"
                "TX (red) = containers sending\n"
                "Uncheck 'Reverse Docker bridge colors' for host perspective."
            )
        else:
            return (
                "Docker bridge - host perspective.\n"
                "RX (green) = traffic from containers into host\n"
                "TX (red) = traffic from host to containers\n"
                "Check 'Reverse Docker bridge colors' for container perspective."
            )
    
    def update_interfaces(self):
        """Update the list of active interfaces"""
        active_interfaces = self.net_stats.get_active_interfaces()
        prev_count = len(self.graphs)
        
        # Add new interfaces
        for interface in active_interfaces:
            if interface not in self.graphs:
                self.add_interface_row(interface)
        
        # Remove inactive interfaces
        for interface in list(self.graphs.keys()):
            if interface not in active_interfaces:
                self.remove_interface_row(interface)
        
        # Resize window if interface count changed
        if len(self.graphs) != prev_count:
            self.resize_to_fit()
    
    def resize_to_fit(self):
        """Resize window height to fit all interface rows"""
        n = max(len(self.graphs), 1)
        target_height = self.CHROME_HEIGHT + n * self.ROW_HEIGHT
        screen = self.get_screen()
        max_height = int(screen.get_height() * 0.85)
        self.resize(self.get_size()[0], min(target_height, max_height))

    @staticmethod
    def get_interface_icon_name(interface):
        """Return a GTK icon name for the interface type"""
        name = interface.lower()
        if name.startswith(('veth', 'virbr')):
            return "computer"
        elif name.startswith(('docker',)):
            return "preferences-system-network"
        elif name.startswith(('wl', 'wlan', 'wifi')):
            return "network-wireless"
        elif name.startswith(('eth', 'en')):
            return "network-wired"
        elif name.startswith(('br',)):
            return "network-workgroup"
        elif name.startswith(('tun', 'tap', 'wg', 'gpd')):
            return "network-vpn"
        else:
            return "network-idle"
    
    def add_interface_row(self, interface):
        """Add a new interface row"""
        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row_box.set_border_width(5)
        
        # Interface type icon
        icon_name = self.get_interface_icon_name(interface)
        icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.LARGE_TOOLBAR)
        row_box.pack_start(icon, False, False, 0)
        
        # Truncate interface name if too long
        display_name = interface
        if len(display_name) > MAX_INTERFACE_CHARS:
            display_name = display_name[:MAX_INTERFACE_CHARS-3] + "..."
        
        # Interface name label with fixed width
        name_label = Gtk.Label()
        escaped_name = GLib.markup_escape_text(display_name)
        name_label.set_markup(f'<span foreground="#00FFFF" font_desc="monospace bold 10">{escaped_name}</span>')
        
        name_label.set_size_request(MAX_INTERFACE_CHARS * 8, -1)  # Approximate width calculation
        name_label.set_halign(Gtk.Align.START)
        name_label.set_valign(Gtk.Align.CENTER)
        name_label.set_xalign(0)  # Left align text within the label
        row_box.pack_start(name_label, False, False, 0)
        
        # Traffic graph - expandable width
        graph = TrafficGraph(interface)
        graph.set_size_request(400, 80)  # Minimum width
        if graph.is_docker_bridge:
            graph.set_tooltip_text(self.get_docker_tooltip())
        row_box.pack_start(graph, True, True, 0)
        
        # Add separator
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        
        self.interfaces_box.pack_start(row_box, False, False, 0)
        self.interfaces_box.pack_start(separator, False, False, 0)
        
        self.graphs[interface] = {
            'graph': graph,
            'row': row_box,
            'separator': separator
        }
        
        self.show_all()
    
    def remove_interface_row(self, interface):
        """Remove an interface row"""
        if interface in self.graphs:
            components = self.graphs[interface]
            self.interfaces_box.remove(components['row'])
            self.interfaces_box.remove(components['separator'])
            del self.graphs[interface]
    
    def update_traffic(self):
        """Update traffic data for all interfaces"""
        # Update interface list
        self.update_interfaces()
        
        # Get current traffic rates
        rates = self.net_stats.get_traffic_rates()
        
        # Update graphs
        for interface, components in self.graphs.items():
            graph = components['graph']
            if interface in rates:
                rx_rate = rates[interface]['rx_rate']
                tx_rate = rates[interface]['tx_rate']
                graph.add_data_point(rx_rate, tx_rate)
            else:
                graph.add_data_point(0, 0)
        
        return True  # Continue the timeout
    
    


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Netchoo - Real-time network interface monitoring with GTK3',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              # Use default settings
  %(prog)s -r                           # Reverse Docker bridge colors
  %(prog)s -t 600                       # Set 10-minute time window
  %(prog)s -r -t 180                    # Reverse colors and 3-minute capture window
  %(prog)s --docker-reverse --time 120  # Same as above using long options
  %(prog)s -s --sample                  # sample time for updating graph (milliseconds)
  %(prog)s --help                       # Show this help message
        """
    )
    
    parser.add_argument(
        '-r', '--docker-reverse',
        action='store_true',
        default=False,
        help='Reverse traffic colors for Docker bridge interfaces (default: True)'
    )

    parser.add_argument(
        '-s', '--sample',
        type=int,
        default=GRAPH_UPDATE_INTERVAL,
        metavar='MILLISECONDS',
        help='Sample time in milliseconds for updating graph (default: 1000)'
    )
    
    parser.add_argument(
        '-t', '--time',
        type=int,
        default=SERIES_TIME_WINDOW,
        metavar='SECONDS',
        help='Time window for data series in seconds (default: 300)'
    )
    
    parser.add_argument(
        '-v', '--version',
        action='version',
        version='Netchoo 1.0'
    )
    
    return parser.parse_args()

def main():
    global SERIES_TIME_WINDOW, REVERSE_DOCKER_BRIDGE_COLORS, GRAPH_UPDATE_INTERVAL
    
    # Parse command line arguments
    args = parse_arguments()
    
    # Set global configuration from command line arguments
    SERIES_TIME_WINDOW = args.time
    REVERSE_DOCKER_BRIDGE_COLORS = args.docker_reverse
    GRAPH_UPDATE_INTERVAL = args.sample
    
    # Validate arguments
    if args.time <= 0:
        print("Error: Time window must be positive")
        return 1
    
    # Print configuration
    print(f"Network Traffic Monitor starting with:")
    print(f"  Time window: {SERIES_TIME_WINDOW} seconds")
    print(f"  Docker bridge color reversal: {'enabled' if REVERSE_DOCKER_BRIDGE_COLORS else 'disabled'}")
    
    # Create and run the application
    try:
        app = NetworkMonitor()
        app.show_all()
        Gtk.main()
    except KeyboardInterrupt:
        print("\nShutting down...")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
