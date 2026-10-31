#!/usr/bin/env bash
# Set up a Raspberry Pi (OS Bookworm, 64-bit) as the a7 III rig computer.
# Run once as the normal user:  bash deploy/pi/install.sh
# Afterwards the Desk starts at boot, waits for the camera (USB, PC Remote) and
# serves http://<pi>:8000 to any phone on the same network / the Pi's hotspot.
set -euo pipefail
cd "$(dirname "$0")/../.."

sudo apt-get update
sudo apt-get install -y --no-install-recommends python3-venv libusb-1.0-0 ffmpeg network-manager

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[desk,usb]"

# let the service talk to the camera without root
sudo install -m 644 deploy/pi/99-sony-camera.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger

# start the Desk at boot and restart it if it ever dies
sed "s|__REPO__|$PWD|g; s|__USER__|$USER|g" deploy/pi/a7iii-desk.service | sudo tee /etc/systemd/system/a7iii-desk.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now a7iii-desk

echo
echo "Desk service: $(systemctl is-active a7iii-desk).  Logs: journalctl -u a7iii-desk -f"
echo "Optional hotspot (no router needed on location):"
echo "  sudo nmcli dev wifi hotspot ifname wlan0 ssid A7III-Rig password <8+ chars>"
echo "then join A7III-Rig on the phone and open http://10.42.0.1:8000"
