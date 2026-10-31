# Third-party notices

## Runtime dependencies

| Package | License | Used for |
|---|---|---|
| NumPy | BSD-3-Clause | everything numeric |
| SciPy | BSD-3-Clause | filters, RBF interpolation, optimisation |
| Pillow | MIT-CMU (HPND) | JPEG/PNG encoding |
| FastAPI, Starlette, Pydantic | MIT | Control Desk and cloud sync API |
| Uvicorn, websockets | BSD-3-Clause | web server and WebSockets |
| pyusb (optional) | BSD-3-Clause | USB PTP transport |
| ultralytics (optional) | AGPL-3.0 | YOLO-pose detector adapter; **AGPL obligations apply if you ship it** |
| opencv-python (optional) | Apache-2.0 | HDMI capture via UVC |
| xxhash (optional) | BSD-2-Clause | fast offload checksums |
| FFmpeg (external binary) | LGPL/GPL depending on build | ProRes/H.264/H.265 encoding, proxies |

Firmware: SparkFun BMI270 Arduino Library (MIT) and Bosch BMI270 SensorAPI (BSD-3-Clause).

## Referenced, not copied

No code from these projects is included. They informed protocol details, and
each place that relies on them says so in the source:

- libgphoto2 (LGPL-2.1): Sony PTP opcode semantics and the property-descriptor layout
- ma1co/Sony-PMCA-RE (MIT): Sony service-mode (Senser) concepts in the roadmap
- Gyroflow (GPL-3.0): `.gcsv` log format; stabilisation approach
- Published algorithms: CIEDE2000 (Sharma et al. 2005), OKLab (Ottosson 2020),
  root-polynomial colour correction (Finlayson et al. 2015), upsampled-DFT registration
  (Guizar-Sicairos et al. 2008), iterative back-projection (Irani & Peleg 1991),
  SMPTE ST 12-1 timecode
