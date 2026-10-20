#include <Wire.h>

const int MPU_ADDR = 0x68; // MPU9250 I2C address

// Binary packet for the GUI (40 bytes, little-endian).
// After the text calibration lines, every sample is one packet:
//   [0]      0xAA
//   [1]      0x55
//   [2]      36          payload length
//   [3..38]  9 x float32 pitch, roll, yaw (deg),
//                       accX, accY, accZ (g),
//                       gyrX, gyrY, gyrZ (deg/s)
//   [39]     XOR of bytes 2..38
//
// Python:
//   import struct
//   # wait for AA 55, then read 38 bytes
//   n, *vals = struct.unpack('<B9f', payload)  # payload is bytes 2..38
//   checksum_ok = (xor(payload) == last_byte)

// Raw sensor values
int16_t rawAccX, rawAccY, rawAccZ;
int16_t rawGyrX, rawGyrY, rawGyrZ;

// Calculated angles
float pitch, roll, yaw = 0.0;

// Gyroscope offsets
float gyroBiasX = 0, gyroBiasY = 0, gyroBiasZ = 0;

// Timing variable for gyro integration
unsigned long prevTime;

void setup() {
  Serial.begin(57600);
  Wire.begin();

  // Wake up the MPU9250
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B); // PWR_MGMT_1 register
  Wire.write(0x00); // Set to zero to wake up
  Wire.endTransmission(true);

  delay(100);
  Serial.println("MPU9250 Initialized!");

  // --- CALIBRATION STEP ---
  Serial.println("\n--- GYRO CALIBRATION ---");
  Serial.println("Keep the sensor completely STILL on a flat surface...");
  delay(2000);

  long sumX = 0, sumY = 0, sumZ = 0;
  const int samples = 500;

  for (int i = 0; i < samples; i++) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x43); // GYRO_XOUT_H register
    Wire.endTransmission(false);
    Wire.requestFrom(MPU_ADDR, 6, true);

    if (Wire.available() >= 6) {
      sumX += (Wire.read() << 8) | Wire.read();
      sumY += (Wire.read() << 8) | Wire.read();
      sumZ += (Wire.read() << 8) | Wire.read();
    }
    delay(2);
  }

  gyroBiasX = (float)sumX / samples;
  gyroBiasY = (float)sumY / samples;
  gyroBiasZ = (float)sumZ / samples;

  Serial.println("Gyro Calibration Complete!");
  Serial.println("Starting binary packets...");

  prevTime = millis();
}

// Append one little-endian float and fold it into the running XOR.
void packFloat(uint8_t *buf, int &index, float value, uint8_t &checksum) {
  uint8_t bytes[4];
  memcpy(bytes, &value, 4);
  for (int i = 0; i < 4; i++) {
    buf[index++] = bytes[i];
    checksum ^= bytes[i];
  }
}

void sendImuPacket(float pitchDeg, float rollDeg, float yawDeg,
                   float ax, float ay, float az,
                   float gx, float gy, float gz) {
  uint8_t packet[40];
  uint8_t checksum = 0;

  packet[0] = 0xAA;
  packet[1] = 0x55;
  packet[2] = 36;          // 9 floats
  checksum ^= packet[2];

  int index = 3;
  packFloat(packet, index, pitchDeg, checksum);
  packFloat(packet, index, rollDeg, checksum);
  packFloat(packet, index, yawDeg, checksum);
  packFloat(packet, index, ax, checksum);
  packFloat(packet, index, ay, checksum);
  packFloat(packet, index, az, checksum);
  packFloat(packet, index, gx, checksum);
  packFloat(packet, index, gy, checksum);
  packFloat(packet, index, gz, checksum);
  packet[index] = checksum;

  Serial.write(packet, 40);
}

void loop() {
  // Calculate time elapsed (dt) in seconds
  unsigned long currentTime = millis();
  float dt = (currentTime - prevTime) / 1000.0;
  prevTime = currentTime;

  // Request Accelerometer (6 bytes) and Gyroscope (6 bytes) starting from 0x3B
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, 14, true);

  if (Wire.available() >= 14) {
    // Read Accelerometer
    rawAccX = (Wire.read() << 8) | Wire.read();
    rawAccY = (Wire.read() << 8) | Wire.read();
    rawAccZ = (Wire.read() << 8) | Wire.read();

    // Skip temperature registers (2 bytes)
    Wire.read(); Wire.read();

    // Read Gyroscope
    rawGyrX = (Wire.read() << 8) | Wire.read();
    rawGyrY = (Wire.read() << 8) | Wire.read();
    rawGyrZ = (Wire.read() << 8) | Wire.read();
  }

  // Convert raw Accelerometer to g-forces (+/- 2g scale)
  float accX = rawAccX / 16384.0;
  float accY = rawAccY / 16384.0;
  float accZ = rawAccZ / 16384.0;

  // Convert raw Gyroscope to degrees per second (+/- 250 deg/s scale)
  float gyrX = (rawGyrX - gyroBiasX) / 131.0;
  float gyrY = (rawGyrY - gyroBiasY) / 131.0;
  float gyrZ = (rawGyrZ - gyroBiasZ) / 131.0;

  // 1. Calculate Pitch & Roll from Accelerometer (Trigonometry)
  float accPitch = atan2(-accX, sqrt(accY * accY + accZ * accZ)) * 180.0 / M_PI;
  float accRoll  = atan2(accY, accZ) * 180.0 / M_PI;

  // 2. Apply Complementary Filter to Pitch & Roll (combines gyro speed + accel stability)
  pitch = 0.96 * (pitch + gyrY * dt) + 0.04 * accPitch;
  roll  = 0.96 * (roll + gyrX * dt) + 0.04 * accRoll;

  // 3. Calculate Yaw by Integrating Gyroscope Z-axis rotation over time
  yaw += gyrZ * dt;

  sendImuPacket(pitch, roll, yaw, accX, accY, accZ, gyrX, gyrY, gyrZ);

  delay(20); // ~50 Hz update rate
}