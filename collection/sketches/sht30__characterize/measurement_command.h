#pragma once

#include <Arduino.h>

struct MeasurementCommand
{
  const char *repeatability;
  uint16_t pollingCommand;
  uint16_t stretchingCommand;
  uint16_t maxDelayMs;
};
