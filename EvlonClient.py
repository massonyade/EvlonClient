import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk, ImageDraw
from pystray import MenuItem as item, Icon
import threading
from pynput import keyboard
import psutil
from datetime import datetime
import json
import os
import sys
import shutil
import time

COLOR_THEMES = {
    "標準 (灰色)": {"bg": "#222222", "fg": "white"},
    "標準 (白)": {"bg": "#E0E0E0", "fg": "black"},
    "赤+黒": {"bg": "#1C1C1C", "fg": "#FF4C4C"},
    "青+黒": {"bg": "#1C1C1C", "fg": "#00A2FF"},
    "黄緑+黒": {"bg": "#1C1C1C", "fg": "#A8FF00"},
    "青+白": {"bg": "#F0F0F0", "fg": "#007ACC"},
    "黄緑+白": {"bg": "#F0F0F0", "fg": "#69B400"},
}

DEFAULT_SETTINGS = {
    "hotkey": "<ctrl>+<shift>+o",
    "alpha": 0.7,
    "font_size": 12,
    "time_format": "24h",
    "show_cpu": True,
    "show_ram": True,
    "show_time": True,
    "show_network": True,
    "show_temp": True,
    "show_battery": True,
    "show_voltage": False,
    "show_amperage": False,
    "theme": "標準 (灰色)",
    "update_interval": 2.0,
}

APP_DATA_PATH = os.path.join(os.getenv('APPDATA'), 'EvlonClient')
CONFIG_FILE = os.path.join(APP_DATA_PATH, 'config.json')

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

ICON_PATH = resource_path("EC.ico")

