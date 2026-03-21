# MediWatch — Real-Time Patient Vitals Dashboard

## Setup

### 1. Install dependencies
```bash
pip install fastapi uvicorn requests
```

### 2. Start the Backend
```bash
uvicorn backend:app --reload --port 8000
```

### 3. Open the Frontend
Open `index.html` directly in your browser.
Or serve it:
```bash
python -m http.server 5500
# then visit http://localhost:5500
```

---

## Architecture

```
Wokwi ESP32 Hardware
       │
       ▼
  backend.py  (FastAPI)
  ├── /ws            ← WebSocket: streams vitals every 3s
  ├── /api/info      ← Doctor + patient list
  └── /api/ai/{id}  ← Llama 3 AI assessment on demand
       │
       ▼
  index.html  (Frontend)
  ├── Connects via WebSocket
  ├── Shows doctor name + all patients
  ├── Normal vitals → clean display
  ├── Threshold crossed → alert with interpretation
  └── "Get AI Assessment" → calls Llama 3
```

## Thresholds
| Vital        | Normal Range       |
|-------------|---------------------|
| HR Pulse    | 60–100 BPM          |
| HR Sensor   | 60–100 BPM          |
| SpO₂        | ≥ 95%               |
| Body Temp   | 36.1–37.2 °C        |
| Room Temp   | 18–26 °C            |
| Humidity    | 40–70 %             |

## Alert Levels
- 🟡 **WARNING** — Mild elevation (e.g., fever)
- 🟠 **CRITICAL** — Dangerous value (e.g., tachycardia, low SpO₂)
- 🔴 **EMERGENCY** — Multi-vital crisis (e.g., Sepsis/PE risk)
