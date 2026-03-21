"""
Real-Time Patient Vitals Backend
FastAPI + WebSocket + OpenRouter Llama 3 AI Assessment
Accepts live vitals POSTed from Jupyter notebook
"""

import asyncio
import json
import time
import io
import requests
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OPENROUTER_API_KEY = "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"

DOCTOR = {
    "name": "Dr. Sougata Bose",
    "specialization": "Critical Care & Internal Medicine",
    "ward": "ICU Ward 3"
}

PATIENTS = [
    {"id": "P001", "name": "Sohon Sen",    "age": 58, "gender": "M", "bed": "Bed 1"},
    {"id": "P002", "name": "Soham Santra", "age": 42, "gender": "F", "bed": "Bed 2"},
    {"id": "P003", "name": "Subhranil Ghosh",  "age": 67, "gender": "M", "bed": "Bed 3"},
    {"id": "P004", "name": "Dibyo Sundar Basu", "age": 35, "gender": "F", "bed": "Bed 4"},
]

live_vitals: dict = {}

THRESHOLDS = {
    "hr_pulse":    {"min": 60,   "max": 100,  "unit": "BPM"},
    "hr_max30100": {"min": 60,   "max": 100,  "unit": "BPM"},
    "spo2":        {"min": 95,   "max": 100,  "unit": "%"},
    "body_temp":   {"min": 36.1, "max": 37.2, "unit": "°C"},
    "room_temp":   {"min": 18,   "max": 26,   "unit": "°C"},
    "humidity":    {"min": 40,   "max": 70,   "unit": "%"},
}

class VitalsPayload(BaseModel):
    ai_interpretation: str = None
    patient_id: str
    hr_pulse:    float
    hr_max30100: float
    spo2:        float
    body_temp:   float
    room_temp:   float
    humidity:    float

def get_simulated_vitals(offset: float) -> dict:
    t = time.time() + offset
    return {
        "hr_pulse":    int(60 + (t % 60)),
        "hr_max30100": int(72 + (t / 5) % 50),
        "spo2":        round(99 - (t / 10) % 9, 1),
        "body_temp":   round(36.5 + (t / 30) % 2, 1),
        "room_temp":   22.0,
        "humidity":    60.0,
    }

SIM_OFFSETS = {"P002": 15, "P003": 30, "P004": 45}

def get_vitals_for_patient(patient_id: str) -> dict:
    if patient_id in live_vitals:
        return live_vitals[patient_id]
    return get_simulated_vitals(SIM_OFFSETS.get(patient_id, 0))

def get_alerts(data: dict) -> list:
    alerts = []
    if data["spo2"] < 94:
        alerts.append({"level": "CRITICAL", "vital": "SpO2", "value": f"{data['spo2']}%",
            "message": "Oxygen saturation critically low",
            "interpretation": "Risk of hypoxemia. Immediate oxygen therapy may be required."})
    if data["hr_max30100"] > 110:
        alerts.append({"level": "CRITICAL", "vital": "Heart Rate", "value": f"{data['hr_max30100']} BPM",
            "message": "Tachycardia detected",
            "interpretation": "Heart rate exceeds safe threshold. Evaluate for cardiac arrhythmia or systemic stress."})
    if data["body_temp"] > 38.3:
        alerts.append({"level": "WARNING", "vital": "Body Temp", "value": f"{data['body_temp']}°C",
            "message": "Elevated body temperature — Fever",
            "interpretation": "Possible infection or inflammatory response. Monitor and consider antipyretics."})
    if data["spo2"] < 94 and data["hr_max30100"] > 110:
        alerts.append({"level": "EMERGENCY", "vital": "Multi-Vital", "value": "Combined Alert",
            "message": "SEPSIS / Pulmonary Embolism Risk",
            "interpretation": "Concurrent tachycardia and hypoxemia — escalate immediately to senior physician."})
    return alerts

def get_vital_status(key: str, value: float) -> str:
    t = THRESHOLDS.get(key)
    if not t:
        return "normal"
    if value < t["min"] or value > t["max"]:
        return "critical" if key in ["spo2", "hr_max30100"] else "warning"
    return "normal"

