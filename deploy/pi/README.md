# On-camera rig: Control Desk on a Raspberry Pi, controlled from a phone

The a7 III cannot run new software itself, so the next best thing is a small
computer on the rig that runs the Desk and a phone that shows it. Nothing on the
camera changes; it still works normally with the Pi unplugged.

## Parts

| Part | Notes |
|---|---|
| Raspberry Pi 5 (4 GB is plenty) or Pi 4 | Pi 5 gives smoother live view |
| microSD card 32 GB, Raspberry Pi OS Bookworm 64-bit | |
| USB-C power bank with Power Delivery, 20 W+ | runs the Pi; the camera keeps its own battery |
| USB-A → USB-C cable (camera ↔ Pi) | the camera's USB-C port |
| Cold-shoe / cage mount or a 1/4" cheese-plate clamp for the Pi case | |
| Optional: NP-FZ100 dummy battery + USB-C power for the camera | for long takes |

## Install

```bash
git clone https://github.com/vikasbanjare/sony-a73 && cd sony-a73
bash deploy/pi/install.sh
```

Then on the camera: **Menu → Setup → USB Connection → PC Remote**, plug it into
the Pi, and turn it on. The Desk service waits for the camera, so order doesn't matter.

## Phone

1. Put the phone on the same Wi-Fi as the Pi, **or** make the Pi a hotspot
   (`install.sh` prints the command) and join it.
2. Open `http://<pi-address>:8000` in Safari.
3. Share → **Add to Home Screen**. It opens full-screen like an app.

## Try it today without a Pi

Run the same thing on the Mac with the camera plugged in:

```bash
a7iii desk --ptp --wait --host 0.0.0.0 --port 8766
```

It prints the address to open on the phone.

## Known limits

- Live view is ~5 fps on a real a7 III (the body's own PTP rate), the same on Mac or Pi.
- If the camera is switched off mid-session, restart the service
  (`sudo systemctl restart a7iii-desk`) or power-cycle; auto-reconnect is not implemented.
- Touch-to-focus can't move the AF point on this body (no 0xD2E4); see `docs/CAMERA_BASELINE.md`.
