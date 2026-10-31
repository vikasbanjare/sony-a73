# A7III-GyroShoe firmware

A 500 Hz gyro/accelerometer logger that rides in the camera's hot shoe and
writes Gyroflow `.gcsv` files (roadmap §6.1).

## Hardware (about $12 BOM)

| Part | Notes |
|---|---|
| Seeed XIAO ESP32-S3 (Sense board for microSD) | any ESP32-S3 works; adjust the pins at the top of the sketch |
| Bosch BMI270 breakout (SPI) | ±2000 dps, ±8 g |
| microSD card | class 10 or better |
| 3D-printed hot-shoe sled | it must have zero play. Any wobble ends up in the gyro data. |
| Optional: 10 kΩ/1 kΩ divider + 1 µF cap | from `PIN_SYNC_OUT` to the camera's 3.5 mm mic input (right channel) |

## Wiring (XIAO ESP32-S3)

| Signal | Pin |
|---|---|
| BMI270 SCK / MOSI / MISO | default SPI pins |
| BMI270 CS | D0 |
| SD CS | 21 (Sense board) |
| Sync pulse out | D1 |
| Hot-shoe X-sync in (optional) | D2 |

## Build

The Arduino IDE needs the "SparkFun BMI270 Arduino Library" from the Library Manager. Or use arduino-cli:

```bash
arduino-cli lib install "SparkFun BMI270 Arduino Library"
```

```bash
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 firmware/gyroshoe
```

## Status

The sketch is compiled in CI against `test_stubs/`, which checks syntax and types but
not on-device behaviour. Before trusting it on set, check these on the real board:
- the SparkFun ODR calls (`setAccelODR` / `setGyroODR`) match your library version
- the SD card keeps up with 500 Hz (`STATUS` reports dropped samples)
- the `orientation` string matches how the board sits in the shoe. Calibrate it once in Gyroflow.

Recording sync: the Control Desk sends `START`/`MARK`/`STOP` over USB serial
(`a7iii.optics.gyroshoe_host.GyroShoeLink`). Gyroflow syncs by optical flow anyway. The
2 ms pulse on the camera's audio track is there as a frame-accurate fallback.