def get_ai_interpretation(patient: dict, data: dict, alerts: list) -> str:
    if not alerts:
        return None
    alert_text = "\n".join([f"- {a['level']}: {a['message']} ({a['value']})" for a in alerts])
    prompt = f"""Patient: {patient['name']}, Age: {patient['age']}, Gender: {patient['gender']}
Vitals: {json.dumps(data)}
Active Alerts:
{alert_text}
Provide a 2-sentence clinical interpretation and recommended immediate action."""
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={"model": "meta-llama/llama-3-8b-instruct", "max_tokens": 150,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=10
        )
        return resp.json()["choices"][0]["message"]["content"]
    except:
        return "AI assessment unavailable — please review alerts manually."

class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)

manager = ConnectionManager()

def build_payload() -> dict:
    payload = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "doctor": DOCTOR, "patients": []}
    for p in PATIENTS:
        vitals = get_vitals_for_patient(p["id"])
        alerts = get_alerts(vitals)
        vitals_with_status = {
            k: {"value": v, "unit": THRESHOLDS.get(k, {}).get("unit", ""), "status": get_vital_status(k, v)}
            for k, v in vitals.items()
        }
        payload["patients"].append({
            "id": p["id"], "name": p["name"], "age": p["age"],
            "gender": p["gender"], "bed": p["bed"],
            "source": "LIVE HARDWARE" if p["id"] in live_vitals else "SIMULATED",
            "vitals": vitals_with_status, "alerts": alerts,
            "ai_interpretation": vitals.get("_ai"),  # from notebook
            "overall_status": (
                "EMERGENCY" if any(a["level"] == "EMERGENCY" for a in alerts) else
                "CRITICAL"  if any(a["level"] == "CRITICAL"  for a in alerts) else
                "WARNING"   if any(a["level"] == "WARNING"   for a in alerts) else "STABLE"
            )
        })
    return payload

async def vitals_broadcaster():
    while True:
        await manager.broadcast(build_payload())
        await asyncio.sleep(300)  # 5 minutes

@app.on_event("startup")
async def startup():
    asyncio.create_task(vitals_broadcaster())

@app.post("/api/vitals")
async def receive_vitals(payload: VitalsPayload):
    live_vitals[payload.patient_id] = {
        "hr_pulse": payload.hr_pulse, "hr_max30100": payload.hr_max30100,
        "spo2": payload.spo2, "body_temp": payload.body_temp,
        "room_temp": payload.room_temp, "humidity": payload.humidity,
        "_ai": payload.ai_interpretation,
    }
    # Data stored — dashboard updates on next 5-min broadcast only
    return {"status": "ok", "patient_id": payload.patient_id}

@app.get("/api/snapshot")
def get_snapshot():
    """HTTP fallback — same payload as WebSocket broadcast"""
    return build_payload()

@app.get("/api/info")
def get_info():
    return {"doctor": DOCTOR, "patients": PATIENTS}

@app.get("/api/ai/{patient_id}")
def get_ai_for_patient(patient_id: str):
    patient = next((p for p in PATIENTS if p["id"] == patient_id), None)
    if not patient:
        return {"error": "Patient not found"}
    vitals = get_vitals_for_patient(patient_id)
    alerts = get_alerts(vitals)
    return {"patient_id": patient_id, "interpretation": get_ai_interpretation(patient, vitals, alerts), "alerts": alerts}


