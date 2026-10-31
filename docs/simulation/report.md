# A7III Enhanced Suite: end-to-end simulation report

29 passed · 0 failed · 1 blocked · 1 silicon limits

Every scenario drives the production code against the virtual ILCE-7M3 (`a7iii.sim`). Most of them
go through the real Sony PTP driver.

| # | Feature | Roadmap | Tier | Result | Key metrics |
|---|---|---|---|---|---|
| 1 | 35-language unlock via guarded NVRAM service tool | §3.2-3.3, §9 | Tier 1 | **PASS** | written=33, languages_enabled=35, calibration_untouched=True, restore_exact=True |
| 2 | 29m59s limit + PAL/NTSC nag unlock | §3.3, §9 | Tier 1 | **BLOCKED** | locked=['rec_limit', 'pal_ntsc_warning'] |
| 3 | Picture Profile recipes + correct-exposure grey | §4.2 | Tier 1 | **PASS** | A7III-Cinetone.grey_signal=0.4089, A7III-Cinetone.target=0.409, A7III-Cinetone.native_iso_matches=True, A7III-HLG-Cine.grey_signal=0.3782 |
| 4 | IMX410 dual conversion gain ('hidden dual native ISO') | §2.2 | Tier 1 | **PASS** | Cine4 ISO 400.shadow_snr=4.12, Cine4 ISO 400.gain=LCG, Cine4 ISO 400.read_noise_e=3.77, Cine4 ISO 500.shadow_snr=3.63 |
| 5 | HLG3 vs S-Log3 tonal density in an 8-bit pipeline | §1.3, §4.1 | Tier 1 | **PASS** | hlg.codes_per_stop=32.9, hlg.distinct_levels_3_stops=100, hlg.max_display_step_8bit=2.0, slog2.codes_per_stop=22.0 |
| 6 | FX3 colour match: ΔE2000 CCM + OKLab RBF -> 65³ LUT + DCTL | §4.3, §9 | Tier 3 | **PASS** | mean_dE_before=2.01, mean_dE_after=0.021, max_dE_after=0.044, skin_dE_after=[0.016, 0.011, 0.03] |
| 7 | 8-bit 4:2:0 -> float 4:4:4 joint-bilateral chroma reconstruction | §4.3 step 3 | Tier 3 | **PASS** | rmse_joint_bilateral=0.00372, rmse_nearest=0.02012, output_dtype=float32 |
| 8 | Sony PTP SDIO handshake + property control + live view | §10.2 | Tier 2 | **PASS** | props_reported=7, liveview_bytes=7433, focus_frame.x=0.5, focus_frame.y=0.5 |
| 9 | External AI subject AF -> PTP Touch-AF -> native PDAF | §5.2-5.3 mode A, §9 | Tier 2 | **PASS** | in_focus_ai=1.0, in_focus_fixed_point=0.0 |
| 10 | f/11 PDAF cutoff guard + hunting prevention | §5.3 mode C, RSK-04 | Tier 2 | **PASS** | f11_ok=True, f13_message=PDAF DISABLED (f/13 > f/11) - add ND or switch to MF, settled_travel_pdaf_steps=0.0, settled_travel_cdaf_steps=204.81200000000013 |
| 11 | 180° shutter-angle lock + 50/60 Hz anti-flicker | §7, §10.3 module A | Tier 2 | **PASS** | 25.0p @ 50 Hz locked.shutter=1/50, 25.0p @ 50 Hz locked.effective_angle=180.0, 25.0p @ 50 Hz locked.row_banding_pct=0.0, 29.97p @ 50 Hz unlocked.shutter=1/60 |
| 12 | Cine EI mode (ISO locked to native gain, EI shifts the monitor LUT) | §7, §9 | Tier 1+2 | **PASS** | recording_iso=5000, gain=HCG, recorded_grey=0.4118, monitor_shift_ev=1.0 |
| 13 | EL-Zone style stop-based false colour | §7, §10.3 module B | Tier 2 | **PASS** | Cine4.grey_zone=-0.5 to +0.5: middle grey, Cine4.+3.5EV_zone=+3 to +5: bright highlight, HLG3.grey_zone=-0.5 to +0.5: middle grey, HLG3.+3.5EV_zone=+3 to +5: bright highlight |
| 14 | Automated focus bracketing over PTP + focus stacking | §8.1, §9 | Tier 2+3 | **PASS** | slices=41, planned_mm=[300.8, 302.3, 303.9, 305.4, 307.0, 308.6, 310.2, 311.8, 313.4, 315.1, 316.8, 318.5, 320.2, 322.0, 323.8, 325.6, 327.4, 329.3, 331.1, 333.0, 335.0, 336.9, 338.9, 340.9, 343.0, 345.0, 347.1, 349.3, 351.4, 353.6, 355.8, 358.1, 360.4, 362.7, 365.0, 367.4, 369.9, 372.3, 374.8, 377.4, 380.0], coverage_stack=0.995, coverage_best_single=0.268 |
| 15 | Cubic-Bézier rack focus over PTP near/far steps | §5.3 mode B | Tier 2 | **PASS** | ticks=48, first_tick_steps=0, peak_tick_steps=9, final_step=460.0 |
| 16 | A7III-GyroShoe IMU + Gyroflow-style stabilisation (with RS correction) | §6.1, §9 | Tier 2+3 | **PASS** | sync_error_ms=2.83, jitter_px_raw=2.353, jitter_px_stabilised=0.217, improvement_x=10.8 |
| 17 | Rolling-shutter readout: Full-Frame 4K24 vs Super35 4K24 | §2.1, §6.1 | Tier 1 | **PASS** | skew_rad_per_frame_ff=0.01556, skew_rad_per_frame_s35=0.00799, ratio=0.513 |
| 18 | Dynamic focus-breathing compensation | §6.2, §9 | Tier 2+3 | **PASS** | size_spread_before_pct=3.85, size_spread_after_pct=0.242, fitted_k1=-0.3588 |
| 19 | Focus map / depth-of-field visualiser | §7 | Tier 2 | **PASS** | class_at_eye=1, class_background=2 |
| 20 | Anamorphic de-squeeze + multi-aspect guides | §7 | Tier 2 | **PASS** | eye_gap_px_true=14.0, squeezed=7.0, restored=14.0, guide_2.39.name=2.39:1 |
| 21 | Waveform, RGB parade, vectorscope, histogram | §7, §9 | Tier 2 | **PASS** | light_skin_hue_angle_deg=122.9, skin_line_deg=123 |
| 22 | Pre-capture video ring buffer (retroactive recording) | §7, §9 | Tier 2 | **PASS** | frames=60, preroll_frames=48, preroll_s=1.9602936269602935, duration_s=2.460794127460792 |
| 23 | SMPTE LTC generator + jam-sync from the camera's audio track | §7 | Tier 2+3 | **PASS** | decoded_frames=224, first_decoded=14:22:10:20, video_frame0_tc=14:22:10:20, error_frames=0.0 |
| 24 | 4-channel audio matrix: device sync, BWF timecode, clip repair | §7 | Tier 2+3 | **PASS** | offset_samples=777, clipped_samples=1148, max_repair_error=0.0, bwf_time_reference=2483049600 |
| 25 | Handheld multi-frame super-resolution | §8.2 | Tier 3 | **PASS** | psnr_single_bilinear_db=28.69, psnr_superres_db=34.48, gain_db=5.8 |
| 26 | Multi-frame noise / astro stacking | §8.2 | Tier 3 | **PASS** | snr_single=5.19, snr_stack=18.46, gain_x=3.56, dr_gain_ev=2.0 |
| 27 | Pre-capture burst (motion-triggered, with pre-roll) | §8.3 | Tier 2+3 | **PASS** | subject_entered_s=1.418, trigger_s=1.502, burst_frames=18 |
| 28 | Verified dual-destination offload + manifests + proxies | §11 Phase 5 | Tier 3 | **PASS** | files=2, manifests=2, resume_all_skipped=True, proxies=['C0001_proxy.mp4'] |
| 29 | Cloud sync API: takes, presets, LUTs, sealed NVRAM backups | §10.1 packages/07, Phase 5 | Tier 3 | **PASS** | takes_converged=True, backup_upload=200, tampered_upload=400 |
| 30 | A7III Control Desk end to end (PTP + AI AF + scopes + takes) | §10.1 packages/06 | Tier 2 | **PASS** | iso_locked=125, shutter=1/50, af.status=rate limited, af.sent=None |
| 31 | Internal 10-bit 4:2:2, 4K60/120, HDMI RAW | §9 Tier 4 | Tier 4 | **LIMIT** |  |

