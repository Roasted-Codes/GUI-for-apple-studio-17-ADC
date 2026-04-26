#!/usr/bin/env python3
"""GTK3 GUI for Apple Studio Display 17" CRT (M7768) geometry control.

Must run as root: sudo python3 pi-adc-gui.py
"""

import os
import sys
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

# Allow importing crt_backend from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crt_backend import (
    CONTROLS, FACTORY_DEFAULTS, BUTTON_USAGE_E4, BRIGHTNESS_CODE, BRIGHTNESS_STEP,
    find_device, read_control, write_control, degauss, apply_settings,
    read_vsync, read_power, set_power, listen_buttons,
)


class ADCControlApp(Gtk.Window):
    def __init__(self, device):
        super().__init__(title="ADC CRT Control")
        self.device = device
        self.adjustments = {}
        self.scales = {}
        self.vsync_label = None
        self.power_on_radio = None
        self.power_off_radio = None
        self.status_label = None
        self._writing = set()

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

        pwr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        pwr_box.set_margin_start(8)
        pwr_box.set_margin_top(4)
        pwr_box.set_margin_bottom(4)
        pwr_frame.add(pwr_box)

        self.power_on_radio = Gtk.RadioButton.new_with_label(None, "On")
        self.power_on_radio.connect("toggled", self._on_power_toggled, True)
        pwr_box.pack_start(self.power_on_radio, False, False, 0)

        self.power_off_radio = Gtk.RadioButton.new_with_label_from_widget(
            self.power_on_radio, "Off")
        pwr_box.pack_start(self.power_off_radio, False, False, 0)

        # --- Status bar ---
        self.status_label = Gtk.Label(label="", xalign=0)
        vbox.pack_start(self.status_label, False, False, 0)

        self.show_all()
        self._read_all(None)
        self._start_button_listener()

    def _set_status(self, text):
        GLib.idle_add(self.status_label.set_text, text)

    def _start_button_listener(self):
        def on_button(usage, value):
            if usage == BUTTON_USAGE_E4:
                self._on_brightness_button()

        def listen():
            try:
                listen_buttons(self.device, on_button)
            except OSError:
                pass

        threading.Thread(target=listen, daemon=True).start()

    def _on_brightness_button(self):
        current = int(self.adjustments[BRIGHTNESS_CODE].get_value())
        new_val = current + BRIGHTNESS_STEP
        if new_val > 96:
            new_val = 0

        def update_ui():
            self._writing.add(BRIGHTNESS_CODE)
            self.adjustments[BRIGHTNESS_CODE].set_value(new_val)
            self._writing.discard(BRIGHTNESS_CODE)
            self.status_label.set_text(f"Brightness: {new_val}")
            return False

        write_control(BRIGHTNESS_CODE, new_val, self.device)
        GLib.idle_add(update_ui)

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
                    if power == 1:
                        self.power_on_radio.set_active(True)
                    else:
                        self.power_off_radio.set_active(True)
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

    def _on_power_toggled(self, radio, on):
        if not radio.get_active():
            return
        self._set_status("Powering on..." if on else "Powering off...")
        def do_it():
            try:
                set_power(on)
                self._set_status("")
            except Exception as e:
                self._set_status(f"Error: {e}")
        threading.Thread(target=do_it, daemon=True).start()


def main():
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
