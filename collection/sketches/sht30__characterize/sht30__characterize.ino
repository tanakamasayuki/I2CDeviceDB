// Direct-I2C SHT30 characterization probe for M5Stack ENV III.
#include <Arduino.h>
#include <Wire.h>
#include <stdlib.h>

#include "measurement_command.h"

#ifndef I2C_SDA_PIN
#define I2C_SDA_PIN "8"
#endif
#ifndef I2C_SCL_PIN
#define I2C_SCL_PIN "9"
#endif
#ifndef MARKER_UART_TX_PIN
#define MARKER_UART_TX_PIN "3"
#endif
#ifndef BUS_HZ
#define BUS_HZ "100000"
#endif

static const int kSdaPin = atoi(I2C_SDA_PIN);
static const int kSclPin = atoi(I2C_SCL_PIN);
static const int kMarkerTxPin = atoi(MARKER_UART_TX_PIN);
static const uint32_t kBusHz = (uint32_t)strtoul(BUS_HZ, nullptr, 10);
static const uint8_t kAddress = 0x44;
#define MARKER Serial1

static void emitReady()
{
  Serial.printf("READY target=sht30 addr=0x%02X sda=%d scl=%d hz=%lu\n",
                kAddress, kSdaPin, kSclPin, (unsigned long)kBusHz);
}

static bool probeAddress()
{
  Wire.beginTransmission(kAddress);
  return Wire.endTransmission() == 0;
}

static uint8_t writeCommand(uint16_t command)
{
  Wire.beginTransmission(kAddress);
  Wire.write((uint8_t)(command >> 8));
  Wire.write((uint8_t)command);
  return Wire.endTransmission();
}

static size_t readBytes(uint8_t *data, size_t length)
{
  size_t received = Wire.requestFrom(kAddress, (uint8_t)length);
  size_t i = 0;
  while (Wire.available() && i < length)
  {
    data[i++] = (uint8_t)Wire.read();
  }
  return received < i ? received : i;
}

static uint8_t crc8(const uint8_t *data, size_t length)
{
  uint8_t crc = 0xFF;
  for (size_t i = 0; i < length; ++i)
  {
    crc ^= data[i];
    for (uint8_t bit = 0; bit < 8; ++bit)
    {
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x31) : (uint8_t)(crc << 1);
    }
  }
  return crc;
}

static void emitFrame(const char *mode, const char *repeatability,
                      const uint8_t *data, size_t length, uint32_t elapsedUs)
{
  if (length != 6)
  {
    Serial.printf("EVENT {\"type\":\"measurement\",\"mode\":\"%s\","
                  "\"repeatability\":\"%s\",\"length\":%u,\"elapsed_us\":%lu}\n",
                  mode, repeatability, (unsigned)length, (unsigned long)elapsedUs);
    return;
  }
  const uint16_t rawT = ((uint16_t)data[0] << 8) | data[1];
  const uint16_t rawRh = ((uint16_t)data[3] << 8) | data[4];
  const bool crcT = crc8(data, 2) == data[2];
  const bool crcRh = crc8(data + 3, 2) == data[5];
  Serial.printf("EVENT {\"type\":\"measurement\",\"mode\":\"%s\","
                "\"repeatability\":\"%s\",\"length\":6,"
                "\"elapsed_us\":%lu,\"raw_temperature\":%u,"
                "\"raw_humidity\":%u,\"crc_temperature_ok\":%s,"
                "\"crc_humidity_ok\":%s}\n",
                mode, repeatability, (unsigned long)elapsedUs, rawT, rawRh,
                crcT ? "true" : "false", crcRh ? "true" : "false");
}

static const MeasurementCommand kMeasurements[] = {
  {"high", 0x2400, 0x2C06, 15},
  {"medium", 0x240B, 0x2C0D, 6},
  {"low", 0x2416, 0x2C10, 4},
};

static bool runResetAndStatus()
{
  MARKER.println("CASE_BEGIN Reset");
  MARKER.println("INPUT {\"command\":\"0x30A2\"}");
  const uint8_t resetRc = writeCommand(0x30A2);
  delay(2);
  const uint8_t statusRc = writeCommand(0xF32D);
  delay(1);
  uint8_t status[3] = {0};
  const size_t n = readBytes(status, sizeof(status));
  const uint16_t value = n == 3 ? (((uint16_t)status[0] << 8) | status[1]) : 0;
  const bool crcOk = n == 3 && crc8(status, 2) == status[2];
  Serial.printf("EVENT {\"type\":\"reset_status\",\"reset_rc\":%u,"
                "\"status_command_rc\":%u,\"length\":%u,"
                "\"status\":%u,\"crc_ok\":%s}\n",
                resetRc, statusRc, (unsigned)n, value, crcOk ? "true" : "false");
  writeCommand(0x3041); // clear status
  MARKER.println("RESULT {\"status\":\"captured\"}");
  MARKER.println("CASE_END Reset");
  return resetRc == 0 && statusRc == 0 && n == 3 && crcOk;
}