class ScreenOverlayApp:
    def __init__(self):
        try:
            p = psutil.Process(os.getpid())
            if os.name == 'nt':
                p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except Exception as e:
            print(f"Priority error: {e}")
        
        self.settings = self.load_settings()
        self.root = None
        self.overlay_window = None
        self.info_window = None
        self.settings_window = None
        self.icon = None
        self.hotkey_listener = None
        self.info_label = None
        self.settings_icon = None
        self.info_frame = None
        self.current_state = 0
        self._offset_x = 0
        self._offset_y = 0

        self.last_net_io = psutil.net_io_counters()
        self.last_net_time = time.time()

        self.setup_hotkey_listener()
        threading.Thread(target=self.run_tkinter_app, daemon=True).start()

    def run_cleanup_in_thread(self):
        if messagebox.askyesno("Confirm", "Delete temporary files?", parent=self.settings_window):
            threading.Thread(target=self.clear_temp_files, daemon=True).start()

    def clear_temp_files(self):
        temp_folders = [os.environ.get('TEMP'), os.path.join(os.environ.get('SystemRoot'), 'Temp'), os.path.join(os.environ.get('SystemRoot'), 'Prefetch'), os.path.join(os.environ.get('SystemRoot'), 'SoftwareDistribution', 'Download')]
        deleted_count, total_size = 0, 0
        self.root.after(0, lambda: self.settings_window.title("Cleaning..."))
        for folder in temp_folders:
            if folder and os.path.exists(folder):
                for item_name in os.listdir(folder):
                    item_path = os.path.join(folder, item_name)
                    try:
                        size = os.path.getsize(item_path)
                        if os.path.isfile(item_path): os.remove(item_path)
                        elif os.path.isdir(item_path): shutil.rmtree(item_path, ignore_errors=True)
                        deleted_count += 1
                        total_size += size
                    except (PermissionError, FileNotFoundError, OSError): continue
        total_size_mb = total_size / (1024 * 1024)
        message = f"Deleted {deleted_count} files.\nFreed {total_size_mb:.2f} MB."
        self.root.after(0, lambda: self.settings_window.title("Settings"))
        messagebox.showinfo("Done", message, parent=self.settings_window)

    def save_settings(self):
        os.makedirs(APP_DATA_PATH, exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.settings, f, indent=4)

    def load_settings(self):
        settings = DEFAULT_SETTINGS.copy()
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    user_settings = json.load(f)
                    settings.update(user_settings)
            except (json.JSONDecodeError, KeyError): pass
        return settings

    def set_click_through(self, hwnd):
        try:
            from win32gui import SetWindowLong, GetWindowLong, WS_EX_TRANSPARENT, GWL_EXSTYLE
            styles = GetWindowLong(hwnd, GWL_EXSTYLE) | WS_EX_TRANSPARENT
            SetWindowLong(hwnd, GWL_EXSTYLE, styles)
        except: pass

    def set_clickable(self, hwnd):
        try:
            from win32gui import SetWindowLong, GetWindowLong, WS_EX_TRANSPARENT, GWL_EXSTYLE
            styles = GetWindowLong(hwnd, GWL_EXSTYLE) & ~WS_EX_TRANSPARENT
            SetWindowLong(hwnd, GWL_EXSTYLE, styles)
        except: pass

    def create_windows(self):
        self.root = tk.Tk()
        self.root.withdraw()
        try:
            pil_icon = Image.open(ICON_PATH)
            self.app_icon = ImageTk.PhotoImage(pil_icon)
        except: self.app_icon = None
        self.overlay_window = tk.Toplevel(self.root)
        self.overlay_window.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
        self.overlay_window.overrideredirect(True)
        self.overlay_window.config(bg="black")
        self.overlay_window.wm_attributes("-topmost", True)
        self.set_click_through(self.overlay_window.winfo_id())
        self.overlay_window.withdraw()
        self.info_window = tk.Toplevel(self.root)
        self.info_window.overrideredirect(True)
        self.info_window.wm_attributes("-topmost", True)
        self.info_window.wm_attributes("-transparentcolor", "black")
        self.info_window.config(bg="black")
        self.info_frame = tk.Frame(self.info_window)
        self.info_frame.pack()
        self.settings_icon = tk.Label(self.info_frame, text="⚙️", font=("Arial", 10))
        self.settings_icon.grid(row=0, column=0, sticky="nw", padx=5, pady=5)
        self.info_label = tk.Label(self.info_frame, justify=tk.LEFT, padx=10, pady=5)
        self.info_label.grid(row=0, column=1, sticky="w")
        self.settings_icon.bind("<Button-1>", self.open_settings_window)
        self.info_frame.bind("<ButtonPress-1>", self.start_move)
        self.info_frame.bind("<B1-Motion>", self.do_move)
        self.info_label.bind("<ButtonPress-1>", self.start_move)
        self.info_label.bind("<B1-Motion>", self.do_move)
        self.info_window.withdraw()
        self.apply_settings()
        self.update_info()
        self.root.mainloop()

    def apply_settings(self):
        theme_name = self.settings.get("theme", "標準 (灰色)")
        colors = COLOR_THEMES.get(theme_name, COLOR_THEMES["標準 (灰色)"])
        bg_color, fg_color = colors["bg"], colors["fg"]
        self.info_frame.config(bg=bg_color)
        self.info_label.config(font=("Arial", self.settings["font_size"], "bold"), bg=bg_color, fg=fg_color)
        self.settings_icon.config(bg=bg_color, fg=fg_color)
        self.overlay_window.wm_attributes("-alpha", self.settings["alpha"])
        self.update_info()
        self.info_window.update_idletasks()
        info_width = self.info_window.winfo_width()
        current_y = self.info_window.winfo_y()
        new_x = (self.root.winfo_screenwidth() // 2) - (info_width // 2)
        if self.current_state == 0: self.info_window.geometry(f"+{new_x}+{20}")
        else: self.info_window.geometry(f"+{new_x}+{current_y}")

    def format_speed(self, bits_per_second):
        bytes_per_second = bits_per_second / 8
        if bytes_per_second < 1024: return f"{bytes_per_second: >4.0f} B/s"
        elif bytes_per_second < 1024 * 1024: return f"{bytes_per_second / 1024: >4.0f} KB/s"
        else: return f"{bytes_per_second / (1024 * 1024): >4.1f} MB/s"

    def update_info(self):
        info_parts = []
        if self.settings.get("show_cpu", True): info_parts.append(f"💻 CPU: {psutil.cpu_percent():>5.1f} %")
        if self.settings.get("show_ram", True): info_parts.append(f"🧠 RAM: {psutil.virtual_memory().percent:>5.1f} %")
        if self.settings.get("show_temp", True):
            try:
                temps = psutil.sensors_temperatures()
                if 'coretemp' in temps and temps['coretemp']:
                    cpu_temp = temps['coretemp'][0].current
                    info_parts.append(f"🌡️ TEMP: {cpu_temp: >4.0f} °C")
                else: info_parts.append("🌡️ TEMP:    N/A")
            except Exception: info_parts.append("🌡️ TEMP:    N/A")
        if self.settings.get("show_network", True):
            current_net_io = psutil.net_io_counters()
            current_time = time.time()
            elapsed_time = current_time - self.last_net_time
            if elapsed_time > 0:
                sent_speed = (current_net_io.bytes_sent - self.last_net_io.bytes_sent) * 8 / elapsed_time
                recv_speed = (current_net_io.bytes_recv - self.last_net_io.bytes_recv) * 8 / elapsed_time
                info_parts.append(f"📤 NET: {self.format_speed(sent_speed)}")
                info_parts.append(f"📥 NET: {self.format_speed(recv_speed)}")
            self.last_net_io = current_net_io
            self.last_net_time = current_time

        battery = psutil.sensors_battery()
        
        if self.settings.get("show_battery", True):
            if battery:
                plugged_status = " 接続" if battery.power_plugged else ""
                info_parts.append(f"🔋 BAT: {battery.percent}%{plugged_status}")
            else:
                info_parts.append("🔋 BAT: N/A")

        if self.settings.get("show_voltage", False):
            info_parts.append("⚡ VOLT: N/A")

        if self.settings.get("show_amperage", False):
            info_parts.append("🔌 AMP:  N/A")

        if self.settings.get("show_time", True):
            time_format = "%I:%M:%S %p" if self.settings.get("time_format") == "12h" else "%H:%M:%S"
            info_parts.append(f"🕒 TIME: {datetime.now().strftime(time_format)}")
        if not info_parts:
            self.info_label.config(text="Open Settings ⚙️")
        else:
            self.info_label.config(text="\n".join(info_parts))
        
        update_ms = int(self.settings.get("update_interval", 2.0) * 1000)
        self.root.after(update_ms, self.update_info)

    def toggle_overlay(self):
        if not self.root: return
        self.current_state = (self.current_state + 1) % 3
        if self.current_state == 0:
            self.overlay_window.withdraw()
            self.info_window.withdraw()
        elif self.current_state == 1:
            self.set_clickable(self.info_window.winfo_id())
            self.settings_icon.grid()
            self.overlay_window.deiconify()
            self.info_window.deiconify()
        elif self.current_state == 2:
            self.set_click_through(self.info_window.winfo_id())
            self.settings_icon.grid_remove()
            self.overlay_window.withdraw()
            self.info_window.deiconify()

    def start_move(self, event):
        self._offset_x = event.x
        self._offset_y = event.y

    def do_move(self, event):
        x = self.info_window.winfo_pointerx() - self._offset_x
        y = self.info_window.winfo_pointery() - self._offset_y
        self.info_window.geometry(f"+{x}+{y}")

    def open_task_manager(self):
        try:
            os.system('taskmgr')
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open Task Manager: {e}", parent=self.settings_window)

    def open_settings_window(self, event=None):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title("Settings")
        self.settings_window.geometry("300x750")
        self.settings_window.wm_attributes("-topmost", True)
        self.settings_window.config(bg="#2d2d2d")
        if self.app_icon: self.settings_window.iconphoto(False, self.app_icon)
        
        style = ttk.Style(self.settings_window)
        style.theme_use('clam')
        style.configure('.', background='#2d2d2d', foreground='white', fieldbackground='#555555', borderwidth=1)
        style.configure('TLabel', background='#2d2d2d', foreground='white')
        style.configure('TButton', background='#555555', foreground='white')
        style.map('TButton', background=[('active', '#666666')])
        style.configure('Horizontal.TScale', troughcolor='#555555', background='#666666')
        style.configure('TCheckbutton', background='#2d2d2d', foreground='white', indicatorcolor='black')
        style.map('TCheckbutton', foreground=[('active', 'white')], background=[('active', '#2d2d2d')])
        style.configure('TLabelFrame', background='#2d2d2d', bordercolor='#555555')
        style.configure('TLabelFrame.Label', background='#2d2d2d', foreground='white')
        style.configure('TCombobox', fieldbackground='#555555', background='#555555', foreground='white', arrowcolor='white')
        self.settings_window.option_add('*TCombobox*Listbox.background', '#555555')
        self.settings_window.option_add('*TCombobox*Listbox.foreground', 'white')

        display_frame = ttk.LabelFrame(self.settings_window, text="Display Items")
        display_frame.pack(pady=(10,0), padx=20, fill='x')
        
        show_vars = {
            "cpu": tk.BooleanVar(value=self.settings.get("show_cpu", True)),
            "ram": tk.BooleanVar(value=self.settings.get("show_ram", True)),
            "temp": tk.BooleanVar(value=self.settings.get("show_temp", True)),
            "network": tk.BooleanVar(value=self.settings.get("show_network", True)),
            "battery": tk.BooleanVar(value=self.settings.get("show_battery", True)),
            "voltage": tk.BooleanVar(value=self.settings.get("show_voltage", False)),
            "amperage": tk.BooleanVar(value=self.settings.get("show_amperage", False)),
            "time": tk.BooleanVar(value=self.settings.get("show_time", True))
        }
        
        ttk.Checkbutton(display_frame, text="CPU Usage", variable=show_vars["cpu"]).pack(anchor='w', padx=10)
        ttk.Checkbutton(display_frame, text="RAM Usage", variable=show_vars["ram"]).pack(anchor='w', padx=10)
        ttk.Checkbutton(display_frame, text="CPU Temp", variable=show_vars["temp"]).pack(anchor='w', padx=10)
        ttk.Checkbutton(display_frame, text="Network Speed", variable=show_vars["network"]).pack(anchor='w', padx=10)
        
        ttk.Separator(display_frame, orient='horizontal').pack(fill='x', pady=5, padx=10)
        ttk.Checkbutton(display_frame, text="Battery Level", variable=show_vars["battery"]).pack(anchor='w', padx=10)
        ttk.Checkbutton(display_frame, text="Voltage (V)", variable=show_vars["voltage"]).pack(anchor='w', padx=10)
        ttk.Checkbutton(display_frame, text="Amperage (A)", variable=show_vars["amperage"]).pack(anchor='w', padx=10)
        
        ttk.Separator(display_frame, orient='horizontal').pack(fill='x', pady=5, padx=10)
        ttk.Checkbutton(display_frame, text="Time", variable=show_vars["time"]).pack(anchor='w', padx=10)

        general_frame = ttk.LabelFrame(self.settings_window, text="General")
        general_frame.pack(pady=(10,0), padx=20, fill='x')
        
        ttk.Label(general_frame, text="Font Size").pack(pady=(5,0), padx=10, anchor='w')
        font_slider = ttk.Scale(general_frame, from_=8, to=24, command=lambda s: self.settings.update({"font_size": int(float(s))}))
        font_slider.set(self.settings["font_size"])
        font_slider.pack(fill="x", padx=10)
        
        ttk.Label(general_frame, text="Background Alpha").pack(pady=(5,0), padx=10, anchor='w')
        alpha_slider = ttk.Scale(general_frame, from_=0.1, to=1.0, command=lambda s: self.settings.update({"alpha": float(s)}))
        alpha_slider.set(self.settings["alpha"])
        alpha_slider.pack(fill="x", padx=10)
        
        ttk.Label(general_frame, text="Color Theme").pack(pady=(5,0), padx=10, anchor='w')
        theme_var = tk.StringVar(value=self.settings.get("theme", "標準 (灰色)"))
        theme_combo = ttk.Combobox(general_frame, textvariable=theme_var, values=list(COLOR_THEMES.keys()), state='readonly')
        theme_combo.pack(fill="x", padx=10)
        
        ttk.Label(general_frame, text="Update Interval (sec)").pack(pady=(5,0), padx=10, anchor='w')
        interval_var = tk.StringVar(value=self.settings.get("update_interval", 2.0))
        interval_combo = ttk.Combobox(general_frame, textvariable=interval_var, values=[0.5, 1.0, 1.5, 2.0, 5.0], state='readonly')
        interval_combo.pack(fill="x", padx=10, pady=(0, 5))

        ttk.Label(general_frame, text="Hotkey").pack(pady=(5,0), padx=10, anchor='w')
        hotkey_var = tk.StringVar(value=self.settings["hotkey"])
        ttk.Entry(general_frame, textvariable=hotkey_var).pack(fill="x", padx=10)
        
        time_format_var = tk.BooleanVar(value=self.settings.get("time_format") == "12h")
        ttk.Checkbutton(general_frame, text="Use 12h Format (AM/PM)", variable=time_format_var).pack(pady=5, padx=10, anchor='w')

        maintenance_frame = ttk.LabelFrame(self.settings_window, text="Maintenance")
        maintenance_frame.pack(pady=(10,0), padx=20, fill='x')
        
        instruction_text = "You can manually change the process priority to prioritize game performance."
        ttk.Label(maintenance_frame, text=instruction_text, wraplength=250).pack(pady=5, padx=10)
        
        taskmgr_button = ttk.Button(maintenance_frame, text="Open Task Manager", command=self.open_task_manager, style='TButton')
        taskmgr_button.pack(pady=5, padx=10, fill='x')

        cleanup_button = ttk.Button(maintenance_frame, text="Clean Temp Files", command=self.run_cleanup_in_thread, style='TButton')
        cleanup_button.pack(pady=(5,10), padx=10, fill='x')
        
        def save_and_apply():
            new_hotkey = hotkey_var.get()
            if self.settings["hotkey"] != new_hotkey:
                self.settings["hotkey"] = new_hotkey
                messagebox.showinfo("Hotkey Changed", "Restart the app to apply the new hotkey.", parent=self.settings_window)
            self.settings["time_format"] = "12h" if time_format_var.get() else "24h"
            self.settings["show_cpu"] = show_vars["cpu"].get()
            self.settings["show_ram"] = show_vars["ram"].get()
            self.settings["show_temp"] = show_vars["temp"].get()
            self.settings["show_network"] = show_vars["network"].get()
            self.settings["show_battery"] = show_vars["battery"].get()
            self.settings["show_voltage"] = show_vars["voltage"].get()
            self.settings["show_amperage"] = show_vars["amperage"].get()
            self.settings["show_time"] = show_vars["time"].get()
            self.settings["theme"] = theme_var.get()
            self.settings["update_interval"] = float(interval_var.get())
            self.apply_settings()
            self.save_settings()
            self.settings_window.destroy()

        save_button = ttk.Button(self.settings_window, text="Save & Close", command=save_and_apply, style='TButton')
        save_button.pack(pady=(10, 10), padx=20, fill='x')

    def setup_tray_icon(self):
        try: image = Image.open(ICON_PATH)
        except:
            image = Image.new("RGB", (64, 64), "black")
            ImageDraw.Draw(image).text((10, 20), "EC", fill="red")
        menu = (item('Toggle Overlay', self.toggle_overlay), item('Exit', self.quit_app))
        self.icon = Icon("EvlonClient", image, "EvlonClient", menu)
        self.icon.run()

    def setup_hotkey_listener(self):
        self.hotkey_listener = keyboard.GlobalHotKeys({self.settings["hotkey"]: self.toggle_overlay})
        self.hotkey_listener.start()

    def run_tkinter_app(self):
        self.create_windows()

    def quit_app(self):
        if self.hotkey_listener: self.hotkey_listener.stop()
        if self.icon: self.icon.stop()
        if self.root: self.root.quit()

if __name__ == "__main__":
    app = ScreenOverlayApp()
    app.setup_tray_icon()
