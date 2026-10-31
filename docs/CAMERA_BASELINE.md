# Camera baseline (roadmap Phase 1 / BASE-01, REV-01)

Recorded 31 Oct 2026 from the owner's camera over USB on macOS (arm64).

## Identity

| Item | Value |
|---|---|
| Model | ILCE-7M3 (product code 0032829420) |
| Body firmware | 4.04 (latest listed by Sony) |
| Lens | model 0x15a08038, firmware 3.00 |
| Card | 119 GB, freshly formatted in camera |

## PTP (USB PC Remote)

- SDIO handshake works; the camera reports **61 property codes**:
  `0x5004 0x5005 0x5007 0x500a 0x500b 0x500c 0x500e 0x5010 0x5013 0xd200 0xd201 0xd203 0xd20d 0xd20e 0xd20f 0xd211 0xd213 0xd21e 0xd21b 0xd21d 0xd21f 0xd217 0xd218 0xd219 0xd212 0xd210 0xd21c 0xd222 0xd22c 0xd22d 0xd22e 0xd22f 0xd230 0xd231 0xd232 0xd233 0xd235 0xd236 0xd24f 0xd250 0xd221 0xd214 0xd215 0xd220 0xd2c1 0xd2c2 0xd2c3 0xd2c9 0xd2c8 0xd2c5 0xd2c7 0xd2cb 0xd2cc 0xd2cd 0xd2ce 0xd2cf 0xd2d0 0xd2d2 0xd2d3 0xd2d4 0xd2d1`
- **0xD2E4 (touch-AF position) is not reported** → AI AF can't move the focus point on this body.
- Live view works: header is u32 JPEG offset (1012) + u32 size, then an info block, then a 1024×576 JPEG. The first GetObject after connect can return 0x200F (Access Denied); retry.
- Not yet tested: property writes, shutter release, movie record, focus steps.

## Service mode (Sony-PMCA-RE v0.18-22-ga82f5ba, service shell)

- Works on 4.04 from macOS with `sudo` (libusb must detach the mass-storage driver). Updater shell and app install are not supported on this body.
- Original settings saved before any write: `a7iii_Backup_20261031-122639.bin`, 1,153,748 bytes, SHA-256 `dc2b060b6a648dc4b88061cd7e5f0e2fb5beca66dd356d78620389b523497810` (copies in `~/Documents` and `~/Claude/sony-a73-camera`). Not committed: it is specific to this body.

| Tweak | Before | After |
|---|---|---|
| Video recording limit | 0h 29m 50s | **13h 01m 00s** |
| Languages | 13 / 35 | **35 / 35** |
| PAL / NTSC selector | on | on |
| USB app installer | on | on (no effect: no app support) |
| 4K recording limit | not offered | — |

Undo: `pmca_apply_tweaks.py --off recLimit language` from the PMCA checkout.

## Not possible on this body

Custom firmware (signed, encrypted CXD90045 firmware), in-camera apps, in-camera LUT import. See `FX_FEATURE_MATRIX.md`.
