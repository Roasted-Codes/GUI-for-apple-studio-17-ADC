#!/usr/bin/env python3
"""GTK3 GUI for Apple Studio Display 17" CRT (M7768) geometry control.

Must run as root: sudo python3 pi-adc-gui.py
"""

import os
import signal
import sys
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

# Allow importing crt_backend from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crt_backend import (
    CONTROLS, FACTORY_DEFAULTS, BRIGHTNESS_CODE,
    find_device, read_control, write_control, degauss, apply_settings,
    read_vsync, read_power, set_power,
)


class ADCControlApp(Gtk.Window):
    def __init__(self, device):
        super().__init__(title="ADC CRT Control")
        self.device = device
        self.adjustments = {}
        self.scales = {}
        self.vsync_label = None
        self.power_switch = None
        self.power_box = None
        self.countdown_label = None
        self.cancel_button = None
        self._poweroff_timer = None
        self._poweroff_countdown = 0
        self.status_label = None
        self._writing = set()
        self._updating_power = False

        self.set_border_width(8)
        self.connect("destroy", Gtk.main_quit)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add(vbox)

        # --- Geometry controls ---
        geo_frame = Gtk.Frame(label="Geometry")
        geo_frame.set_margin_bottom(4)
        vbox.pack_start(geo_frame, True, True, 0)

        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(4)
        grid.set_margin_start(8)
        grid.set_margin_end(8)
        grid.set_margin_top(8)
        grid.set_margin_bottom(8)
        geo_frame.add(grid)

        for i, (code, label, max_val) in enumerate(CONTROLS):
            lbl = Gtk.Label(label=label, xalign=0)
            lbl.set_width_chars(14)
            grid.attach(lbl, 0, i, 1, 1)

            adj = Gtk.Adjustment(value=0, lower=0, upper=max_val,
                                 step_increment=1, page_increment=10)
            self.adjustments[code] = adj

            spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=0)
            spin.set_width_chars(4)
            spin.connect("value-changed", self._on_spin_changed, code)
            grid.attach(spin, 1, i, 1, 1)

            scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
            scale.set_draw_value(False)
            scale.set_hexpand(True)
            scale.set_size_request(200, -1)
            scale.connect("button-release-event", self._on_scale_release, code)
            self.scales[code] = scale
            grid.attach(scale, 2, i, 1, 1)

        # --- Button bar ---
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        btn_box.set_margin_bottom(4)
        vbox.pack_start(btn_box, False, False, 0)

        self.vsync_label = Gtk.Label(label="V. Rate: -- Hz")
        self.vsync_label.set_margin_end(12)
        btn_box.pack_start(self.vsync_label, False, False, 4)

        for label, callback in [("Degauss", self._degauss),
                                ("Read", self._read_all),
                                ("Write", self._apply),
                                ("Defaults", self._defaults)]:
            btn = Gtk.Button(label=label)
            btn.connect("clicked", callback)
            btn_box.pack_start(btn, False, False, 2)

        # --- Power ---
        pwr_frame = Gtk.Frame(label="Power")
        pwr_frame.set_margin_bottom(4)
        vbox.pack_start(pwr_frame, False, False, 0)

        self.power_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.power_box.set_margin_start(8)
        self.power_box.set_margin_top(4)
        self.power_box.set_margin_bottom(4)
        pwr_frame.add(self.power_box)

        self.power_switch = Gtk.Switch()
        self.power_switch.connect("state-set", self._on_power_toggled)
        self.power_box.pack_start(self.power_switch, False, False, 0)

        self.countdown_label = Gtk.Label()
        self.power_box.pack_start(self.countdown_label, False, False, 0)

        self.cancel_button = Gtk.Button(label="Cancel")
        self.cancel_button.connect("clicked", self._cancel_poweroff)
        self.power_box.pack_start(self.cancel_button, False, False, 0)

        # --- Status bar ---
        self.status_label = Gtk.Label(label="", xalign=0)
        vbox.pack_start(self.status_label, False, False, 0)

        self.show_all()
        self.countdown_label.hide()
        self.cancel_button.hide()
        self._read_all(None)
        self._install_signal_handler()

    def _install_signal_handler(self):
        """Listen for SIGUSR1 from crt-tray to refresh the contrast slider."""
        def on_signal(*_args):
            self._refresh_contrast()
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, on_signal)

    def _refresh_contrast(self):
        def do_read():
            val = read_control(BRIGHTNESS_CODE, self.device)
            if val is not None:
                def update_ui():
                    self._writing.add(BRIGHTNESS_CODE)
                    self.adjustments[BRIGHTNESS_CODE].set_value(val)
                    self._writing.discard(BRIGHTNESS_CODE)
                    return False
                GLib.idle_add(update_ui)
            return False
        threading.Thread(target=do_read, daemon=True).start()
        return True

    def _set_status(self, text):
        GLib.idle_add(self.status_label.set_text, text)

    def _on_spin_changed(self, spin, code):
        if code in self._writing:
            return
        value = int(spin.get_value())
        self._set_status(f"Setting 0x{code:02X} = {value}...")
        threading.Thread(target=self._write_value, args=(code, value), daemon=True).start()

    def _on_scale_release(self, scale, event, code):
        value = int(self.adjustments[code].get_value())
        self._set_status(f"Setting 0x{code:02X} = {value}...")
        threading.Thread(target=self._write_value, args=(code, value), daemon=True).start()
        return False

    def _write_value(self, code, value):
        try:
            write_control(code, value, self.device)
            self._set_status("")
        except Exception as e:
            self._set_status(f"Error: {e}")

    def _read_all(self, _widget):
        self._set_status("Reading values from monitor...")

        def do_read():
            values = {}
            for code, _, _ in CONTROLS:
                val = read_control(code, self.device)
                if val is not None:
                    values[code] = val
            vsync = read_vsync(self.device)
            power = read_power(self.device)

            def update_ui():
                for code, val in values.items():
                    if code in self.adjustments:
                        self._writing.add(code)
                        self.adjustments[code].set_value(val)
                        self._writing.discard(code)
                if vsync is not None:
                    self.vsync_label.set_text(f"V. Rate: {vsync:.1f} Hz")
                if power is not None:
                    self._updating_power = True
                    self.power_switch.set_active(power == 1)
                    self._updating_power = False
                self.status_label.set_text("")
                return False

            GLib.idle_add(update_ui)

        threading.Thread(target=do_read, daemon=True).start()

    def _degauss(self, _widget):
        self._set_status("Degaussing...")
        def do_it():
            try:
                degauss(self.device)
                self._set_status("")
            except Exception as e:
                self._set_status(f"Error: {e}")
        threading.Thread(target=do_it, daemon=True).start()

    def _defaults(self, _widget):
        self._set_status("Restoring defaults...")
        def do_it():
            for code, val in FACTORY_DEFAULTS.items():
                write_control(code, val, self.device)
            def update_ui():
                for code, val in FACTORY_DEFAULTS.items():
                    if code in self.adjustments:
                        self._writing.add(code)
                        self.adjustments[code].set_value(val)
                        self._writing.discard(code)
                self.status_label.set_text("Defaults restored.")
                return False
            GLib.idle_add(update_ui)
        threading.Thread(target=do_it, daemon=True).start()

    def _apply(self, _widget):
        self._set_status("Saving settings to NVRAM...")
        def do_it():
            try:
                apply_settings(self.device)
                self._set_status("Settings saved.")
            except Exception as e:
                self._set_status(f"Error: {e}")
        threading.Thread(target=do_it, daemon=True).start()

    def _on_power_toggled(self, switch, on):
        if self._updating_power:
            return
        if on:
            self._cancel_poweroff(None)
            self._set_status("Powering on...")
            def do_it():
                try:
                    set_power(True)
                    self._set_status("")
                except Exception as e:
                    self._set_status(f"Error: {e}")
            threading.Thread(target=do_it, daemon=True).start()
        else:
            self._start_poweroff_countdown()

    def _start_poweroff_countdown(self):
        self._poweroff_countdown = 5
        self.countdown_label.set_text(f"Powering off in {self._poweroff_countdown}s — Ctrl+Alt+P to restore")
        self.countdown_label.show()
        self.cancel_button.show()
        self._poweroff_timer = GLib.timeout_add(1000, self._poweroff_tick)

    def _poweroff_tick(self):
        self._poweroff_countdown -= 1
        if self._poweroff_countdown <= 0:
            self.countdown_label.hide()
            self.cancel_button.hide()
            self._poweroff_timer = None
            self._set_status("Powering off...")
            def do_it():
                try:
                    set_power(False)
                    self._set_status("")
                except Exception as e:
                    self._set_status(f"Error: {e}")
            threading.Thread(target=do_it, daemon=True).start()
            return False
        self.countdown_label.set_text(f"Powering off in {self._poweroff_countdown}s — Ctrl+Alt+P to restore")
        return True

    def _cancel_poweroff(self, _widget):
        if self._poweroff_timer is not None:
            GLib.source_remove(self._poweroff_timer)
            self._poweroff_timer = None
        self.countdown_label.hide()
        self.cancel_button.hide()
        self._updating_power = True
        self.power_switch.set_active(True)
        self._updating_power = False
        self._set_status("")


def main():
    # Exit cleanly on SIGTERM (sent by crt-buttons to close the GUI)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM,
                         lambda: Gtk.main_quit() or True)

    if os.geteuid() != 0:
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Must run as root.\nUse: sudo python3 pi-adc-gui.py")
        dialog.run()
        dialog.destroy()
        return

    device = find_device()
    if not device:
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Apple Studio Display not found.\n"
                 "Check USB connection to the Jason adapter.")
        dialog.run()
        dialog.destroy()
        return

    ADCControlApp(device)
    Gtk.main()


if __name__ == "__main__":
    main()
