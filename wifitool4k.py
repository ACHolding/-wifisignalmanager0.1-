import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import re
import sys
import os
import threading
import time
import json
from datetime import datetime
from collections import deque
import platform

class ACWifiSignalManager:
    def __init__(self, master):
        self.master = master
        self.app_name = "acwifisignalmanager0.1"
        master.title(self.app_name)
        master.geometry("600x400")
        master.resizable(False, False)
        master.configure(bg='#0A2F5A')
        self.lock = threading.Lock()
        self.scanning = False
        self.scan_thread = None
        self.stop_event = threading.Event()
        self.last_results = []
        self.cache_file = os.path.expanduser(f"~/.{self.app_name}_cache")
        self.log_buffer = deque(maxlen=50)
        self.status_code = 500
        self.last_scan_time = "Never"
        self.retry_count = 0
        self.max_retries = 1
        self.heartbeat_state = 0
        self.scan_dots = 0
        self.scan_complete_timer = None
        self.os_type = platform.system()

        # Build UI first - everything must exist before logging
        self.build_ui()
        
        # Now safe to log
        self.log_event("Initialized", "INFO")
        self.log_event(f"OS detected: {self.os_type}", "INFO")

        # Load cache if exists
        self.load_cache()

        # Start heartbeat
        self.heartbeat()

        # Initial scan
        self.start_scan()

    def build_ui(self):
        # Style
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TButton', background='#000000', foreground='#4A90D9', borderwidth=2)
        style.map('TButton', background=[('active', '#1A1A1A'), ('disabled', '#333333')])
        style.configure('TLabel', background='#0A2F5A', foreground='#4A90D9')
        style.configure('TFrame', background='#0A2F5A')

        # Main layout: split pane
        self.paned = ttk.PanedWindow(self.master, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left frame for listbox
        left_frame = ttk.Frame(self.paned)
        self.paned.add(left_frame, weight=4)

        # Top status bar inside left frame
        top_frame = ttk.Frame(left_frame)
        top_frame.pack(fill=tk.X, pady=2)
        self.count_label = ttk.Label(top_frame, text="Networks: 0", font=('Arial', 9, 'bold'))
        self.count_label.pack(side=tk.LEFT, padx=5)
        self.status_code_label = ttk.Label(top_frame, text="Code: ---", font=('Arial', 9))
        self.status_code_label.pack(side=tk.RIGHT, padx=5)

        # Listbox with scrollbar
        mid_frame = ttk.Frame(left_frame)
        mid_frame.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(mid_frame, bg='#1E3B6D', fg='#4A90D9',
                                  selectbackground='#2E5A8A', selectforeground='white',
                                  font=('Consolas', 9))
        scrollbar = ttk.Scrollbar(mid_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Right frame for status panel
        right_frame = ttk.Frame(self.paned)
        self.paned.add(right_frame, weight=1)

        # Heartbeat indicator (square)
        self.heartbeat_canvas = tk.Canvas(right_frame, width=12, height=12, bg='#0A2F5A', highlightthickness=0)
        self.heartbeat_canvas.pack(pady=2)
        self.heartbeat_rect = self.heartbeat_canvas.create_rectangle(2, 2, 10, 10, fill='#00FF00', outline='')

        # Status labels in right panel
        ttk.Label(right_frame, text="LAST SCAN:", font=('Arial', 8, 'bold')).pack(anchor=tk.W, padx=2)
        self.time_label = ttk.Label(right_frame, text="Never", font=('Arial', 8))
        self.time_label.pack(anchor=tk.W, padx=5, pady=1)

        ttk.Label(right_frame, text="STATUS:", font=('Arial', 8, 'bold')).pack(anchor=tk.W, padx=2, pady=(5,0))
        self.status_label = ttk.Label(right_frame, text="Idle", font=('Arial', 8))
        self.status_label.pack(anchor=tk.W, padx=5, pady=1)

        ttk.Label(right_frame, text="LOG (last 3):", font=('Arial', 8, 'bold')).pack(anchor=tk.W, padx=2, pady=(5,0))
        self.log_display = tk.Text(right_frame, height=4, width=15, bg='#0A2F5A', fg='#4A90D9',
                                   font=('Consolas', 7), wrap=tk.WORD, relief=tk.FLAT)
        self.log_display.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.log_display.config(state=tk.DISABLED)

        # Bottom frame for scan button
        bottom_frame = ttk.Frame(self.master)
        bottom_frame.pack(fill=tk.X, pady=5)
        self.scan_btn = ttk.Button(bottom_frame, text="INITIATE SCAN", command=self.start_scan)
        self.scan_btn.pack(pady=3)

        # Bind keyboard shortcuts
        self.master.bind('<Key-s>', lambda e: self.start_scan())
        self.master.bind('<Key-S>', lambda e: self.start_scan())
        self.master.bind('<Key-c>', lambda e: self.clear_cache())
        self.master.bind('<Key-C>', lambda e: self.clear_cache())
        self.master.bind('<Key-r>', lambda e: self.refresh_display())
        self.master.bind('<Key-R>', lambda e: self.refresh_display())
        self.master.bind('<Key-e>', lambda e: self.export_data())
        self.master.bind('<Key-E>', lambda e: self.export_data())
        self.master.bind('<Key-l>', lambda e: self.dump_log())
        self.master.bind('<Key-L>', lambda e: self.dump_log())
        self.master.bind('<Control-Shift-L>', lambda e: self.dump_log())
        self.master.bind('<Key-q>', lambda e: self.quit_app())
        self.master.bind('<Key-Q>', lambda e: self.quit_app())

    def log_event(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] [{level}] {message}"
        self.log_buffer.append(entry)
        self.update_log_display()

    def update_log_display(self):
        self.log_display.config(state=tk.NORMAL)
        self.log_display.delete(1.0, tk.END)
        for line in list(self.log_buffer)[-3:]:
            self.log_display.insert(tk.END, line + "\n")
        self.log_display.config(state=tk.DISABLED)

    def heartbeat(self):
        if self.scanning:
            self.heartbeat_canvas.itemconfig(self.heartbeat_rect, fill='#FFA500')
        else:
            if self.status_code == 200:
                self.heartbeat_canvas.itemconfig(self.heartbeat_rect, fill='#00FF00')
            elif self.status_code >= 400:
                self.heartbeat_canvas.itemconfig(self.heartbeat_rect, fill='#FF0000')
            else:
                self.heartbeat_canvas.itemconfig(self.heartbeat_rect, fill='#00FF00')
        self.master.after(500, self.heartbeat)

    def load_cache(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                    self.last_results = data.get('results', [])
                    self.last_scan_time = data.get('time', 'Never')
                    if self.last_results:
                        self.log_event(f"Cache loaded: {len(self.last_results)} entries", "INFO")
                        self.refresh_display()
                        self.status_code = 206
                        self.status_code_label.config(text="Code: 206 (cache)")
        except Exception as e:
            self.log_event(f"Cache load failed: {str(e)[:30]}", "WARN")

    def save_cache(self):
        try:
            data = {
                'results': self.last_results,
                'time': self.last_scan_time
            }
            with open(self.cache_file, 'w') as f:
                json.dump(data, f)
            self.log_event("Cache saved", "INFO")
        except Exception as e:
            self.log_event(f"Cache save failed: {str(e)[:30]}", "WARN")

    def clear_cache(self):
        try:
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
            self.last_results = []
            self.listbox.delete(0, tk.END)
            self.count_label.config(text="Networks: 0")
            self.log_event("Cache cleared", "INFO")
            self.status_code = 404
            self.status_code_label.config(text="Code: 404")
            self.status_label.config(text="Cache cleared")
        except Exception as e:
            self.log_event(f"Clear cache failed: {str(e)[:30]}", "ERROR")

    def refresh_display(self):
        self.listbox.delete(0, tk.END)
        for entry in self.last_results:
            self.listbox.insert(tk.END, entry)
        self.count_label.config(text=f"Networks: {len(self.last_results)}")
        self.log_event("Display refreshed", "INFO")

    def export_data(self):
        if not self.last_results:
            messagebox.showinfo("Export", "No data to export")
            return
        filename = f"{self.app_name}_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        try:
            with open(filename, 'w') as f:
                f.write("SSID,BSSID,Signal,Channel\n")
                for entry in self.last_results:
                    parts = entry.split('|')
                    if len(parts) >= 4:
                        ssid = parts[0].replace("SSID:", "").strip()
                        bssid = parts[1].replace("BSSID:", "").strip()
                        signal = parts[2].replace("SIG:", "").replace("%", "").strip()
                        channel = parts[3].replace("CH:", "").strip()
                        f.write(f"{ssid},{bssid},{signal},{channel}\n")
            messagebox.showinfo("Export", f"Exported to {filename}")
            self.log_event(f"Exported to {filename}", "INFO")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))
            self.log_event(f"Export failed: {str(e)[:30]}", "ERROR")

    def dump_log(self):
        filename = f"{self.app_name}_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        try:
            with open(filename, 'w') as f:
                f.write(f"{self.app_name} log dump\n")
                f.write(f"Time: {datetime.now().isoformat()}\n")
                f.write("-" * 40 + "\n")
                for line in self.log_buffer:
                    f.write(line + "\n")
            messagebox.showinfo("Log Dump", f"Log saved to {filename}")
        except Exception as e:
            messagebox.showerror("Log Error", str(e))

    def quit_app(self):
        self.save_cache()
        self.log_event("Shutdown", "INFO")
        self.master.quit()
        self.master.destroy()

    def start_scan(self):
        if self.scanning:
            return
        self.scanning = True
        self.scan_btn.config(state=tk.DISABLED, text="SCANNING...")
        self.status_label.config(text="Scanning")
        self.log_event("Scan initiated", "INFO")
        self.retry_count = 0
        self.scan_thread = threading.Thread(target=self.scan_worker, daemon=True)
        self.scan_thread.start()
        self.animate_scan_button()

    def animate_scan_button(self):
        if self.scanning:
            dots = "." * ((self.scan_dots % 3) + 1)
            self.scan_btn.config(text=f"SCANNING{dots}")
            self.scan_dots += 1
            self.master.after(300, self.animate_scan_button)
        else:
            self.scan_btn.config(text="SCAN COMPLETE")
            self.master.after(2000, lambda: self.scan_btn.config(text="INITIATE SCAN", state=tk.NORMAL))

    def scan_worker(self):
        try:
            self.do_scan()
        except Exception as e:
            self.log_event(f"Scan error: {str(e)[:40]}", "ERROR")
            self.status_code = 500
            self.master.after(0, self.update_ui_after_scan)
        finally:
            self.scanning = False
            self.master.after(0, self.update_ui_after_scan)

    def do_scan(self):
        os_type = self.os_type
        if os_type == 'Windows':
            self.scan_windows()
        elif os_type == 'Darwin':
            self.scan_macos()
        elif os_type == 'Linux':
            self.scan_linux()
        else:
            self.status_code = 501
            self.last_results = [f"OS not supported: {os_type}"]
            self.log_event(f"Unsupported OS: {os_type}", "ERROR")

    def scan_windows(self):
        # Check admin
        is_admin = False
        try:
            import ctypes
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except:
            pass

        if not is_admin:
            self.log_event("Not running as admin - limited data", "WARN")
            self.status_code = 403

        cmd = ['netsh', 'wlan', 'show', 'networks', 'mode=Bssid']
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=12, shell=True)
            raw = result.stdout + result.stderr

            if "Access is denied" in raw or "failed" in raw.lower():
                self.log_event("Access denied - retry with admin", "ERROR")
                if self.retry_count < self.max_retries:
                    self.retry_count += 1
                    self.log_event(f"Retry {self.retry_count}", "INFO")
                    time.sleep(1)
                    self.do_scan()
                    return
                self.status_code = 403
                self.last_results = ["[ERROR] Admin rights required - run as administrator"]
                return

            self.parse_windows_output(raw)
            self.status_code = 200
            self.last_scan_time = datetime.now().isoformat()
            self.save_cache()

        except subprocess.TimeoutExpired:
            self.log_event("Scan timeout", "ERROR")
            if self.retry_count < self.max_retries:
                self.retry_count += 1
                self.log_event(f"Retry {self.retry_count}", "INFO")
                time.sleep(1)
                self.do_scan()
                return
            self.status_code = 503
            self.last_results = ["[ERROR] Scan timed out - check network interface"]
        except FileNotFoundError:
            self.log_event("netsh not found", "ERROR")
            self.status_code = 500
            self.last_results = ["[ERROR] netsh command not found"]

    def parse_windows_output(self, raw):
        lines = raw.splitlines()
        ssid = ""
        bssid = ""
        signal = ""
        channel = ""
        seen = set()
        results = []

        mac_regex = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if "SSID" in line and "BSSID" not in line and ":" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    raw_ssid = parts[1].strip()
                    if not raw_ssid or raw_ssid == " ":
                        raw_ssid = "<Hidden>"
                    try:
                        ssid = raw_ssid.encode('ascii', 'replace').decode('ascii')
                        if any(ord(c) < 32 for c in ssid):
                            ssid = "[UNPRINTABLE]"
                    except:
                        ssid = "[BINARY DATA]"

            if "BSSID" in line and ":" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    raw_bssid = parts[1].strip()
                    if mac_regex.match(raw_bssid):
                        bssid = raw_bssid.upper()
                    else:
                        bssid = f"[INVALID MAC: {raw_bssid}]"

            if "Signal" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    raw_signal = parts[1].strip().replace("%", "")
                    try:
                        signal_val = int(raw_signal)
                        signal_val = max(0, min(100, signal_val))
                        signal = str(signal_val)
                    except:
                        signal = "0"

            if "Channel" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    raw_channel = parts[1].strip()
                    try:
                        ch = int(raw_channel)
                        if not (1 <= ch <= 14 or 36 <= ch <= 165 or 1 <= ch <= 233):
                            ch = 0
                        channel = str(ch)
                    except:
                        channel = "0"

                    if bssid and bssid not in seen and ssid:
                        seen.add(bssid)
                        entry = f"SSID: {ssid[:25]:<25} | BSSID: {bssid} | SIG: {signal:>3}% | CH: {channel}"
                        results.append(entry)
                        ssid = ""
                        bssid = ""
                        signal = ""
                        channel = ""

        if not results:
            for line in lines:
                if "SSID" in line and "BSSID" not in line:
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        raw_ssid = parts[1].strip()
                        if raw_ssid and raw_ssid != " ":
                            results.append(f"SSID: {raw_ssid[:25]} | BSSID: N/A | SIG: N/A | CH: N/A")

        if not results:
            results = ["No Wi-Fi networks found - check adapter"]
            self.status_code = 404

        self.last_results = results

    def scan_macos(self):
        # Method 1: airport command
        airport_paths = [
            '/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport',
            '/usr/sbin/airport'
        ]
        airport_cmd = None
        for path in airport_paths:
            if os.path.exists(path):
                airport_cmd = path
                break

        if airport_cmd:
            try:
                cmd = [airport_cmd, '-s']
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if result.returncode == 0 and result.stdout:
                    self.parse_macos_airport(result.stdout)
                    self.status_code = 200
                    self.last_scan_time = datetime.now().isoformat()
                    self.save_cache()
                    return
            except Exception as e:
                self.log_event(f"airport failed: {str(e)[:30]}", "WARN")

        # Method 2: system_profiler
        try:
            cmd = ['system_profiler', 'SPAirPortDataType']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout:
                self.parse_macos_system_profiler(result.stdout)
                self.status_code = 200
                self.last_scan_time = datetime.now().isoformat()
                self.save_cache()
                return
        except Exception as e:
            self.log_event(f"system_profiler failed: {str(e)[:30]}", "WARN")

        # Method 3: ioreg for basic interface info
        try:
            cmd = ['ioreg', '-r', '-c', 'IO80211Interface']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout:
                self.parse_macos_ioreg(result.stdout)
                self.status_code = 200
                self.last_scan_time = datetime.now().isoformat()
                self.save_cache()
                return
        except:
            pass

        self.status_code = 404
        self.last_results = ["No Wi-Fi networks found - check adapter and permissions"]
        self.log_event("All macOS scan methods failed", "ERROR")

    def parse_macos_airport(self, raw):
        lines = raw.splitlines()
        results = []
        seen = set()
        mac_regex = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')

        # Skip header line
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 5:
                # Format: SSID BSSID RSSI CHANNEL HT CC SECURITY
                # Example: "MyWiFi 00:11:22:33:44:55 -45 6 Y WPA2"
                ssid_parts = []
                idx = 0
                # First part is SSID - could have spaces, so we need to find BSSID pattern
                for i, part in enumerate(parts):
                    if mac_regex.match(part):
                        # This is the BSSID
                        bssid = part.upper()
                        # Everything before is SSID
                        ssid = " ".join(parts[:i])
                        # Everything after: RSSI, CHANNEL, etc.
                        remaining = parts[i+1:]
                        if len(remaining) >= 2:
                            rssi = remaining[0]
                            channel = remaining[1]
                            try:
                                rssi_int = int(rssi)
                                # Convert dBm to percentage
                                sig_percent = max(0, min(100, 2 * (rssi_int + 100)))
                                signal = str(sig_percent)
                            except:
                                signal = "0"
                            try:
                                ch = int(channel)
                                if not (1 <= ch <= 14 or 36 <= ch <= 165 or 1 <= ch <= 233):
                                    ch = 0
                                channel = str(ch)
                            except:
                                channel = "0"
                            if bssid not in seen and ssid:
                                seen.add(bssid)
                                entry = f"SSID: {ssid[:25]:<25} | BSSID: {bssid} | SIG: {signal:>3}% | CH: {channel}"
                                results.append(entry)
                        break

        if not results:
            results = ["No Wi-Fi networks found via airport"]
            self.status_code = 404
        self.last_results = results

    def parse_macos_system_profiler(self, raw):
        lines = raw.splitlines()
        results = []
        seen = set()
        current_ssid = ""
        current_bssid = ""
        current_signal = "0"
        current_channel = "0"
        mac_regex = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if "Network Name:" in line:
                parts = line.split("Network Name:", 1)
                if len(parts) == 2:
                    current_ssid = parts[1].strip()
            if "BSSID:" in line:
                parts = line.split("BSSID:", 1)
                if len(parts) == 2:
                    raw_bssid = parts[1].strip()
                    if mac_regex.match(raw_bssid):
                        current_bssid = raw_bssid.upper()
            if "RSSI:" in line:
                parts = line.split("RSSI:", 1)
                if len(parts) == 2:
                    raw_rssi = parts[1].strip().replace("dBm", "").strip()
                    try:
                        rssi_int = int(raw_rssi)
                        sig_percent = max(0, min(100, 2 * (rssi_int + 100)))
                        current_signal = str(sig_percent)
                    except:
                        current_signal = "0"
            if "Channel:" in line and "BSSID:" not in line:
                parts = line.split("Channel:", 1)
                if len(parts) == 2:
                    raw_ch = parts[1].strip()
                    try:
                        ch = int(raw_ch.split()[0])
                        if not (1 <= ch <= 14 or 36 <= ch <= 165 or 1 <= ch <= 233):
                            ch = 0
                        current_channel = str(ch)
                    except:
                        current_channel = "0"
                    if current_bssid and current_bssid not in seen and current_ssid:
                        seen.add(current_bssid)
                        entry = f"SSID: {current_ssid[:25]:<25} | BSSID: {current_bssid} | SIG: {current_signal:>3}% | CH: {current_channel}"
                        results.append(entry)
                        current_ssid = ""
                        current_bssid = ""
                        current_signal = "0"
                        current_channel = "0"

        if not results:
            results = ["No Wi-Fi networks found via system_profiler"]
            self.status_code = 404
        self.last_results = results

    def parse_macos_ioreg(self, raw):
        results = []
        # Extract interface names and basic info
        for line in raw.splitlines():
            if "IO80211Interface" in line:
                if "IOBuiltin" in line:
                    results.append("Built-in Wi-Fi interface detected - use airport for scan")
        if not results:
            results = ["No Wi-Fi interface detected - check hardware"]
            self.status_code = 404
        self.last_results = results

    def scan_linux(self):
        # Try nmcli first
        cmd = ['nmcli', '-t', '-f', 'SSID,BSSID,SIGNAL,CHAN', 'dev', 'wifi', 'list']
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout:
                self.parse_nmcli_output(result.stdout)
                self.status_code = 200
                self.last_scan_time = datetime.now().isoformat()
                self.save_cache()
                return
        except:
            pass

        # Fallback to iwlist
        try:
            cmd = ['iwlist', 'scanning']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and result.stdout:
                self.parse_iwlist_output(result.stdout)
                self.status_code = 200
                self.last_scan_time = datetime.now().isoformat()
                self.save_cache()
                return
        except:
            pass

        # Fallback to iw dev scan
        try:
            # Get interface name
            iface_cmd = ['iw', 'dev']
            iface_result = subprocess.run(iface_cmd, capture_output=True, text=True, timeout=3)
            iface_lines = iface_result.stdout.splitlines()
            interface = None
            for line in iface_lines:
                if 'Interface' in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        interface = parts[1]
                        break
            if interface:
                cmd = ['iw', 'dev', interface, 'scan']
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if result.returncode == 0 and result.stdout:
                    self.parse_iw_scan_output(result.stdout)
                    self.status_code = 200
                    self.last_scan_time = datetime.now().isoformat()
                    self.save_cache()
                    return
        except:
            pass

        # Fallback to /proc/net/wireless
        try:
            with open('/proc/net/wireless', 'r') as f:
                content = f.read()
                if content:
                    self.parse_proc_wireless(content)
                    self.status_code = 200
                    self.last_scan_time = datetime.now().isoformat()
                    self.save_cache()
                    return
        except:
            pass

        self.status_code = 404
        self.last_results = ["No Wi-Fi networks found - check adapter and tools"]
        self.log_event("All Linux scan methods failed", "ERROR")

    def parse_nmcli_output(self, raw):
        lines = raw.splitlines()
        seen = set()
        results = []
        mac_regex = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')

        for line in lines:
            if ":" in line and not line.startswith("SSID"):
                parts = line.split(":", 3)
                if len(parts) >= 4:
                    ssid, bssid, signal, channel = parts[0], parts[1], parts[2], parts[3]
                    if not bssid or not mac_regex.match(bssid):
                        continue
                    if bssid in seen:
                        continue
                    seen.add(bssid)
                    try:
                        sig_int = int(signal)
                        sig_int = max(0, min(100, sig_int))
                        signal = str(sig_int)
                    except:
                        signal = "0"
                    try:
                        ch = int(channel)
                        if not (1 <= ch <= 14 or 36 <= ch <= 165 or 1 <= ch <= 233):
                            ch = 0
                        channel = str(ch)
                    except:
                        channel = "0"
                    if not ssid or ssid == "--" or ssid == "":
                        ssid = "<Hidden>"
                    entry = f"SSID: {ssid[:25]:<25} | BSSID: {bssid} | SIG: {signal:>3}% | CH: {channel}"
                    results.append(entry)

        if not results:
            results = ["No Wi-Fi networks found via nmcli"]
            self.status_code = 404
        self.last_results = results

    def parse_iwlist_output(self, raw):
        lines = raw.splitlines()
        results = []
        seen = set()
        ssid = ""
        bssid = ""
        signal = ""
        channel = ""
        mac_regex = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')

        for line in lines:
            line = line.strip()
            if "ESSID:" in line:
                parts = line.split("ESSID:", 1)
                if len(parts) == 2:
                    raw_ssid = parts[1].strip().strip('"')
                    if not raw_ssid:
                        raw_ssid = "<Hidden>"
                    ssid = raw_ssid
            if "Address:" in line:
                parts = line.split("Address:", 1)
                if len(parts) == 2:
                    raw_bssid = parts[1].strip()
                    if mac_regex.match(raw_bssid):
                        bssid = raw_bssid.upper()
            if "Signal level=" in line:
                parts = line.split("Signal level=", 1)
                if len(parts) == 2:
                    signal_part = parts[1].split(" ")[0].replace("dBm", "").strip()
                    try:
                        sig_dbm = int(signal_part)
                        sig_percent = max(0, min(100, 2 * (sig_dbm + 100)))
                        signal = str(sig_percent)
                    except:
                        signal = "0"
            if "Channel:" in line:
                parts = line.split("Channel:", 1)
                if len(parts) == 2:
                    channel = parts[1].strip().split(" ")[0]
                    try:
                        ch = int(channel)
                        if not (1 <= ch <= 14 or 36 <= ch <= 165 or 1 <= ch <= 233):
                            ch = 0
                        channel = str(ch)
                    except:
                        channel = "0"
                    if bssid and bssid not in seen and ssid:
                        seen.add(bssid)
                        entry = f"SSID: {ssid[:25]:<25} | BSSID: {bssid} | SIG: {signal:>3}% | CH: {channel}"
                        results.append(entry)
                        ssid = ""
                        bssid = ""
                        signal = ""
                        channel = ""

        if not results:
            results = ["No Wi-Fi networks found via iwlist"]
            self.status_code = 404
        self.last_results = results

    def parse_iw_scan_output(self, raw):
        lines = raw.splitlines()
        results = []
        seen = set()
        ssid = ""
        bssid = ""
        signal = ""
        channel = ""
        mac_regex = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')

        for line in lines:
            line = line.strip()
            if "SSID:" in line:
                parts = line.split("SSID:", 1)
                if len(parts) == 2:
                    raw_ssid = parts[1].strip()
                    if not raw_ssid:
                        raw_ssid = "<Hidden>"
                    ssid = raw_ssid
            if "BSS" in line and "(" in line and ")" in line:
                bssid_match = re.search(r'([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})', line)
                if bssid_match:
                    raw_bssid = bssid_match.group(1)
                    if mac_regex.match(raw_bssid):
                        bssid = raw_bssid.upper()
            if "signal:" in line:
                parts = line.split("signal:", 1)
                if len(parts) == 2:
                    sig_part = parts[1].strip().split()[0]
                    try:
                        sig_dbm = int(sig_part)
                        sig_percent = max(0, min(100, 2 * (sig_dbm + 100)))
                        signal = str(sig_percent)
                    except:
                        signal = "0"
            if "channel:" in line:
                parts = line.split("channel:", 1)
                if len(parts) == 2:
                    channel = parts[1].strip().split()[0]
                    try:
                        ch = int(channel)
                        if not (1 <= ch <= 14 or 36 <= ch <= 165 or 1 <= ch <= 233):
                            ch = 0
                        channel = str(ch)
                    except:
                        channel = "0"
                    if bssid and bssid not in seen and ssid:
                        seen.add(bssid)
                        entry = f"SSID: {ssid[:25]:<25} | BSSID: {bssid} | SIG: {signal:>3}% | CH: {channel}"
                        results.append(entry)
                        ssid = ""
                        bssid = ""
                        signal = ""
                        channel = ""

        if not results:
            results = ["No Wi-Fi networks found via iw scan"]
            self.status_code = 404
        self.last_results = results

    def parse_proc_wireless(self, raw):
        lines = raw.splitlines()
        results = []
        for line in lines[2:]:
            parts = line.split()
            if len(parts) >= 4:
                iface = parts[0].replace(':', '')
                try:
                    signal_raw = parts[3].replace('.', '').strip()
                    signal_val = int(signal_raw) if signal_raw else 0
                    signal_percent = max(0, min(100, signal_val))
                    entry = f"SSID: {iface[:25]:<25} | BSSID: N/A | SIG: {signal_percent:>3}% | CH: N/A"
                    results.append(entry)
                except:
                    continue
        if not results:
            results = ["No wireless interfaces found"]
            self.status_code = 404
        self.last_results = results

    def update_ui_after_scan(self):
        self.listbox.delete(0, tk.END)
        for entry in self.last_results:
            self.listbox.insert(tk.END, entry)
        self.count_label.config(text=f"Networks: {len(self.last_results)}")
        self.status_code_label.config(text=f"Code: {self.status_code}")
        if self.status_code == 200:
            self.status_label.config(text="Scan complete - OK")
        elif self.status_code == 206:
            self.status_label.config(text="Using cached data")
        elif self.status_code == 403:
            self.status_label.config(text="Permission denied")
        elif self.status_code == 404:
            self.status_label.config(text="No networks found")
        elif self.status_code == 503:
            self.status_label.config(text="Timeout - check interface")
        else:
            self.status_label.config(text=f"Error code {self.status_code}")
        self.time_label.config(text=self.last_scan_time)
        self.scan_btn.config(state=tk.NORMAL)
        self.scanning = False
        self.log_event(f"Scan finished - code {self.status_code}", "INFO")

if __name__ == "__main__":
    root = tk.Tk()
    app = ACWifiSignalManager(root)
    root.mainloop()