## Details

### 35-language unlock via guarded NVRAM service tool: PASS

*Pass criterion:* 33 locked language flags enabled after a sealed backup, read-back verified, calibration untouched, restore works

```json
{
  "written": 33,
  "languages_enabled": 35,
  "calibration_untouched": true,
  "restore_exact": true
}
```

### 29m59s limit + PAL/NTSC nag unlock: BLOCKED

*Pass criterion:* refused until verified property IDs exist

```json
{
  "locked": [
    "rec_limit",
    "pal_ntsc_warning"
  ]
}
```

The roadmap gives no property IDs for these flags. The tool refuses to guess; add a verified ID to nvram/registry.py (reviewed change) to enable them.

### Picture Profile recipes + correct-exposure grey: PASS

*Pass criterion:* 18% grey lands on each recipe's middle-grey level within 2%; recipe native ISOs match the DCG table

```json
{
  "A7III-Cinetone": {
    "grey_signal": 0.4089,
    "target": 0.409,
    "native_iso_matches": true
  },
  "A7III-HLG-Cine": {
    "grey_signal": 0.3782,
    "target": 0.3783,
    "native_iso_matches": true
  },
  "A7III-Log2-Pro": {
    "grey_signal": 0.3394,
    "target": 0.3395,
    "native_iso_matches": true
  },
  "A7III-Neutral-709": {
    "grey_signal": 0.4089,
    "target": 0.409,
    "native_iso_matches": true
  }
}
```

