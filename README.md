# Pi Studio Display

Power on/off an Apple Studio Display 17" CRT (M7768) from a Raspberry Pi using a Jason "Does It All" ADC adapter.

The Apple Studio Display uses Apple's proprietary ADC connector. The Jason adapter converts DVI and VGA to ADC, letting you use modern video sources. But the monitor has no software power control — and the physical power button doesn't work either, since ADC monitors rely on the host computer (originally a Mac) to manage power.

This project fixes that with 4 wires and a shell script.

## How it works (ELI5)

The monitor has two communication paths through the Jason adapter, and each one can do something the other can't:

**USB** lets you *ask* the monitor if it's on or off, but it **won't let you flip the switch**. Apple made the power state read-only over USB. You can read settings, adjust geometry, degauss the tube — but power control? Nope.

**DDC/CI over the DVI pins** is a side entrance. Pins 6 and 7 on the DVI connector carry a simple I2C data bus that the monitor's controller listens on. Through this path, the monitor **will** accept a "change power state" command. But it won't tell you its current state — read requests come back empty.

So the toggle script does this:

1. "Hey monitor, are you on or off?" — asked over **USB**
2. "Turn on!" or "Turn off!" — sent over **4 GPIO wires into the DVI pins**

Both paths go through the Jason adapter. Both needed, doing different jobs.

## What you need

- Raspberry Pi (tested on Pi 2B, any Pi with I2C GPIO should work)
- Jason "Does It All" ADC adapter
- Apple Studio Display 17" CRT (M7768)
- 4 jumper wires (female-to-whatever fits your DVI connector)
- A video source into the Jason adapter's VGA port (e.g., Pi HDMI out through an HDMI-to-VGA adapter)

## Wiring

Four wires from the Pi's GPIO header to the DVI female port on the Jason adapter:

| Wire | Pi Pin | Pi Function | DVI Pin | DVI Function |
|------|--------|-------------|---------|--------------|
| Blue | Pin 2 | 5V | Pin 14 | +5V Power |
| Yellow | Pin 3 | SDA1 | Pin 7 | DDC Data |
| White | Pin 5 | SCL1 | Pin 6 | DDC Clock |
| Black | Pin 9 | GND | Pin 15 | DDC Ground |

All four DVI pins sit in a 2x2 cluster — easy to find:

```
        DVI-I Female — front face
        ─────────────────────────────────────────
 Row 1:  1    2    3    4    5   [6]  [7]   8
                                 WHT  YEL
                                 SCL  SDA

 Row 2:  9   10   11   12   13  [14] [15]  16
                                 BLU  BLK
                                 5V   GND

 Row 3: 17   18   19   20   21   22   23   24

                                        ┌──────┐
 Blade:                                 │C1─C5 │
                                        └──────┘
```

### Why 5V on pin 14?

DDC is a 5V bus. The Pi's I2C GPIOs are 3.3V. The monitor didn't recognize 3.3V pullups, so we supply 5V on DVI pin 14. The monitor's internal DDC pullups then pull SDA/SCL up to 5V. The Pi's GPIOs are open-drain (they only pull low, never drive high), so this works — though it's technically out of spec for the Pi's 3.3V inputs. A BSS138 level shifter is the proper fix if you care about longevity.

## Setup

### 1. Enable I2C on the Pi

```bash
sudo apt update && sudo apt install -y i2c-tools
sudo raspi-config nonint do_i2c 0
echo i2c-dev | sudo tee -a /etc/modules
sudo reboot
```

### 2. Build and install usbmonctl

[usbmonctl](https://github.com/OndrejZary/usbmonctl) is used to read the monitor's power state over USB.

```bash
sudo apt install -y gcc make
git clone https://github.com/OndrejZary/usbmonctl.git
cd usbmonctl
make
sudo cp usbmonctl /usr/local/bin/
```

### 3. Install the toggle script

```bash
sudo cp crt-toggle /usr/local/bin/crt-toggle
sudo chmod +x /usr/local/bin/crt-toggle
```

### 4. Verify wiring

```bash
sudo i2cdetect -y 1
```

You should see `37` (DDC/CI controller) and `50` (EDID EEPROM) in the grid. If not, check your wiring.

### 5. Toggle the monitor

```bash
sudo crt-toggle
```

## Manual commands

Power on:
```bash
i2ctransfer -y 1 w7@0x37 0x51 0x84 0x03 0xD6 0x00 0x01 0x6F
```

Power off:
```bash
i2ctransfer -y 1 w7@0x37 0x51 0x84 0x03 0xD6 0x00 0x04 0x6A
```

Read current state (via USB):
```bash
sudo usbmonctl -g F,0xD6
```
Returns `1` (on), `2` (sleep), or `4` (off).

## DDC/CI command breakdown

The power commands are standard DDC/CI SET VCP Feature frames sent over I2C to address `0x37`:

| Byte | Value (on / off) | Meaning |
|------|-------------------|---------|
| 1 | `0x51` | Source address (host) |
| 2 | `0x84` | Length: `0x80` flag + 4 data bytes |
| 3 | `0x03` | Opcode: Set VCP Feature |
| 4 | `0xD6` | VCP code: power state |
| 5 | `0x00` | Value high byte |
| 6 | `0x01` / `0x04` | Value low byte (1=on, 4=off) |
| 7 | `0x6F` / `0x6A` | XOR checksum |

## Video setup

The DVI port on the Jason adapter is occupied by the I2C power control wires, so video goes in through the VGA port. Use an HDMI-to-VGA adapter (like a powered Tripp-Lite) from the Pi's HDMI output, or any other VGA source.

## Credits

- [Jason "Does It All" ADC adapter](https://jasondoesitall.com) — makes the whole thing possible
- [usbmonctl](https://github.com/OndrejZary/usbmonctl) by Ondrej Zary — USB HID monitor control for Linux
- [monitorcontrol](https://github.com/newAM/monitorcontrol) by newAM — Python DDC/CI library (reference for the I2C protocol)
- [GUI-for-apple-studio-17-ADC](https://github.com/mega-calibrator/GUI-for-apple-studio-17-ADC) by mega-calibrator — Windows GUI that inspired this project
