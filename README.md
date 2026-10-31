# a7iii-enhanced-suite

Companion tooling for the **Sony α7 III (ILCE-7M3)**. It's built from the R&D roadmap in
[`docs/ROADMAP.md`](docs/ROADMAP.md). Read [`docs/ROADMAP_REVIEW.md`](docs/ROADMAP_REVIEW.md)
for the places where the code intentionally differs from the roadmap.

This first milestone covers the parts that don't need hardware: the math, the protocol
encoding and the safety layers. Everything is unit-tested.

| Package | Roadmap | What's in it |
|---|---|---|
| `a7iii.color` | §4, packages/04 | S-Log2/S-Log3/HLG/Rec.709 transfer functions, CIEDE2000, a weighted ΔE2000 chart-matching CCM solver (root-polynomial), OKLab thin-plate-RBF residual stage, `.cube` LUT read/write/apply, DCTL export, a luma-guided 4:2:0 → float 4:4:4 chroma upsampler with TPDF dither, picture-profile recipes, native dual-gain ISOs |
| `a7iii.cinema` | §7, §10.3 | Shutter-angle lock with flicker-safe snapping, Cine EI, stop-based false colour, pre-roll ring buffer |
| `a7iii.optics` | §5, §6, §8 | DoF/hyperfocal, focus-bracketing plans, Bézier rack-focus schedules, focus-breathing fit and compensation, f/11 PDAF guard, rolling-shutter readout table, Gyroflow `.gcsv` writer/reader with BMI270 scales, IMU↔video offset estimation |
| `a7iii.af` | §5, packages/03 | AI-AF bridge: eye → head → torso → box focus priority, subject lock, Kalman latency lookahead, letterbox/pillarbox mapping, a rate-limited and dead-banded controller that stops steering past f/11, and an optional YOLO-pose + ByteTrack adapter |
| `a7iii.ingest` | Phase 5 | Verified multi-destination card offload: single read, temp file + atomic rename, hash verified after writing, resumable, conflict-safe, with a JSON manifest |
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

Other commands: `iso`, `ei`, `dof`, `bracket`, `af-guard`, `profiles`, `readout`,
`match` (chart CSVs → `.cube` + DCTL) and `offload` (verified card copy). Run `a7iii -h` for details.

```bash
a7iii match --source a7iii_patches.csv --source-curve hlg --target fx3_patches.csv --target-curve slog3 --out a7iii_to_fx3.cube
```

```bash
a7iii offload /media/SONY_CARD /mnt/ssd_a /mnt/ssd_b
```

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

- **AI-AF**: `AFController` sends image-normalised points to any `sink(u, v)` callable.
  The PTP Touch-AF sink isn't wired up yet because the property encoding is unverified.
  Until then you can test it with a logging sink, or point it at an external focus motor.

## Not built yet

- HDMI capture and the Control Desk UI (FastAPI + WebGL scopes, de-squeeze)
- The PTP Touch-AF sink, which is waiting on hardware verification
- GyroShoe ESP32 firmware (needs hardware to build and test)
- Cloud sync API