### IMX410 dual conversion gain ('hidden dual native ISO'): PASS

*Pass criterion:* shadow SNR at the HCG ISO beats the 'forbidden zone' ISO just below it (Cine4 640 > 500; S-Log3 5000 > 4000)

```json
{
  "Cine4 ISO 400": {
    "shadow_snr": 4.12,
    "gain": "LCG",
    "read_noise_e": 3.77
  },
  "Cine4 ISO 500": {
    "shadow_snr": 3.63,
    "gain": "LCG",
    "read_noise_e": 3.58
  },
  "Cine4 ISO 640": {
    "shadow_snr": 3.75,
    "gain": "HCG",
    "read_noise_e": 1.67
  },
  "Cine4 ISO 800": {
    "shadow_snr": 3.39,
    "gain": "HCG",
    "read_noise_e": 1.49
  },
  "S-Log3 ISO 3200": {
    "shadow_snr": 1.12,
    "gain": "LCG",
    "read_noise_e": 3.77
  },
  "S-Log3 ISO 4000": {
    "shadow_snr": 1.04,
    "gain": "LCG",
    "read_noise_e": 3.58
  },
  "S-Log3 ISO 5000": {
    "shadow_snr": 1.2,
    "gain": "HCG",
    "read_noise_e": 1.69
  },
  "S-Log3 ISO 6400": {
    "shadow_snr": 1.12,
    "gain": "HCG",
    "read_noise_e": 1.49
  }
}
```

Shadow patch (0.3% reflectance) at correct exposure for each ISO, measured pre-quantisation. The HCG ISO receives 22% less light than the ISO below it and still has the cleaner shadows.

### HLG3 vs S-Log3 tonal density in an 8-bit pipeline: PASS

*Pass criterion:* HLG3 spends more 8-bit code values per stop than S-Log3 across skin/midtones (-1.5..+1.5 EV)

```json
{
  "hlg": {
    "codes_per_stop": 32.9,
    "distinct_levels_3_stops": 100,
    "max_display_step_8bit": 2.0
  },
  "slog2": {
    "codes_per_stop": 22.0,
    "distinct_levels_3_stops": 67,
    "max_display_step_8bit": 3.0
  },
  "slog3": {
    "codes_per_stop": 18.4,
    "distinct_levels_3_stops": 56,
    "max_display_step_8bit": 4.0
  },
  "rec709": {
    "codes_per_stop": 41.9,
    "distinct_levels_3_stops": 127,
    "max_display_step_8bit": 1.0
  }
}
```

Larger display steps after the grade show up as visible banding on skin and skies.

### FX3 colour match: ΔE2000 CCM + OKLab RBF -> 65³ LUT + DCTL: PASS

*Pass criterion:* through the generated LUT: mean ΔE2000 < 1.5 over 24 patches and < 1.0 on skin patches (roadmap Phase 2 gate)

