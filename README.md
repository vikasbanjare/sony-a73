# a7iii-enhanced-suite

Companion tooling for the **Sony α7 III (ILCE-7M3)**. It implements the R&D roadmap in
[`docs/ROADMAP.md`](docs/ROADMAP.md), and a **virtual α7 III** exercises every feature end to end.

```bash
pip install -e ".[dev]"
```

```bash
a7iii sim --out sim_report
```

`a7iii sim` runs one scenario per roadmap feature and writes `report.md`, `report.json` and
images. Current result: **29 passed, 0 failed, 1 blocked (on purpose), 1 silicon limit.**

```bash
a7iii desk --sim
```

That serves the Control Desk at http://localhost:8000 against the virtual camera.

## The virtual α7 III

`a7iii.sim` renders a procedural 3D scene through a physical model of the camera:

- **Exposure and sensor:** photon shot noise, full well, and IMX410-style **dual conversion gain**. The
  HCG switch at analog ISO 640 lands on S-Log ISO 5000 and HLG3 ISO 800. Pre- and post-amp read noise are modelled.
- **Optics:** per-pixel thin-lens defocus, focus breathing, a stepper focus motor, and a box pixel aperture for super-res.
- **Rolling shutter:** every row is sampled at its own time, so pans and moving subjects skew.
  FF 4K24 reads out in 24.4 ms, S35 in 13.8 ms.
- **AC flicker:** integrated per row over the shutter window.
- **AF behaviour:** PDAF drives straight to the subject. Past f/11 in movie mode it falls back to CDAF, which hunts.
- **Picture profiles:** S-Log2/3, HLG and Rec.709 curves, 8-bit quantisation.
- **A Sony PTP device** (`SimTransport`): the production `SonyCamera` driver runs against it **unmodified**.
- Handheld motion with a BMI270-like IMU, a ground-truth stand-in for YOLO-pose, and a simulated NVRAM body.

## Feature coverage (roadmap §9 and the rest of the document)

| Roadmap feature | Module | Simulation result |
|---|---|---|
| 35-language unlock (NVRAM, Tier 1) | `nvram` + `a7iii nvram` | PASS: 33 flags written and verified, calibration untouched, exact restore |
| 29m59s limit, PAL/NTSC nag | `nvram.registry` | **BLOCKED:** the roadmap gives no property IDs; the tool refuses to guess |
| Picture Profile recipes | `color.profiles` | PASS: grey lands on each recipe's middle-grey level |
| Dual native ISO (DCG) / Cine EI | `cinema.cine_ei`, `ptp.automation` | PASS: HCG ISO beats the ISO below it, EI shifts the monitor by exactly +1 EV |
| HLG3 vs S-Log3 in 8-bit | `color.transfer` | PASS: HLG3 32.9 codes/stop vs S-Log3 18.4 |
| FX3 colour match, ΔE2000 + OKLab RBF → 65³ LUT + DCTL | `color` | PASS: ΔE 2.0 → 0.02 in the sim (see notes) |
| 4:2:0 → float 4:4:4 + dither | `color.chroma` | PASS: chroma RMSE 5.6× lower than nearest-neighbour |
| AI subject AF → PTP Touch-AF | `af`, `ptp.automation.PtpAFSink` | PASS: 100% of frames in focus vs 0% for a fixed AF point |
| f/11 PDAF guard, hunting prevention | `optics.af_guard`, `ptp.automation.ApertureGuard` | PASS |
| Focus bracketing + stacking | `ptp.automation.focus_bracket`, `stills.focus_stack` | PASS: 99.8% of the frame sharp vs 16% for the best single slice |
| Bézier rack focus | `optics.rack_focus`, `ptp.automation.rack_focus` | PASS |
| 180° shutter lock + 50/60 Hz anti-flicker | `cinema.shutter` | PASS: 0% banding when locked, 7% when unlocked |
| EL-Zone false colour, waveform, vectorscope | `cinema.false_color`, `cinema.scopes` | PASS |
| GyroShoe IMU + Gyroflow stabilisation | `firmware/gyroshoe`, `optics.gyro`, `optics.stabilize` | PASS: 2.8 ms sync error, jitter 10.8× lower |
| Rolling-shutter FF vs S35 | `optics.rolling_shutter` | PASS: measured ratio 0.51 vs 0.57 expected |
| Focus-breathing compensation | `optics.breathing` | PASS: size spread 3.9% → 0.24% |
| Focus map (DoF visualiser) | `optics.focus_map` | PASS |
| Anamorphic de-squeeze + guides | `cinema.framing` | PASS |
| Pre-capture ring buffer → ProRes | `cinema.ring_buffer`, `desk`, `media` | PASS |
| SMPTE LTC generator / jam-sync | `audio.ltc`, `audio.timecode` | PASS: frame-exact video TC from camera audio |
| 4-channel audio, BWF timecode, safety track | `audio.multitrack` | PASS |
| Handheld super-resolution | `stills.superres` | PASS: +5.8 dB over single-frame upscaling |
| Noise / astro stacking | `stills.stack` | PASS: 3.6× SNR from 16 frames |
| Pre-capture burst (stills) | `stills.burst_trigger` | PASS |
| Verified offload + proxies | `ingest`, `media` | PASS |
| Cloud sync (takes, presets, LUTs, NVRAM backups) | `cloud` | PASS |
| A7III Control Desk (UI + backend) | `desk` | PASS, and checked in headless Chromium |
| Internal 10-bit, 4K60, HDMI RAW | n/a | **LIMIT:** Tier 4 silicon limit, not attempted |

