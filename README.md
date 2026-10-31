# a7iii-enhanced-suite

Companion tooling for the **Sony α7 III (ILCE-7M3)**. It's built from the R&D roadmap in
[`docs/ROADMAP.md`](docs/ROADMAP.md). Read [`docs/ROADMAP_REVIEW.md`](docs/ROADMAP_REVIEW.md)
for the places where the code intentionally differs from the roadmap.

This first milestone covers the parts that don't need hardware: the math, the protocol
encoding and the safety layers. Everything is unit-tested.

| Package | Roadmap | What's in it |
|---|---|---|
| `a7iii.color` | §4, packages/04 | S-Log2/S-Log3/HLG/Rec.709 transfer functions, CIEDE2000, a weighted ΔE2000 chart-matching CCM solver (root-polynomial), `.cube` LUT read/write/apply, picture-profile recipes, native dual-gain ISOs |
| `a7iii.cinema` | §7, §10.3 | Shutter-angle lock with flicker-safe snapping, Cine EI, stop-based false colour, pre-roll ring buffer |
| `a7iii.optics` | §5, §6, §8 | DoF/hyperfocal, focus-bracketing plans, Bézier rack-focus schedules, focus-breathing fit and compensation, f/11 PDAF guard, rolling-shutter readout table |
| `a7iii.ptp` | §10.2, packages/02 | PTP container codec, Sony SDIO handshake, property and button control, live-view JPEG extraction, a pyusb transport and a mock transport |
| `a7iii.nvram` | §3, packages/01 | **Deny-by-default** NVRAM write gate, SHA-256-sealed backups, a guarded apply/restore session that runs behind an abstract Senser backend |

## Quick start

```bash
pip install -e ".[dev]"
```

```bash
pytest -q
```

```bash
a7iii shutter --fps 23.976 --angle 180 --mains 50
```

Other commands: `iso`, `ei`, `dof`, `bracket`, `af-guard`, `profiles` and `readout`. Run `a7iii -h` for details.

## Hardware status

- **PTP** (`UsbTransport` + `SonyCamera`): implemented, but tested only against the mock
  transport. To try it on a camera, set *Setup → USB Connection: PC Remote*, install
  `pip install -e ".[usb]"`, then:

  ```python
  from a7iii.ptp import SonyCamera, UsbTransport
  cam = SonyCamera(UsbTransport())
  print([hex(c) for c in cam.connect()])   # supported property codes
  ```

- **NVRAM**: there's no USB backend on purpose. Only the language bitmap is writable,
  and only after you take a matching backup. Writes are dry-run by default.
  The record-limit and PAL/NTSC tweaks stay locked until a verified property ID is added
  to `nvram/registry.py`. Never write factory calibration areas.

## Not built yet

These are later roadmap phases:
- AI-AF engine (YOLO + ByteTrack → PTP)
- HDMI capture and the Control Desk UI (FastAPI + WebGL)
- GyroShoe ESP32 firmware
- RBF/OKLab stage-2 LUT refinement
- Chroma upsampler
- Cloud sync