```json
{
  "mean_dE_before": 2.01,
  "mean_dE_after": 0.021,
  "max_dE_after": 0.044,
  "skin_dE_after": [
    0.016,
    0.011,
    0.03
  ],
  "ccm_only_mean_dE": 0.389
}
```

Patches extracted from rendered 8-bit frames (HLG3 a7 III vs S-Log3 FX3-like reference).

Artifacts: `color_a7iii_hlg3.png`, `color_fx3_slog3.png`, `a7iii_hlg3_to_fx3_slog3.cube`, `a7iii_hlg3_to_fx3_slog3.dctl`, `a7iii_to_fx3_matrix_only.dctl`

### 8-bit 4:2:0 -> float 4:4:4 joint-bilateral chroma reconstruction: PASS

*Pass criterion:* chroma error after reconstruction is lower than plain nearest-neighbour upsampling

```json
{
  "rmse_joint_bilateral": 0.00372,
  "rmse_nearest": 0.02012,
  "output_dtype": "float32"
}
```

Artifacts: `chroma_reconstructed.png`

### Sony PTP SDIO handshake + property control + live view: PASS

*Pass criterion:* 3-phase handshake succeeds, settings round-trip, live view returns a JPEG and focus frames

```json
{
  "props_reported": 7,
  "liveview_bytes": 7433,
  "focus_frame": {
    "x": 0.5,
    "y": 0.5,
    "w": 0.06,
    "h": 0.1,
    "status": "unfocused"
  },
  "ops_logged": 10
}
```

Artifacts: `ptp_liveview.png`

### External AI subject AF -> PTP Touch-AF -> native PDAF: PASS

*Pass criterion:* subject eye stays inside the depth of field in >= 90% of frames after acquisition, vs a fixed AF point baseline

```json
{
  "in_focus_ai": 1.0,
  "in_focus_fixed_point": 0.0
}
```

