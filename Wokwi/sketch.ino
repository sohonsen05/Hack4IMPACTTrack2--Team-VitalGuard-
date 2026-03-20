#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include "MAX30100_PulseOximeter.h"
#include <OneWire.h>
#include <DallasTemperature.h>
#include "DHT.h"
#include <PulseSensorPlayground.h>

#define DHTTYPE DHT11
#define DHTPIN 18
#define DS18B20_PIN 5
#define PULSE_PIN 34
#define REPORTING_PERIOD_MS 1000

float temperature, humidity, BPM, SpO2, bodytemperature;
int pulseBPM = 0;
bool poxAvailable = false;

const char* ssid = "Wokwi-GUEST";
const char* password = "";

DHT dht(DHTPIN, DHTTYPE);
PulseOximeter pox;
PulseSensorPlayground pulseSensor;
uint32_t tsLastReport = 0;
OneWire oneWire(DS18B20_PIN);
DallasTemperature sensors(&oneWire);

WebServer server(80);

void onBeatDetected() {
  Serial.println("Beat!");
}

void setup() {
  Serial.begin(115200);
  pinMode(19, OUTPUT);
  delay(100);

  dht.begin();
  sensors.begin();

  // Pulse Sensor
  pulseSensor.analogInput(PULSE_PIN);
  pulseSensor.setThreshold(550);
  pulseSensor.begin();
  Serial.println("Pulse Sensor ready");

  Serial.println("Connecting to WiFi...");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.print(".");
  }
  Serial.println("");
  Serial.println("WiFi connected..!");
  Serial.print("Got IP: ");
  Serial.println(WiFi.localIP());

  server.on("/", handle_OnConnect);
  server.onNotFound(handle_NotFound);
  server.begin();
  Serial.println("HTTP server started");

  // MAX30100
  Wire.begin(21, 22);
  Serial.print("Initializing pulse oximeter..");
  if (!pox.begin()) {
    Serial.println("MAX30100 not detected - using simulated values");
    poxAvailable = false;
  } else {
    Serial.println("SUCCESS");
    pox.setOnBeatDetectedCallback(onBeatDetected);
    pox.setIRLedCurrent(MAX30100_LED_CURR_7_6MA);
    poxAvailable = true;
  }
}

void loop() {
  server.handleClient();

  // Pulse Sensor
  pulseSensor.sawStartOfBeat();
  pulseBPM = pulseSensor.getBeatsPerMinute();

  // MAX30100
  if (poxAvailable) {
    pox.update();
    BPM  = pox.getHeartRate();
    SpO2 = pox.getSpO2();
  } else {
    // Simulated — rises to critical over time for demo
    BPM  = 72  + (millis() / 5000)  % 50;
    SpO2 = 99  - (millis() / 10000) % 9;
  }

  // DHT11
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (!isnan(t)) temperature = t;
  if (!isnan(h)) humidity    = h;

  // DS18B20
  sensors.requestTemperatures();
  float bt = sensors.getTempCByIndex(0);
  if (bt != -127) bodytemperature = bt;

  if (millis() - tsLastReport > REPORTING_PERIOD_MS) {

    // JSON output for Python middleware
    Serial.print("{\"hr_pulse\":");
    Serial.print(pulseBPM);
    Serial.print(",\"hr_max30100\":");
    Serial.print(BPM);
    Serial.print(",\"spo2\":");
    Serial.print(SpO2);
    Serial.print(",\"body_temp\":");
    Serial.print(bodytemperature);
    Serial.print(",\"room_temp\":");
    Serial.print(temperature);
    Serial.print(",\"humidity\":");
    Serial.print(humidity);
    Serial.println("}");

    Serial.print("Pulse Sensor BPM : "); Serial.println(pulseBPM);
    Serial.print("MAX30100 BPM     : "); Serial.println(BPM);
    Serial.print("SpO2             : "); Serial.print(SpO2);          Serial.println("%");
    Serial.print("Body Temperature : "); Serial.print(bodytemperature); Serial.println("°C");
    Serial.print("Room Temperature : "); Serial.print(temperature);     Serial.println("°C");
    Serial.print("Room Humidity    : "); Serial.print(humidity);        Serial.println("%");
    Serial.println("*********************************");

    tsLastReport = millis();
  }
}

void handle_OnConnect() {
  server.send(200, "text/html", SendHTML(temperature, humidity, BPM, SpO2, bodytemperature, pulseBPM));
}

void handle_NotFound() {
  server.send(404, "text/plain", "Not found");
}

