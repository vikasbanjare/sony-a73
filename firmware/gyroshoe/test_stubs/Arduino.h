// Minimal Arduino API surface used by gyroshoe.ino - for host-side compile checks only.
#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cmath>
#include <string>
#define IRAM_ATTR
#define PI 3.14159265358979323846
enum { LOW = 0, HIGH = 1, INPUT = 0, OUTPUT = 1, INPUT_PULLUP = 2, FALLING = 2 };
inline void pinMode(int, int) {}
inline void digitalWrite(int, int) {}
inline void delay(unsigned long) {}
inline void delayMicroseconds(unsigned int) {}
inline uint32_t micros() { return 0; }
inline int digitalPinToInterrupt(int p) { return p; }
inline void attachInterrupt(int, void (*)(), int) {}
inline void noInterrupts() {}
inline void interrupts() {}
class String {
 public:
  std::string s;
  String() {}
  String(const char *c) : s(c) {}
  String(const std::string &x) : s(x) {}
  String(int v) : s(std::to_string(v)) {}
  String(unsigned int v) : s(std::to_string(v)) {}
  String(long v) : s(std::to_string(v)) {}
  String(unsigned long v) : s(std::to_string(v)) {}
  bool startsWith(const char *p) const { return s.rfind(p, 0) == 0; }
  int indexOf(char c, unsigned from = 0) const { auto i = s.find(c, from); return i == std::string::npos ? -1 : (int)i; }
  String substring(unsigned a) const { return String(s.substr(a)); }
  String substring(unsigned a, unsigned b) const { return String(s.substr(a, b - a)); }
  void trim() {}
  unsigned length() const { return (unsigned)s.size(); }
  const char *c_str() const { return s.c_str(); }
  bool operator==(const char *o) const { return s == o; }
  String &operator+=(char c) { s += c; return *this; }
  friend String operator+(const String &a, const String &b) { return String(a.s + b.s); }
  friend String operator+(const char *a, const String &b) { return String(std::string(a) + b.s); }
  friend String operator+(const String &a, const char *b) { return String(a.s + b); }
};
class Print {
 public:
  void print(const char *) {}
  void print(const String &) {}
  void print(unsigned long long) {}
  void print(unsigned long) {}
  void println() {}
  void println(const char *) {}
  void println(const String &) {}
  void println(double, int) {}
  void println(unsigned long long) {}
  void println(unsigned long) {}
  void println(uint32_t) {}
  size_t write(const uint8_t *, size_t n) { return n; }
};
class HardwareSerial : public Print {
 public:
  void begin(unsigned long) {}
  int available() { return 0; }
  int read() { return -1; }
};
extern HardwareSerial Serial;