## Command line

| Command | What it does |
|---|---|
| `a7iii sim [--only k1,k2] [--list]` | end-to-end simulation report |
| `a7iii desk --sim` / `--uvc 0 --ptp` | Control Desk on the simulator, or on HDMI capture + USB PTP |
| `a7iii cloud --db sync.sqlite --token …` | cloud sync API |
| `a7iii shutter --fps 23.976 --mains 50` | shutter-angle lock with anti-flicker |
| `a7iii iso slog3 --need 3200` / `a7iii ei slog3 1600` | native ISOs and Cine EI offset |
| `a7iii dof …` / `a7iii bracket …` | depth of field and focus-stack plans |
| `a7iii ptp-check [--write --capture --record]` | what the connected camera accepts over USB; writes are read back and restored |
| `a7iii luts --out luts` | FX-style LUT pack: S-Log3 / S-Log2 / HLG → Rec.709, technical / cinetone / portrait (33 + 65 pt) and the ten FX3 Creative Look-alikes (33 pt), each with a DCTL |
| `a7iii chart-sample CLIP --corners …` | read a ColorChecker into a CSV; then `a7iii match --target colorchecker` calibrates without a reference camera |
| `a7iii match --source … --target …` | chart CSVs → `.cube` + DCTL |
| `a7iii offload CARD SSD_A SSD_B --proxies PROXIES` | verified copy, then proxies with the FX-style `fxdefault` look baked in (`--look slog3:cinetone`, `--look none`, …) |
| `a7iii nvram tweaks\|dump\|apply\|restore\|verify --sim IMAGE` | guarded NVRAM tool, rehearsed on a simulated body |
| `a7iii profiles`, `a7iii readout`, `a7iii af-guard 13` | reference data and checks |

## Hardware status, honestly

- **PTP over USB** (`UsbTransport`) is confirmed on a real ILCE-7M3 (firmware 4.04): handshake, 61 property
  codes, live view, white balance, step-controlled shutter/ISO/aperture, focus steps, stills and movie record
  (`a7iii ptp-check`). The body does **not** report Touch-AF `0xD2E4`.
  See `docs/CAMERA_BASELINE.md`, and `docs/FX_FEATURE_MATRIX.md` for what each FX3/FX6 feature becomes here.
- **NVRAM:** there is no hardware Senser backend, on purpose. The safety layer is complete and tested.
- **GyroShoe firmware** is compiled in CI against API stubs, which checks syntax and types but not
  on-device behaviour. Verify it on the board (see `firmware/gyroshoe/README.md`).
- **YOLO-pose** is wired in through an optional `ultralytics` adapter. The simulator uses a ground-truth detector instead.
- **HDMI capture** goes through OpenCV/UVC (`pip install '.[capture]'`).

## Deploy

```bash
docker compose up
```

That starts the desk (simulated camera) on :8000 and the cloud API on :8080. Real hardware is easier
to run natively than in containers.