@app.get("/api/report/{patient_id}")
def generate_patient_report(patient_id: str):
    """Generate and stream a PDF report for a patient."""
    patient = next((p for p in PATIENTS if p["id"] == patient_id), None)
    if not patient:
        return {"error": "Patient not found"}

    vitals_raw = get_vitals_for_patient(patient_id)
    alerts     = get_alerts(vitals_raw)
    ai_text    = get_ai_interpretation(patient, vitals_raw, alerts) or "All vitals within normal range."
    timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Styles ────────────────────────────────────────────────────
    ts  = ParagraphStyle("t",  fontSize=22, fontName="Helvetica-Bold", textColor=colors.HexColor("#0a1628"), alignment=TA_CENTER, spaceAfter=4)
    ss  = ParagraphStyle("s",  fontSize=10, fontName="Helvetica",      textColor=colors.HexColor("#4a6a88"), alignment=TA_CENTER, spaceAfter=2)
    scs = ParagraphStyle("sc", fontSize=11, fontName="Helvetica-Bold", textColor=colors.HexColor("#0a1628"), spaceBefore=10, spaceAfter=4)
    ais = ParagraphStyle("ai", fontSize=10, fontName="Helvetica",      textColor=colors.HexColor("#1a2e42"), leading=16, leftIndent=8)
    fs  = ParagraphStyle("f",  fontSize=8,  fontName="Helvetica",      textColor=colors.HexColor("#4a6a88"), alignment=TA_CENTER)

    def vital_status(key, value):
        thr = {"hr_pulse":(60,100),"hr_max30100":(60,100),"spo2":(95,100),"body_temp":(36.1,37.2),"room_temp":(18,26),"humidity":(40,70)}
        lo, hi = thr.get(key, (None, None))
        if lo is None: return "-"
        return "ABNORMAL" if (value < lo or value > hi) else "NORMAL"

    story = []

    # Header
    story.append(Paragraph("MediWatch", ts))
    story.append(Paragraph("Real-Time Patient Vitals Report", ss))
    story.append(Paragraph(f"Generated: {timestamp}", ss))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#00d4ff"), spaceAfter=10))

    # Patient info
    story.append(Paragraph("Patient Information", scs))
    info = [
        ["Patient Name", patient["name"],          "Patient ID",  patient["id"]],
        ["Age",          f"{patient['age']} years", "Gender",    "Male" if patient["gender"] == "M" else "Female"],
        ["Bed",          patient["bed"],            "Attending",   DOCTOR["name"]],
        ["Ward",         "ICU Ward 3",              "Report Time", timestamp],
    ]
    it = Table(info, colWidths=[38*mm,58*mm,38*mm,58*mm])
    it.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(0,-1), colors.HexColor("#e8f4fd")),
        ("BACKGROUND",    (2,0),(2,-1), colors.HexColor("#e8f4fd")),
        ("FONTNAME",      (0,0),(0,-1), "Helvetica-Bold"),
        ("FONTNAME",      (2,0),(2,-1), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0),(-1,-1),9),
        ("GRID",          (0,0),(-1,-1),0.5, colors.HexColor("#d0e4f0")),
        ("VALIGN",        (0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",    (0,0),(-1,-1),5),
        ("BOTTOMPADDING", (0,0),(-1,-1),5),
        ("LEFTPADDING",   (0,0),(-1,-1),6),
    ]))
    story.append(it)
    story.append(Spacer(1, 8))

    # Vitals
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#d0e4f0"), spaceAfter=6))
    story.append(Paragraph("Current Vitals", scs))
    vrows = [
        ["Vital Sign",   "Value",                 "Unit", "Normal Range", "Status"],
        ["HR Pulse",     vitals_raw["hr_pulse"],    "BPM", "60-100",     vital_status("hr_pulse",    vitals_raw["hr_pulse"])],
        ["HR (Sensor)",  vitals_raw["hr_max30100"], "BPM", "60-100",     vital_status("hr_max30100", vitals_raw["hr_max30100"])],
        ["SpO2",         vitals_raw["spo2"],        "%",   "95-100",     vital_status("spo2",        vitals_raw["spo2"])],
        ["Body Temp",    vitals_raw["body_temp"],   "C",   "36.1-37.2",  vital_status("body_temp",   vitals_raw["body_temp"])],
        ["Room Temp",    vitals_raw["room_temp"],   "C",   "18-26",      vital_status("room_temp",   vitals_raw["room_temp"])],
        ["Humidity",     vitals_raw["humidity"],    "%",   "40-70",      vital_status("humidity",    vitals_raw["humidity"])],
    ]
    vt = Table(vrows, colWidths=[45*mm,28*mm,18*mm,38*mm,35*mm])
    vts = [
        ("BACKGROUND",    (0,0),(-1,0),  colors.HexColor("#0a1628")),
        ("TEXTCOLOR",     (0,0),(-1,0),  colors.white),
        ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0,0),(-1,-1), 9),
        ("ALIGN",         (1,0),(-1,-1), "CENTER"),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("LEFTPADDING",   (0,0),(-1,-1), 6),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.HexColor("#f8fcff"), colors.white]),
        ("GRID",          (0,0),(-1,-1), 0.5, colors.HexColor("#d0e4f0")),
    ]
    for i, row in enumerate(vrows[1:], 1):
        if row[4] == "ABNORMAL":
            vts += [("TEXTCOLOR",(4,i),(4,i),colors.HexColor("#dc2626")),("FONTNAME",(4,i),(4,i),"Helvetica-Bold"),("BACKGROUND",(4,i),(4,i),colors.HexColor("#fee2e2"))]
        else:
            vts += [("TEXTCOLOR",(4,i),(4,i),colors.HexColor("#16a34a")),("FONTNAME",(4,i),(4,i),"Helvetica-Bold")]
    vt.setStyle(TableStyle(vts))
    story.append(vt)
    story.append(Spacer(1, 8))

    # Alerts
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#d0e4f0"), spaceAfter=6))
    story.append(Paragraph("Active Alerts", scs))
    if not alerts:
        story.append(Paragraph("All vitals within normal range — no active alerts.",
            ParagraphStyle("ok", fontSize=10, fontName="Helvetica", textColor=colors.HexColor("#16a34a"), leading=14)))
    else:
        for a in alerts:
            level = "EMERGENCY" if "EMERGENCY" in str(a) else "CRITICAL" if "CRITICAL" in str(a) else "WARNING"
            msg   = a["message"] if isinstance(a, dict) else str(a)
            val   = a["value"]   if isinstance(a, dict) else ""
            bg = {"EMERGENCY":"#fee2e2","CRITICAL":"#fff3e0","WARNING":"#fffde7"}[level]
            tc = {"EMERGENCY":"#991b1b","CRITICAL":"#b45309","WARNING":"#854d0e"}[level]
            at = Table([[f"  {level}", f"  {msg}  {val}"]], colWidths=[28*mm,148*mm])
            at.setStyle(TableStyle([
                ("BACKGROUND",    (0,0),(-1,0), colors.HexColor(bg)),
                ("TEXTCOLOR",     (0,0),(-1,0), colors.HexColor(tc)),
                ("FONTNAME",      (0,0),(0,0),  "Helvetica-Bold"),
                ("FONTNAME",      (1,0),(1,0),  "Helvetica"),
                ("FONTSIZE",      (0,0),(-1,0), 9),
                ("TOPPADDING",    (0,0),(-1,0), 5),
                ("BOTTOMPADDING", (0,0),(-1,0), 5),
                ("LEFTPADDING",   (0,0),(-1,0), 6),
                ("BOX",           (0,0),(-1,0), 0.5, colors.HexColor(tc)),
            ]))
            story.append(at)
            story.append(Spacer(1, 3))

    story.append(Spacer(1, 8))

    # AI Assessment
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#d0e4f0"), spaceAfter=6))
    story.append(Paragraph("AI Clinical Assessment  (Llama 3 via OpenRouter)", scs))
    ai_tbl = Table([[Paragraph(ai_text.replace("\n","<br/>"), ais)]], colWidths=[174*mm])
    ai_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#f0f9ff")),
        ("BOX",           (0,0),(-1,-1), 0.8, colors.HexColor("#00d4ff")),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ("TOPPADDING",    (0,0),(-1,-1), 8),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
    ]))
    story.append(ai_tbl)
    story.append(Spacer(1, 10))

    # Footer
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#d0e4f0"), spaceAfter=4))
    story.append(Paragraph(f"MediWatch Auto-Report  |  {DOCTOR['name']}  |  ICU Ward 3  |  {timestamp}", fs))
    story.append(Paragraph("This report is AI-assisted. All clinical decisions must be verified by a licensed physician.", fs))

    # Build into memory buffer
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm, leftMargin=18*mm, rightMargin=18*mm)
    doc.build(story)
    buf.seek(0)

    filename = f"report_{patient['id']}_{patient['name'].replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_json(build_payload())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)