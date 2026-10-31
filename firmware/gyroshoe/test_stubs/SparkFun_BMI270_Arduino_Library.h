#pragma once
#include <cstdint>
#define BMI2_OK 0
#define BMI2_ACC_ODR_800HZ 0x0B
#define BMI2_GYR_ODR_800HZ 0x0B
struct BMI270_SensorData { float accelX, accelY, accelZ, gyroX, gyroY, gyroZ; };
class BMI270 {
 public:
  BMI270_SensorData data{};
  int8_t beginSPI(uint8_t, uint32_t = 100000) { return BMI2_OK; }
  int8_t setAccelODR(uint8_t) { return BMI2_OK; }
  int8_t setGyroODR(uint8_t) { return BMI2_OK; }
  int8_t getSensorData() { return BMI2_OK; }
};
