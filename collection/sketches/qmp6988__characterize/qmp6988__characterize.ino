// Direct-I2C QMP6988 characterization probe for M5Stack ENV III.
#include <Arduino.h>
#include <Wire.h>
#include <stdlib.h>

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
static const uint8_t kAddress = 0x70;
#define MARKER Serial1

static void emitReady()
{
  Serial.printf("READY target=qmp6988 addr=0x%02X sda=%d scl=%d hz=%lu\n",
                kAddress, kSdaPin, kSclPin, (unsigned long)kBusHz);
}

static bool probeAddress()
{
  Wire.beginTransmission(kAddress);
  return Wire.endTransmission() == 0;
}

static uint8_t writeRegister(uint8_t reg, uint8_t value)
{
  Wire.beginTransmission(kAddress);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission();
}

static size_t readRegisters(uint8_t reg, uint8_t *data, size_t length)
{
  Wire.beginTransmission(kAddress);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return 0;
  const size_t received = Wire.requestFrom(kAddress, (uint8_t)length);
  size_t i = 0;
  while (Wire.available() && i < length)
  {
    data[i++] = (uint8_t)Wire.read();
  }
  return received < i ? received : i;
}

static bool readRegister(uint8_t reg, uint8_t &value)
{
  return readRegisters(reg, &value, 1) == 1;
}

static void printHex(const uint8_t *data, size_t length)
{
  for (size_t i = 0; i < length; ++i) Serial.printf("%02X", data[i]);
}

static bool runResetIdentityDefaults()
{
  MARKER.println("CASE_BEGIN Reset");
  MARKER.println("INPUT {\"register\":\"0xE0\",\"value\":\"0xE6\"}");
  const uint8_t resetRc = writeRegister(0xE0, 0xE6);
  delay(10);
  uint8_t id = 0;
  const bool idOk = readRegister(0xD1, id);
  uint8_t defaults[5] = {0};
  bool defaultsOk = true;
  for (uint8_t i = 0; i < 5; ++i)
  {
    defaultsOk = readRegister((uint8_t)(0xF1 + i), defaults[i]) && defaultsOk;
  }
  Serial.printf("EVENT {\"type\":\"reset_identity\",\"reset_rc\":%u,"
                "\"chip_id\":%u,\"chip_id_ok\":%s,\"defaults_f1_f5\":\"",
                resetRc, id, (idOk && id == 0x5C) ? "true" : "false");
  printHex(defaults, sizeof(defaults));
  Serial.println("\"}");
  MARKER.println("RESULT {\"identity\":\"captured\"}");
  MARKER.println("CASE_END Reset");
  return resetRc == 0 && idOk && id == 0x5C && defaultsOk;
}

static bool runCalibration()
{
  MARKER.println("CASE_BEGIN Default Read");
  MARKER.println("PHASE calibration");
  uint8_t calibration[25] = {0};
  const size_t n = readRegisters(0xA0, calibration, sizeof(calibration));
  Serial.printf("EVENT {\"type\":\"calibration\",\"start\":\"0xA0\","
                "\"length\":%u,\"bytes\":\"", (unsigned)n);
  printHex(calibration, n);
  Serial.println("\",\"variability\":\"per_specimen\"}");
  MARKER.println("RESULT {\"calibration\":\"captured\"}");
  MARKER.println("CASE_END Default Read");
  return n == sizeof(calibration);
}

static bool waitMeasurement(uint32_t &elapsedUs, uint8_t &lastStatus, bool &sawMeasuring)
{
  const uint32_t started = micros();
  sawMeasuring = false;
  do
  {
    if (!readRegister(0xF3, lastStatus)) return false;
    sawMeasuring = sawMeasuring || (lastStatus & 0x08);
    if (!(lastStatus & 0x08) && sawMeasuring)
    {
      elapsedUs = micros() - started;
      return true;
    }
    if (!sawMeasuring && (micros() - started) >= 2000)
    {
      // Preserve this as an observation: either the mode completed before the
      // first visible status=1, or the device did not expose the transition.
      elapsedUs = micros() - started;
      return true;
    }
    delayMicroseconds(250);
  } while ((micros() - started) < 200000);
  elapsedUs = micros() - started;
  return !(lastStatus & 0x08); // very fast modes may finish before first poll
}