static bool runPollingMeasurement(const MeasurementCommand &m)
{
  MARKER.println("CASE_BEGIN Single Measurement");
  MARKER.printf("PHASE polling-%s\n", m.repeatability);
  MARKER.printf("INPUT {\"command\":\"0x%04X\",\"clock_stretch\":false}\n",
                m.pollingCommand);
  if (writeCommand(m.pollingCommand) != 0)
  {
    MARKER.println("CASE_END Single Measurement");
    return false;
  }

  uint8_t data[6] = {0};
  const uint32_t started = micros();
  delay(1); // datasheet minimum interval before the next bus activity
  size_t n = readBytes(data, sizeof(data));
  const size_t immediate = n;
  Serial.printf("EVENT {\"type\":\"not_ready_read\",\"repeatability\":\"%s\","
                "\"received\":%u}\n", m.repeatability, (unsigned)immediate);

  while (n != sizeof(data) && (micros() - started) < (uint32_t)(m.maxDelayMs + 5) * 1000)
  {
    delayMicroseconds(250);
    n = readBytes(data, sizeof(data));
  }
  const uint32_t elapsed = micros() - started;
  emitFrame("polling", m.repeatability, data, n, elapsed);
  MARKER.println("RESULT {\"measurement\":\"captured\"}");
  MARKER.println("CASE_END Single Measurement");
  return n == 6 && crc8(data, 2) == data[2] && crc8(data + 3, 2) == data[5];
}

static bool runStretchingMeasurement(const MeasurementCommand &m)
{
  MARKER.println("CASE_BEGIN Single Measurement");
  MARKER.printf("PHASE stretching-%s\n", m.repeatability);
  MARKER.printf("INPUT {\"command\":\"0x%04X\",\"clock_stretch\":true}\n",
                m.stretchingCommand);
  if (writeCommand(m.stretchingCommand) != 0)
  {
    MARKER.println("CASE_END Single Measurement");
    return false;
  }
  delay(1); // datasheet minimum SCL-free interval before the read
  uint8_t data[6] = {0};
  const uint32_t started = micros();
  const size_t n = readBytes(data, sizeof(data));
  const uint32_t elapsed = micros() - started;
  emitFrame("clock_stretch", m.repeatability, data, n, elapsed);
  MARKER.println("RESULT {\"measurement\":\"captured\"}");
  MARKER.println("CASE_END Single Measurement");
  return n == 6 && crc8(data, 2) == data[2] && crc8(data + 3, 2) == data[5];
}

static void runCharacterization()
{
  MARKER.println("CASE_BEGIN Device Detection");
  const bool present = probeAddress();
  Serial.printf("EVENT {\"type\":\"presence\",\"address\":\"0x44\",\"ack\":%s}\n",
                present ? "true" : "false");
  MARKER.println("CASE_END Device Detection");
  if (!present)
  {
    Serial.println("ALL_DONE target=sht30 ok=0");
    return;
  }

  bool ok = runResetAndStatus();
  for (const auto &m : kMeasurements)
  {
    ok = runPollingMeasurement(m) && ok;
    ok = runStretchingMeasurement(m) && ok;
  }
  Serial.printf("ALL_DONE target=sht30 ok=%d\n", ok ? 1 : 0);
}

static bool readLine(String &line)
{
  if (!Serial.available()) return false;
  line = Serial.readStringUntil('\n');
  line.trim();
  return line.length() > 0;
}

void setup()
{
  Serial.begin(115200);
  MARKER.begin(115200, SERIAL_8N1, -1, kMarkerTxPin);
  Wire.begin(kSdaPin, kSclPin);
  Wire.setClock(kBusHz);
  Wire.setTimeOut(100);
  delay(200);
  emitReady();
}

void loop()
{
  String line;
  if (!readLine(line)) return;
  if (line == "READY") emitReady();
  else if (line == "PING") Serial.println("PONG");
  else if (line == "RUN") runCharacterization();
}
