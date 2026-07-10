// Address Sweep probe (product-agnostic).
//
// Sweeps the full 7-bit address space 0x00-0x7F, including the I2C reserved
// ranges (0x00-0x07 / 0x78-0x7F) on purpose: some devices answer there. The
// logic analyzer records the ACK/NACK per address; this sketch only drives the
// bus and brackets the operation with UART markers on the LA-observed line.
//
// GPIO and marker pin come from compile-time defines injected by
// build_config.toml (see docs/COLLECTION.ja.md). Defaults let it build stand-alone.
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
#define BUS_HZ "100000" // scan is nominal-only; speed does not change presence
#endif

static const int kSdaPin = atoi(I2C_SDA_PIN);
static const int kSclPin = atoi(I2C_SCL_PIN);
static const int kMarkerTxPin = atoi(MARKER_UART_TX_PIN);
static const uint32_t kBusHz = (uint32_t)strtoul(BUS_HZ, nullptr, 10);

// Serial  = USB CDC, the pytest control/status channel (READY / PONG / ALL_DONE).
// Serial1 = marker line observed by the LA on the UART_TX channel; its
//           CASE_BEGIN/CASE_END land on the captured timeline for Level4.
#define MARKER Serial1

static void syncMarker()
{
  // Serial1 writes are buffered. Emit the operation boundary before I2C starts
  // so its captured timestamp is a valid lower bound for the bus transaction.
  MARKER.flush();
}

static void emitReady()
{
  Serial.print("READY sda=");
  Serial.print(kSdaPin);
  Serial.print(" scl=");
  Serial.print(kSclPin);
  Serial.print(" hz=");
  Serial.println(kBusHz);
}

static void runSweep()
{
  MARKER.println("CASE_BEGIN Address Sweep");
  syncMarker();
  int found = 0;
  for (uint8_t addr = 0x00; addr <= 0x7F; addr++)
  {
    Wire.beginTransmission(addr);
    // endTransmission() == 0 => the device ACKed its address (present).
    // The MCU is the authority for presence; the LA capture of the same sweep
    // is noise-prone and kept only as transient/uniform data (not persisted).
    if (Wire.endTransmission() == 0)
    {
      Serial.printf("FOUND 0x%02X\n", addr);
      found++;
    }
  }
  MARKER.println("CASE_END Address Sweep");
  syncMarker();
  Serial.printf("ALL_DONE found=%d\n", found);
}

static bool readLine(String &line)
{
  if (!Serial.available())
  {
    return false;
  }
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
  delay(200);
  emitReady();
}

void loop()
{
  String line;
  if (!readLine(line))
  {
    return;
  }
  if (line == "PING")
  {
    Serial.println("PONG");
  }
  else if (line == "READY")
  {
    emitReady();
  }
  else if (line == "RUN")
  {
    runSweep();
  }
}
