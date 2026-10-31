#pragma once
#include "Arduino.h"
#define FILE_WRITE "w"
class File : public Print {
 public:
  explicit operator bool() const { return true; }
  void close() {}
};
struct SDClass {
  bool begin(int) { return true; }
  File open(const String &, const char *) { return File(); }
};
extern SDClass SD;
