// A7III-GyroShoe: 500 Hz BMI270 gyro/accel logger for Gyroflow (roadmap §6.1).
//
// Board: Seeed XIAO ESP32-S3 (any ESP32-S3 works; adjust pins).
// Sensor: Bosch BMI270 on SPI. Storage: microSD on SPI.
// Library: "SparkFun BMI270 Arduino Library" (Library Manager).
//
// Output: one Gyroflow .gcsv per take, raw integer counts with scales in the
// header, identical to a7iii.optics.gyro.write_gcsv so the desk/tests and the
// device agree byte-for-byte on format.
//
// Serial protocol (115200 baud, newline-terminated), mirrored by
// a7iii/optics/gyroshoe_host.py:
//   START <name> <unix_ms>   open /<name>.gcsv, start logging, 2 ms sync pulse
//   STOP                     close the file
//   MARK <unix_ms>           record a sync marker in <name>.marks.csv (desk record start)
//   STATUS                   -> "OK <logging 0|1> <samples> <dropped>"
// Every command answers "OK ..." or "ERR <reason>".
//
// Status: compiled only against API stubs in CI (no ESP32 toolchain there).
// Verify on hardware: SPI pins, the SparkFun ODR/range calls, SD speed.

#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include "SparkFun_BMI270_Arduino_Library.h"

// ---- pins (XIAO ESP32-S3) ----
static const int PIN_IMU_CS = 1;     // D0
static const int PIN_SD_CS = 21;     // on the Sense expansion board
static const int PIN_SYNC_OUT = 2;   // D1 -> 2 ms pulse into the camera mic (via divider + cap)
static const int PIN_XSYNC_IN = 3;   // D2 <- hot-shoe X-sync (optional, stills)

// ---- sampling ----
static const uint32_t SAMPLE_US = 2000;        // 500 Hz
static const float GYRO_LSB_PER_DPS = 16.4f;   // +/-2000 dps
static const float ACCEL_LSB_PER_G = 4096.0f;  // +/-8 g
static const char *ORIENTATION = "YxZ";        // IMU -> camera axes; set for your mount

struct Sample {
  uint32_t t_us;
  int16_t g[3];
  int16_t a[3];
};

static const size_t RING = 1024;  // ~2 s of headroom while the SD card stalls
static Sample ring[RING];
static volatile size_t head = 0, tail = 0;
static volatile uint32_t dropped = 0;
static volatile uint32_t samples = 0;

static BMI270 imu;
static File logFile;
static File marksFile;  // sync markers live in a sidecar so the .gcsv stays pure data
static bool logging = false;
static uint32_t t0_us = 0;
static String line;
static volatile uint32_t xsyncAt = 0;

static void IRAM_ATTR onXsync() { xsyncAt = micros(); }

static bool ringPush(const Sample &s) {
  size_t next = (head + 1) % RING;
  if (next == tail) {
    dropped++;
    return false;
  }
  ring[head] = s;
  head = next;
  return true;
}

static void syncPulse() {
  digitalWrite(PIN_SYNC_OUT, HIGH);
  delayMicroseconds(2000);
  digitalWrite(PIN_SYNC_OUT, LOW);
}

static void writeHeader(const String &name, uint64_t unixMs) {
  const double gscale = (PI / 180.0) / GYRO_LSB_PER_DPS;
  const double ascale = 1.0 / ACCEL_LSB_PER_G;
  logFile.println("GYROFLOW IMU LOG");
  logFile.println("version,1.3");
  logFile.println("id,a7iii_gyroshoe");
  logFile.print("orientation,"); logFile.println(ORIENTATION);
  logFile.println("vendor,a7iii-gyroshoe");
  logFile.println("lensprofile,");
  logFile.println("tscale,1e-06");
  logFile.print("gscale,"); logFile.println(gscale, 12);
  logFile.print("ascale,"); logFile.println(ascale, 12);
  logFile.print("note,take="); logFile.print(name);
  logFile.print(" unix_ms="); logFile.println((unsigned long long)unixMs);
  logFile.println("t,gx,gy,gz,ax,ay,az");
}

static void reply(const String &msg) { Serial.println(msg); }

