"""Shared backend for Apple Studio Display 17" CRT (M7768) control.

Provides functions for USB HID control (via usbmonctl) and DDC/CI power
control (via i2ctransfer). Used by pi-adc-gui.py, crt-daemon, and crt-tray.
"""

import os
import re
import struct
import subprocess

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONTROLS = [
    # (code, label, max_value)
    (0x12, "Contrast", 96),
    (0x20, "H Phase", 96),
    (0x22, "H Size", 96),
    (0x30, "V Phase", 96),
    (0x32, "V Size", 96),
    (0x24, "H Pincushion", 96),
    (0x42, "H Keystone", 96),
    (0x40, "H Key Balance", 96),
    (0x44, "Rotation", 255),
    (0x28, "H Stat Conv", 255),
    (0x38, "V Stat Conv", 255),
]

FACTORY_DEFAULTS = {
    0x12: 95, 0x20: 64, 0x22: 70, 0x30: 68, 0x32: 67,
    0x24: 63, 0x42: 54, 0x40: 77, 0x44: 152, 0x28: 127, 0x38: 127,
}

I2C_BUS = 1
DDCCI_ADDR = 0x37
POWER_ON_CMD = [0x51, 0x84, 0x03, 0xD6, 0x00, 0x01, 0x6F]
POWER_OFF_CMD = [0x51, 0x84, 0x03, 0xD6, 0x00, 0x04, 0x6A]

BRIGHTNESS_CODE = 0x12
BRIGHTNESS_STEP = 19  # 5 presses from 0 to max
BUTTON_USAGE_E4 = 0x00E4

# ---------------------------------------------------------------------------
# Device discovery
# ---------------------------------------------------------------------------

def find_device():
    """Find the hiddev path for the Apple Studio Display (0x05ac:0x9213)."""
    try:
        result = subprocess.run(
            ["usbmonctl", "-l"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if "0x05ac:0x9213" in line:
                paths = re.findall(r"(/dev/\S+?):", line)
                if paths:
                    return paths[-1]
    except Exception:
        pass
    return None

# ---------------------------------------------------------------------------
# USB HID control (via usbmonctl)
# ---------------------------------------------------------------------------

def _run_usbmonctl(args, device):
    """Run usbmonctl with the given args and device path."""
    cmd = ["usbmonctl"] + args
    if device:
        cmd.append(device)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=5)


def read_control(code, device):
    """Read a FEATURE control value. Returns int or None on failure."""
    result = _run_usbmonctl(["-g", f"F,0x{code:02x}"], device)
    if result.returncode == 0 and result.stdout.strip():
        match = re.match(r"(\d+)", result.stdout.strip())
        if match:
            return int(match.group(1))
    return None


def write_control(code, value, device):
    """Write a FEATURE control value."""
    _run_usbmonctl(["-s", f"F,0x{code:02x}={value}"], device)


def degauss(device):
    """Trigger degauss."""
    _run_usbmonctl(["-s", "F,0x01=1"], device)


def apply_settings(device):
    """Save current settings to NVRAM (0xB0 = 1)."""
    _run_usbmonctl(["-s", "F,0xB0=1"], device)


def read_vsync(device):
    """Read vertical refresh rate. Returns Hz as float, or None."""
    val = read_control(0xAE, device)
    if val is not None:
        return val / 100.0
    return None


def read_power(device):
    """Read power state: 1=on, 2=sleep, 4=off."""
    return read_control(0xD6, device)

# ---------------------------------------------------------------------------
# DDC/CI power control (via i2ctransfer)
# ---------------------------------------------------------------------------

def set_power(on):
    """Set power via DDC/CI over I2C."""
    cmd_bytes = POWER_ON_CMD if on else POWER_OFF_CMD
    args = ["i2ctransfer", "-y", str(I2C_BUS),
            f"w{len(cmd_bytes)}@0x{DDCCI_ADDR:02x}"]
    args += [f"0x{b:02x}" for b in cmd_bytes]
    subprocess.run(args, capture_output=True, timeout=5)


def toggle_power(device):
    """Read current power state and toggle it. Returns new state."""
    state = read_power(device)
    if state == 1:
        set_power(False)
        return 4
    else:
        set_power(True)
        return 1

# ---------------------------------------------------------------------------
# Button listener
# ---------------------------------------------------------------------------

def listen_buttons(device, callback):
    """Block and listen for button presses. Calls callback(usage, value) for each.

    This function never returns — run it in a thread or as the main loop of a daemon.
    """
    fd = os.open(device, os.O_RDONLY)
    try:
        while True:
            data = os.read(fd, 8)
            if len(data) == 8:
                hid, val = struct.unpack("ii", data)
                usage = hid & 0xFFFF
                callback(usage, val)
    finally:
        os.close(fd)