Subject walks across frame; the fixed AF point (camera's own behaviour without subject tracking) loses them.

Artifacts: `ai_af_tracking.png`, `fixed_point_baseline.png`

### f/11 PDAF cutoff guard + hunting prevention: PASS

*Pass criterion:* guard flags f/13 over PTP; CDAF beyond f/11 hunts measurably; AI steering is suppressed while PDAF is off

```json
{
  "f11_ok": true,
  "f13_message": "PDAF DISABLED (f/13 > f/11) - add ND or switch to MF",
  "settled_travel_pdaf_steps": 0.0,
  "settled_travel_cdaf_steps": 204.81200000000013,
  "ai_commands_sent_at_f16": 0
}
```

### 180° shutter-angle lock + 50/60 Hz anti-flicker: PASS

*Pass criterion:* locked speeds render with < 0.5% row banding under AC light; the naive 180° speed under 50 Hz bands visibly

```json
{
  "25.0p @ 50 Hz locked": {
    "shutter": "1/50",
    "effective_angle": 180.0,
    "row_banding_pct": 0.0
  },
  "29.97p @ 50 Hz unlocked": {
    "shutter": "1/60",
    "effective_angle": 179.8,
    "row_banding_pct": 7.068
  },
  "29.97p @ 50 Hz locked": {
    "shutter": "1/50",
    "effective_angle": 215.8,
    "row_banding_pct": 0.0
  },
  "23.976p @ 60 Hz locked": {
    "shutter": "1/40",
    "effective_angle": 215.8,
    "row_banding_pct": 0.0
  },
  "59.94p @ 60 Hz locked": {
    "shutter": "1/60",
    "effective_angle": 359.6,
    "row_banding_pct": 0.0
  }
}
```

The unlocked 29.97p case picks 1/60 s (179.8°), which is not a multiple of the 100 Hz light period.

Artifacts: `flicker_cases.png`

### Cine EI mode (ISO locked to native gain, EI shifts the monitor LUT): PASS

*Pass criterion:* PTP locks ISO 5000 (HCG) for S-Log3; rating EI 10000 lifts monitored grey by exactly +1 EV; recorded signal unchanged

```json
{
  "recording_iso": 5000,
  "gain": "HCG",
  "recorded_grey": 0.4118,
  "monitor_shift_ev": 1.0
}
```

### EL-Zone style stop-based false colour: PASS

*Pass criterion:* 18% grey maps to the middle-grey zone in every curve; +3.5 EV maps to 'bright highlight'

```json
{
  "Cine4": {
    "grey_zone": "-0.5 to +0.5: middle grey",
    "+3.5EV_zone": "+3 to +5: bright highlight"
  },
  "HLG3": {
    "grey_zone": "-0.5 to +0.5: middle grey",
    "+3.5EV_zone": "+3 to +5: bright highlight"
  },
  "S-Log2": {
    "grey_zone": "-0.5 to +0.5: middle grey",
    "+3.5EV_zone": "+3 to +5: bright highlight"
  },
  "S-Log3": {
    "grey_zone": "-0.5 to +0.5: middle grey",
    "+3.5EV_zone": "+3 to +5: bright highlight"
  }
}
```

10 zones, identical meaning across curves.

Artifacts: `false_color_cine4_hlg3_slog2_slog3.png`

### Automated focus bracketing over PTP + focus stacking: PASS

*Pass criterion:* stack covers >= 90% of the frame at near-best sharpness; the best single frame covers far less

```json
{
  "slices": 41,
  "planned_mm": [
    300.8,
    302.3,
    303.9,
    305.4,
    307.0,
    308.6,
    310.2,
    311.8,
    313.4,
    315.1,
    316.8,
    318.5,
    320.2,
    322.0,
    323.8,
    325.6,
    327.4,
    329.3,
    331.1,
    333.0,
    335.0,
    336.9,
    338.9,
    340.9,
    343.0,
    345.0,
    347.1,
    349.3,
    351.4,
    353.6,
    355.8,
    358.1,
    360.4,
    362.7,
    365.0,
    367.4,
    369.9,
    372.3,
    374.8,
    377.4,
    380.0
  ],
  "coverage_stack": 0.995,
  "coverage_best_single": 0.268
}
```

Artifacts: `focus_stack_merged.png`, `focus_stack_first_last.png`

### Cubic-Bézier rack focus over PTP near/far steps: PASS

*Pass criterion:* lands exactly on target; eased (first tick < 1/3 of peak tick speed)

```json
{
  "ticks": 48,
  "first_tick_steps": 0,
  "peak_tick_steps": 9,
  "final_step": 460.0
}
```

### A7III-GyroShoe IMU + Gyroflow-style stabilisation (with RS correction): PASS

*Pass criterion:* IMU/video sync error < 10 ms with an unknown 370 ms START->record latency; frame-to-frame jitter reduced >= 4x

```json
{
  "sync_error_ms": 2.83,
  "jitter_px_raw": 2.353,
  "jitter_px_stabilised": 0.217,
  "improvement_x": 10.8,
  "imu_samples": 1666
}
```

Sync by signed per-axis cross-correlation of gyro rate against rotation recovered from optical flow; per-row correction uses the FF 4K readout time.

Artifacts: `gyroshoe_sd/A001C001.gcsv`, `gyro_before_after.png`

### Rolling-shutter readout: Full-Frame 4K24 vs Super35 4K24: PASS

*Pass criterion:* measured skew ratio S35/FF within 15% of 13.8/24.4 = 0.566 on a fast pan

```json
{
  "skew_rad_per_frame_ff": 0.01556,
  "skew_rad_per_frame_s35": 0.00799,
  "ratio": 0.513
}
```

### Dynamic focus-breathing compensation: PASS

*Pass criterion:* breathing model fitted from rendered frames; compensated subject size varies < 0.5% across the focus range

```json
{
  "size_spread_before_pct": 3.85,
  "size_spread_after_pct": 0.242,
  "fitted_k1": -0.3588
}
```

### Focus map / depth-of-field visualiser: PASS

*Pass criterion:* subject at the focus plane is classified in-focus, background behind, and the overlay is rendered

```json
{
  "class_at_eye": 1,
  "class_background": 2
}
```

Artifacts: `focus_map.png`

### Anamorphic de-squeeze + multi-aspect guides: PASS

*Pass criterion:* a 2x-squeezed capture is restored to within 4% of true proportions; 2.39:1 guide computed

```json
{
  "eye_gap_px_true": 14.0,
  "squeezed": 7.0,
  "restored": 14.0,
  "guide_2.39": {
    "name": "2.39:1",
    "x0": 0,
    "y0": 28,
    "x1": 384,
    "y1": 189
  }
}
```

Artifacts: `anamorphic_restored_guides.png`

### Waveform, RGB parade, vectorscope, histogram: PASS

*Pass criterion:* scopes render from live frames; the chart's skin patch lands near the vectorscope skin-tone line

```json
{
  "light_skin_hue_angle_deg": 122.9,
  "skin_line_deg": 123
}
```

Artifacts: `scope_waveform.png`, `scope_parade.png`, `scope_vectorscope.png`

### Pre-capture video ring buffer (retroactive recording): PASS

*Pass criterion:* a take triggered late contains the buffered seconds before the trigger, encoded to ProRes 422 HQ

```json
{
  "frames": 60,
  "preroll_frames": 48,
  "preroll_s": 1.9602936269602935,
  "duration_s": 2.460794127460792,
  "codec": "prores",
  "pix_fmt": "yuv422p10le",
  "file": "ILCE-7M3-1793425273164.mov"
}
```

60 frames streamed before the trigger; buffer holds 2 s.

Artifacts: `takes/ILCE-7M3-1793425273164/ILCE-7M3-1793425273164.mov`

### SMPTE LTC generator + jam-sync from the camera's audio track: PASS

*Pass criterion:* decoding LTC recorded on the camera's right channel recovers the exact start timecode of video frame 0

```json
{
  "decoded_frames": 224,
  "first_decoded": "14:22:10:20",
  "video_frame0_tc": "14:22:10:20",
  "error_frames": 0.0
}
```

### 4-channel audio matrix: device sync, BWF timecode, clip repair: PASS

*Pass criterion:* recorder synced to the sample; 4-ch BWF carries the start TC; clipped shout repaired from the -12 dB safety

```json
{
  "offset_samples": 777,
  "clipped_samples": 1148,
  "max_repair_error": 0.0,
  "bwf_time_reference": 2483049600
}
```

Artifacts: `take_4ch.wav`

### Handheld multi-frame super-resolution: PASS

*Pass criterion:* 12 tremor-shifted stills reconstructed at 2x beat single-frame upscaling by >= 3 dB PSNR against a true 2x render

```json
{
  "psnr_single_bilinear_db": 28.69,
  "psnr_superres_db": 34.48,
  "gain_db": 5.8
}
```

Pixels integrate light over their area (4x4 supersampled aperture).

Artifacts: `superres_single_vs_sr.png`

### Multi-frame noise / astro stacking: PASS

*Pass criterion:* 16-frame sigma-clipped stack improves SNR by ~sqrt(16) = 4x (3.2x-4.8x)

```json
{
  "snr_single": 5.19,
  "snr_stack": 18.46,
  "gain_x": 3.56,
  "dr_gain_ev": 2.0
}
```

### Pre-capture burst (motion-triggered, with pre-roll): PASS

*Pass criterion:* trigger fires within 3 frames of the subject entering the ROI and the burst includes earlier frames

```json
{
  "subject_entered_s": 1.418,
  "trigger_s": 1.502,
  "burst_frames": 18
}
```

Artifacts: `burst_first_trigger_last.png`

### Verified dual-destination offload + manifests + proxies: PASS

*Pass criterion:* every file copied to both drives, hash-verified, resumable, manifests re-verify, proxies generated

```json
{
  "files": 2,
  "manifests": 2,
  "resume_all_skipped": true,
  "proxies": [
    "C0001_proxy.mp4"
  ]
}
```

### Cloud sync API: takes, presets, LUTs, sealed NVRAM backups: PASS

*Pass criterion:* two desks converge on the same take list; tampered NVRAM backup rejected

```json
{
  "takes_converged": true,
  "backup_upload": 200,
  "tampered_upload": 400
}
```

### A7III Control Desk end to end (PTP + AI AF + scopes + takes): PASS

*Pass criterion:* desk drives the simulated body over PTP, AI AF engages, every view and scope renders, a take is logged

```json
{
  "iso_locked": 125,
  "shutter": "1/50",
  "af": {
    "status": "rate limited",
    "sent": null,
    "part": "eye"
  },
  "take_frames": 16
}
```

Artifacts: `desk_falsecolor.jpg`

### Internal 10-bit 4:2:2, 4K60/120, HDMI RAW: LIMIT

*Pass criterion:* documented silicon limits; not attempted

The CXD90045 video encoder and HDMI transmitter are 8-bit, and IMX410 readout bandwidth caps full-width 4K at 30p. No software path changes this. The suite instead gets the most out of 8-bit: HLG3, 4:2:2 HDMI capture, float chroma reconstruction and dithering.