static bool runForcedMeasurement()
{
  MARKER.println("CASE_BEGIN Single Measurement");
  MARKER.println("PHASE forced-minimum");
  // temperature x1 (001), pressure x1 (001), forced mode (01)
  const uint8_t control = 0x25;
  MARKER.println("INPUT {\"ctrl_meas\":\"0x25\"}");
  if (writeRegister(0xF4, control) != 0)
  {
    MARKER.println("CASE_END Single Measurement");
    return false;
  }
  uint32_t elapsed = 0;
  uint8_t status = 0;
  bool sawMeasuring = false;
  const bool ready = waitMeasurement(elapsed, status, sawMeasuring);
  uint8_t raw[6] = {0};
  const size_t n = readRegisters(0xF7, raw, sizeof(raw));
  uint8_t finalControl = 0xFF;
  const bool ctrlOk = readRegister(0xF4, finalControl);
  Serial.printf("EVENT {\"type\":\"forced_measurement\",\"ctrl_meas\":%u,"
                "\"elapsed_us\":%lu,\"last_status\":%u,\"ready\":%s,"
                "\"saw_measuring\":%s,\"final_ctrl_meas\":%u,\"raw_f7_fc\":\"",
                control, (unsigned long)elapsed, status, ready ? "true" : "false",
                sawMeasuring ? "true" : "false", finalControl);
  printHex(raw, n);
  Serial.printf("\",\"length\":%u}\n", (unsigned)n);
  MARKER.println("RESULT {\"measurement\":\"captured\"}");
  MARKER.println("CASE_END Single Measurement");
  // Forced mode returns to the sleep state internally, but this specimen keeps
  // the written mode bits in CTRL_MEAS. Preserve that distinction as data.
  return ready && n == sizeof(raw) && ctrlOk;
}

static bool runNormalMeasurement()
{
  MARKER.println("CASE_BEGIN Continuous Measurement");
  MARKER.println("PHASE normal-representative");
  // Default 1ms standby; temperature x1, pressure x1, normal mode.
  const uint8_t control = 0x27;
  MARKER.println("INPUT {\"ctrl_meas\":\"0x27\",\"samples\":10}");
  if (writeRegister(0xF4, control) != 0)
  {
    MARKER.println("CASE_END Continuous Measurement");
    return false;
  }
  bool ok = true;
  for (uint8_t sample = 0; sample < 10; ++sample)
  {
    delay(10);
    uint8_t raw[6] = {0};
    const size_t n = readRegisters(0xF7, raw, sizeof(raw));
    Serial.printf("EVENT {\"type\":\"normal_sample\",\"index\":%u,"
                  "\"raw_f7_fc\":\"", sample);
    printHex(raw, n);
    Serial.printf("\",\"length\":%u}\n", (unsigned)n);
    ok = ok && n == sizeof(raw);
  }
  // Preserve averaging fields, switch only mode bits to sleep.
  ok = writeRegister(0xF4, 0x24) == 0 && ok;
  MARKER.println("RESULT {\"samples\":10,\"final_mode\":\"sleep\"}");
  MARKER.println("CASE_END Continuous Measurement");
  return ok;
}

static void runCharacterization()
{
  MARKER.println("CASE_BEGIN Device Detection");
  const bool present = probeAddress();
  Serial.printf("EVENT {\"type\":\"presence\",\"address\":\"0x70\",\"ack\":%s}\n",
                present ? "true" : "false");
  MARKER.println("CASE_END Device Detection");
  if (!present)
  {
    Serial.println("ALL_DONE target=qmp6988 ok=0");
    return;
  }

  bool ok = runResetIdentityDefaults();
  ok = runCalibration() && ok;
  ok = runForcedMeasurement() && ok;
  ok = runNormalMeasurement() && ok;
  Serial.printf("ALL_DONE target=qmp6988 ok=%d\n", ok ? 1 : 0);
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
