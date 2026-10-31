# Roadmap review notes

I checked `ROADMAP.md` against public references while implementing it. Where the
code does something different from the roadmap, it's listed here so nobody
"fixes" the code back.

## Corrections applied in code

| Roadmap claim | What the code does | Why |
|---|---|---|
| §10.2: `0x9205` executes button actions, `0x9207` sets property values | Swapped: `0x9205` = `SetControlDeviceA` (property values), `0x9207` = `SetControlDeviceB` (buttons such as half-press `0xD2C1`, release `0xD2C2`, record `0xD2C8`) | Matches libgphoto2's Sony driver, the most widely used open implementation. Confirm against hardware. |
| §10.3A: snap exposure to `k / (2 f_mains)` and then pick the nearest Sony speed | Only flicker-free speeds that **actually exist** on the a7 III are considered | The a7 III has no variable shutter. Under 60 Hz, 1/120 doesn't exist, so a 180° shutter at 24p becomes **1/40** (3 flicker periods, 216°), not 1/50. 1/50 flickers under 60 Hz. |
| §8.1: focus bracketing step `Δd ∝ N·c·d²/f²` | Exact thin-lens chaining: each shot's near DoF limit sits on the previous shot's far limit, with configurable overlap | Same scaling, but the result is exact and you can verify the coverage. |
| §4.1: HLG formula `E' = r√E` (ARIB form, E up to 12) | BT.2100 form `E' = √(3E)` with E normalised to [0,1]; reflectance is scaled so that diffuse white encodes at 75% | The two forms are equivalent; BT.2100 is the current standard and makes 18% grey come out at ~38%. |
| §3.3: record-limit and PAL/NTSC flags are "GREEN" toggles | Registered, but **unwritable** (no property ID) | The roadmap gives no property IDs for them. Guessing NVRAM IDs on a real camera is how bodies get bricked. Add a verified ID in a reviewed change to enable them. |

## Claims that still need checking on hardware

- **PTP property `0xD2E4` (Touch AF position)** and its coordinate encoding are marked `verified=False` in `ptp/codes.py`. The AI-AF bridge depends on this, so run `GetExtDeviceInfo` on the body first and see if the code is listed.
- **Live-view header layout** (§10.2): the parser deliberately finds the JPEG by its SOI/EOI markers and doesn't trust fixed offsets. The focus-frame (`0x02`) payload isn't parsed yet.
- **Rolling-shutter readout times** (§6.1) and **dual-gain ISOs** (§2.2) are typical published figures, not per-body calibration. Measure your own camera.
- **Senser service mode on FW 4.04** (§3): the roadmap cites Sony-PMCA-RE issues #724/#733/#744/#747, dated after mid-2026. I couldn't verify them independently. The NVRAM module only provides the safety layer and a backend interface. It doesn't contain any USB service-mode code.

## What the end-to-end simulation found (`a7iii sim`)

These come from the physical camera model in `a7iii.sim`, not from a real body. They show what
the physics implies; confirm on hardware.

- **Dual gain (§2.2):** ISO 640 has cleaner shadows than ISO 500 (shadow SNR 3.75 vs 3.63), and
  S-Log3 ISO 5000 beats 4000 (1.20 vs 1.04). It does **not** beat ISO 400 (4.12): at correct
  exposure, ISO 400 gets 1.6× more light. Revised rule: skip the 320–500 range, but if ISO 400
  gives enough exposure, use it.
- **HLG3 vs S-Log3 (§1.3):** in the skin/midtone range HLG3 gets **32.9** 8-bit codes per stop against
  S-Log3's **18.4**, which is +79%, more than the +35% the roadmap claims. After a Rec.709 grade, the largest step
  between output levels is 2 codes for HLG3 and 4 for S-Log3.
- **Anti-flicker (§10.3A):** under 50 Hz light at 29.97p, a plain 180° shutter (1/60) shows **7% row
  banding**. The lock picks 1/50 (216°) and banding drops to 0. At 23.976p under 60 Hz it picks 1/40.
- **Gyro sync (§6.1):** two corrections were needed for accurate sync:
  1. Correlate **signed per-axis** rates. Magnitudes are ambiguous for hand shake.
  2. Timestamp optical-flow measurements at **mid-readout** (frame start + readout/2). Without that, sync is
     biased by 12 ms at FF 4K24, which wrecks stabilisation.

  With both, sync error is 2.8 ms and jitter falls 10.8×.
- **Colour match (§4.3):** in the simulator the cameras differ by linear 3×3 sensor responses, so
  ΔE falls to about 0.02. Real cameras also differ spectrally (metamerism), so expect a larger residual on
  real charts. The roadmap's < 1.5 gate is the meaningful target there.
- **Pre-capture trigger (§8.3):** frame differencing misses a subject that arrives and then stops (it only sees
  moving edges), so the trigger compares against a background model instead.

## Hard limits (Tier 4), as in the roadmap

You can't get internal 10-bit video, 4K60, or RAW over HDMI. Nothing here attempts it.