static void handleCommand(const String &cmd) {
  if (cmd.startsWith("START ")) {
    int sp = cmd.indexOf(' ', 6);
    String name = sp > 0 ? cmd.substring(6, sp) : cmd.substring(6);
    uint64_t unixMs = sp > 0 ? strtoull(cmd.substring(sp + 1).c_str(), nullptr, 10) : 0;
    if (logging) { reply("ERR already logging"); return; }
    logFile = SD.open("/" + name + ".gcsv", FILE_WRITE);
    if (!logFile) { reply("ERR cannot open file"); return; }
    marksFile = SD.open("/" + name + ".marks.csv", FILE_WRITE);
    if (marksFile) marksFile.println("kind,unix_ms,t_us");
    writeHeader(name, unixMs);
    noInterrupts(); head = tail = 0; dropped = 0; samples = 0; interrupts();
    t0_us = micros();
    logging = true;
    syncPulse();
    reply("OK START " + name);
  } else if (cmd == "STOP") {
    if (!logging) { reply("ERR not logging"); return; }
    logging = false;
    logFile.close();
    if (marksFile) marksFile.close();
    reply("OK STOP " + String(samples) + " " + String(dropped));
  } else if (cmd.startsWith("MARK ")) {
    if (logging && marksFile) {
      marksFile.print("mark,");
      marksFile.print(cmd.substring(5));
      marksFile.print(",");
      marksFile.println(micros() - t0_us);
    }
    syncPulse();
    reply("OK MARK");
  } else if (cmd == "STATUS") {
    reply("OK " + String(logging ? 1 : 0) + " " + String(samples) + " " + String(dropped));
  } else {
    reply("ERR unknown command");
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_SYNC_OUT, OUTPUT);
  digitalWrite(PIN_SYNC_OUT, LOW);
  pinMode(PIN_XSYNC_IN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_XSYNC_IN), onXsync, FALLING);

  SPI.begin();
  while (imu.beginSPI(PIN_IMU_CS) != BMI2_OK) {
    Serial.println("ERR BMI270 not found");
    delay(1000);
  }
  // Verify these against the installed SparkFun library version.
  imu.setAccelODR(BMI2_ACC_ODR_800HZ);
  imu.setGyroODR(BMI2_GYR_ODR_800HZ);

  if (!SD.begin(PIN_SD_CS)) {
    Serial.println("ERR SD card");
  }
  Serial.println("OK READY a7iii-gyroshoe");
}

void loop() {
  static uint32_t next = micros();
  uint32_t now = micros();

  if ((int32_t)(now - next) >= 0) {
    next += SAMPLE_US;
    if (logging && imu.getSensorData() == BMI2_OK) {
      Sample s;
      s.t_us = now - t0_us;
      s.g[0] = (int16_t)lroundf(imu.data.gyroX * GYRO_LSB_PER_DPS);
      s.g[1] = (int16_t)lroundf(imu.data.gyroY * GYRO_LSB_PER_DPS);
      s.g[2] = (int16_t)lroundf(imu.data.gyroZ * GYRO_LSB_PER_DPS);
      s.a[0] = (int16_t)lroundf(imu.data.accelX * ACCEL_LSB_PER_G);
      s.a[1] = (int16_t)lroundf(imu.data.accelY * ACCEL_LSB_PER_G);
      s.a[2] = (int16_t)lroundf(imu.data.accelZ * ACCEL_LSB_PER_G);
      if (ringPush(s)) samples++;
    }
  }

  // Drain the ring to SD between samples (bounded so sampling stays on time).
  int budget = 16;
  while (logging && tail != head && budget-- > 0) {
    const Sample &s = ring[tail];
    char buf[64];
    int n = snprintf(buf, sizeof(buf), "%lu,%d,%d,%d,%d,%d,%d\n", (unsigned long)s.t_us,
                     s.g[0], s.g[1], s.g[2], s.a[0], s.a[1], s.a[2]);
    logFile.write((const uint8_t *)buf, n);
    tail = (tail + 1) % RING;
  }
  if (logging && xsyncAt) {
    if (marksFile) {
      marksFile.print("xsync,,");
      marksFile.println(xsyncAt - t0_us);
    }
    xsyncAt = 0;
  }

  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      line.trim();
      if (line.length()) handleCommand(line);
      line = "";
    } else if (line.length() < 96) {
      line += c;
    }
  }
}