String SendHTML(float temperature, float humidity, float BPM, float SpO2, float bodytemperature, int pulseBPM) {
  bool critical = (SpO2 < 94 || BPM > 110 || bodytemperature > 38.3);

  String html = "<!DOCTYPE html><html><head>";
  html += "<title>VITAL Watch</title>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1.0'>";
  html += "<meta http-equiv='refresh' content='1'>";
  html += "<link rel='stylesheet' href='https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.7.2/css/all.min.css'>";
  html += "<style>";
  html += "* { box-sizing: border-box; margin: 0; padding: 0; }";
  html += "body { background: #0a1c48; font-family: sans-serif; color: #fff; padding: 20px; }";
  html += "h1 { text-align: center; font-size: 1.8rem; color: #48dc8c; margin-bottom: 8px; }";
  html += "h3 { text-align: center; color: #aac4ff; font-size: 0.95rem; margin-bottom: 20px; }";
  html += ".alert { background: #cc0000; border-radius: 10px; padding: 14px; text-align: center;";
  html += "         font-size: 1.1rem; font-weight: bold; margin-bottom: 20px; animation: blink 1s infinite; }";
  html += ".safe  { background: #1a5c2a; border-radius: 10px; padding: 14px; text-align: center;";
  html += "         font-size: 1rem; margin-bottom: 20px; }";
  html += "@keyframes blink { 0%{opacity:1} 50%{opacity:0.6} 100%{opacity:1} }";
  html += ".grid { display: flex; flex-wrap: wrap; justify-content: center; gap: 16px; }";
  html += ".card { background: #0d2870; border-radius: 14px; padding: 20px; width: 200px;";
  html += "        text-align: center; box-shadow: 0 4px 14px rgba(0,0,0,0.4); }";
  html += ".card.danger { border: 2px solid #ff4444; }";
  html += ".card i { font-size: 2rem; margin-bottom: 10px; }";
  html += ".card .value { font-size: 2.4rem; font-weight: bold; }";
  html += ".card .label { font-size: 0.85rem; color: #aac4ff; margin-top: 6px; }";
  html += "</style></head><body>";

  html += "<h1>&#127973; VITAL Watch</h1>";
  html += "<h3>AI Shield for Real-Time Clinical Safety</h3>";

  if (critical) {
    html += "<div class='alert'>&#128680; RED FLAG — Critical Vitals Detected! Escalate Immediately.</div>";
  } else {
    html += "<div class='safe'>&#9989; All Vitals Normal</div>";
  }

  html += "<div class='grid'>";

  // Pulse Sensor BPM
  html += "<div class='card'>";
  html += "<i class='fas fa-heartbeat' style='color:#e74c3c'></i>";
  html += "<div class='value'>" + String(pulseBPM) + "</div>";
  html += "<div class='label'>Pulse Sensor BPM</div>";
  html += "</div>";

  // MAX30100 HR
  String bpmClass = (BPM > 110) ? "card danger" : "card";
  html += "<div class='" + bpmClass + "'>";
  html += "<i class='fas fa-heart' style='color:#ff6b6b'></i>";
  html += "<div class='value'>" + String((int)BPM) + "</div>";
  html += "<div class='label'>Heart Rate (MAX30100)</div>";
  html += "</div>";

  // SpO2
  String spo2Class = (SpO2 < 94) ? "card danger" : "card";
  html += "<div class='" + spo2Class + "'>";
  html += "<i class='fas fa-lungs' style='color:#48dc8c'></i>";
  html += "<div class='value'>" + String((int)SpO2) + "%</div>";
  html += "<div class='label'>SpO2 (MAX30100)</div>";
  html += "</div>";

  // Body Temperature
  String btClass = (bodytemperature > 38.3) ? "card danger" : "card";
  html += "<div class='" + btClass + "'>";
  html += "<i class='fas fa-thermometer-full' style='color:#d9534f'></i>";
  html += "<div class='value'>" + String((int)bodytemperature) + "°C</div>";
  html += "<div class='label'>Body Temp (DS18B20)</div>";
  html += "</div>";

  // Room Temperature
  html += "<div class='card'>";
  html += "<i class='fas fa-thermometer-half' style='color:#0275d8'></i>";
  html += "<div class='value'>" + String((int)temperature) + "°C</div>";
  html += "<div class='label'>Room Temp (DHT11)</div>";
  html += "</div>";

  // Humidity
  html += "<div class='card'>";
  html += "<i class='fas fa-tint' style='color:#5bc0de'></i>";
  html += "<div class='value'>" + String((int)humidity) + "%</div>";
  html += "<div class='label'>Humidity (DHT11)</div>";
  html += "</div>";

  html += "</div></body></html>";
  return html;
}
