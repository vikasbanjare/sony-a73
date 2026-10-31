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

## Hard limits (Tier 4), as in the roadmap

You can't get internal 10-bit video, 4K60, or RAW over HDMI. Nothing here attempts it.
