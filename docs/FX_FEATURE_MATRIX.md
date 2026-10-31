# FX3 / FX6 / FX30 features on the a7 III

What each cinema-line feature becomes on an a7 III, and where it runs.
Status reflects real-hardware testing on an ILCE-7M3, firmware 4.04 (see `CAMERA_BASELINE.md`).

**Where:** `Camera` = native or service-mode setting in the body · `Desk` = live, in the Control Desk (`a7iii desk`) · `Post` = files you take into your editor · `—` = not achievable.

## Colour and picture

| FX feature | a7 III result | Where | How |
|---|---|---|---|
| S-Log3 / S-Gamut3.Cine | Yes (8-bit) | Camera | `a7iii profiles A7III-SLog3-Cine` (PP8) |
| S-Log2, HLG | Yes (8-bit) | Camera | `A7III-Log2-Pro`, `A7III-HLG-Cine` |
| S-Cinetone | Inspired look only | Camera + Post | `A7III-Cinetone` PP recipe, or `*_to_709_cinetone` LUT. Not Sony's processing. |
| s709 / technical log → Rec.709 | Yes | Post + Desk | `a7iii luts` → `*_to_709_technical_33/65.cube`; Desk "Cine EI" view |
| Portrait / soft-skin look | Yes | Camera + Post | `A7III-Portrait-Soft` PP, `*_to_709_portrait` LUT |
| FX3 camera match | Yes, chart-based | Post | `a7iii match` (needs paired chart shots from both cameras) |
| User 3D LUT loaded in camera (MLUT) | — | — | No LUT import in a7 III firmware; use the Desk or an HDMI monitor |
| 10-bit 4:2:2, All-Intra | — | — | 8-bit pipeline; `chroma` reconstruction helps grading only |

## Exposure and Cine mode

| FX feature | a7 III result | Where | How |
|---|---|---|---|
| Cine EI (locked base ISO, EI shifts monitor) | Yes | Desk | Native ISO = Low/High, Exposure index field, "Cine EI" view |
| Dual base ISO | Partial | Camera | IMX410 dual conversion gain: 100/640 (Cine/709), 800/5000 (S-Log) — `a7iii iso` |
| Shutter angle | Yes | Desk | Shutter angle + anti-flicker (50/60 Hz) |
| False colour | Yes | Desk | "False colour" view, stop-based zones |
| Zebra | Yes | Camera + Desk | Desk: 70–100% levels |
| Waveform, vectorscope, parade, histogram | Yes | Desk | Scopes panel |
| Gamma display assist | Yes | Camera | Native a7 III menu |

## Framing and focus

| FX feature | a7 III result | Where | How |
|---|---|---|---|
| Frame lines | Yes | Desk | 2.39 / 2.35 / 1.85 / 16:9 / 4:3 / 1:1 / 4:5 / 9:16 with matte |
| Safety zones | Yes | Desk | 80 / 90 / 93 / 95% |
| Centre marker | Yes | Desk | Centre marker |
| Anamorphic de-squeeze | Yes | Desk + Post | 1.33–2.0× |
| Focus peaking | Yes | Camera + Desk | Desk: Low / Mid / High (red) |
| AI subject tracking AF | Overlay only | Desk | Detection works; moving the AF point needs touch-AF 0xD2E4, which this body does not report |
| Focus breathing compensation | Yes | Post | `optics` breathing correction |
| Rack focus / focus bracketing | Yes (sim-tested) | Desk | Rack near/far, `a7iii bracket` |

## Recording and workflow

| FX feature | a7 III result | Where | How |
|---|---|---|---|
| No 30-min record limit | Yes | Camera | Service-mode tweak applied: 13h 01m (see baseline) |
| Pre-roll / cache record | Yes | Desk | Pre-roll buffer |
| Proxy recording | Yes | Post | `a7iii offload --proxies` |
| Verified dual offload | Yes | Post | `a7iii offload` + SHA-256 manifests |
| Timecode | Partial | Post | LTC generator + jam-sync from audio; no TC in/out port |
| 4-channel audio / XLR | — | — | Needs external audio hardware |
| 4K 60/120p, HDMI RAW, genlock, fan cooling | — | — | Hardware limits |
| Active / electronic stabilisation in body | Post only | Post | GyroShoe IMU + Gyroflow-style stabilisation |
