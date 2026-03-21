"""
Wokwi Real-Time Monitor + AI Interpretation + PDF Report Generator
"""

import time
import json
import requests
import os
from datetime import datetime

# ── ReportLab imports for PDF ─────────────────────────────────────────────────
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# ── Configuration ──────────────────────────────────────────────────────────────
POLL_INTERVAL      = 300.0                          # 5 minutes
LOG_TO_FILE        = True
LOG_FILE           = "wokwi_log.json"
BACKEND_URL        = "http://localhost:8080/api/vitals"
PATIENT_ID         = "P001"
PATIENT_NAME       = "Sohon Sen"
PATIENT_AGE        = 58
PATIENT_GENDER     = "Male"
PATIENT_BED        = "Bed 1"
DOCTOR_NAME        = "Dr. Sougata Bose"
OPENROUTER_API_KEY = "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"

AI_CHANGE_THRESHOLD = {
    "hr_pulse": 2, "hr_max30100": 2, "spo2": 0.5, "body_temp": 0.1,
}
# ──────────────────────────────────────────────────────────────────────────────


# ── 1. Vitals reader (replace with serial read) ───────────────────────────────
def get_simulated_vitals() -> dict:
    """
    Replace this block with your real serial read:
        import serial, json
        ser  = serial.Serial('COM3', 115200)
        line = ser.readline().decode().strip()
        return json.loads(line)
    """
    t = time.time()
    return {
        "hr_pulse":    int(60  + (t % 60)),
        "hr_max30100": int(72  + (t / 5) % 50),
        "spo2":        round(99  - (t / 10) % 9, 1),
        "body_temp":   round(36.5 + (t / 30) % 2, 1),
        "room_temp":   22.0,
        "humidity":    60.0,
    }


# ── 2. Alert detector ─────────────────────────────────────────────────────────
def get_alerts(data: dict) -> list:
    alerts = []
    if data["spo2"] < 94:
        alerts.append("CRITICAL: SpO2 low ({:.1f}%)".format(data["spo2"]))
    if data["hr_max30100"] > 110:
        alerts.append("CRITICAL: Tachycardia ({} BPM)".format(data["hr_max30100"]))
    if data["body_temp"] > 38.3:
        alerts.append("WARNING: Fever ({:.1f} C)".format(data["body_temp"]))
    if data["spo2"] < 94 and data["hr_max30100"] > 110:
        alerts.append("EMERGENCY: SEPSIS/PE Risk — Escalate immediately")
    return alerts


# ── 3. Change detector ────────────────────────────────────────────────────────
def has_changed(current: dict, previous: dict) -> bool:
    if previous is None:
        return True
    for key, thr in AI_CHANGE_THRESHOLD.items():
        if abs(current.get(key, 0) - previous.get(key, 0)) >= thr:
            return True
    return False


# ── 4. Llama 3 AI interpretation ──────────────────────────────────────────────
def get_ai_interpretation(data: dict, alerts: list) -> str:
    """Call Llama 3 via OpenRouter and return clinical interpretation."""
    alert_text = "\n".join(f"  - {a}" for a in alerts) if alerts else "  None"

    prompt = f"""You are a senior ICU physician. Analyze the following real-time patient vitals and provide a structured clinical assessment.

Patient : {PATIENT_NAME}, Age: {PATIENT_AGE}, Gender: {PATIENT_GENDER}
Doctor  : {DOCTOR_NAME}

Vitals:
  HR Pulse     : {data['hr_pulse']} BPM
  HR (Sensor)  : {data['hr_max30100']} BPM
  SpO2         : {data['spo2']} %
  Body Temp    : {data['body_temp']} C
  Room Temp    : {data['room_temp']} C
  Humidity     : {data['humidity']} %

Active Alerts:
{alert_text}

Provide your response in exactly this format:
CLINICAL SUMMARY: [2 sentences describing the overall clinical picture]
VITAL ANALYSIS: [1 sentence per abnormal vital explaining what it indicates]
IMMEDIATE ACTION: [1-2 sentences on what should be done right now]
RISK LEVEL: [one of: LOW / MODERATE / HIGH / CRITICAL]"""

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type":  "application/json"
            },
            json={
                "model":      "meta-llama/llama-3-8b-instruct",
                "max_tokens": 300,
                "messages":   [{"role": "user", "content": prompt}]
            },
            timeout=15
        )
        return resp.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.Timeout:
        return "AI assessment timed out. Please review alerts manually."
    except Exception as e:
        return f"AI assessment unavailable: {str(e)}"


# ── 5. PDF report generator ───────────────────────────────────────────────────
def generate_pdf_report(data: dict, alerts: list, ai_text: str, timestamp: str) -> str:
    """Generate a styled PDF report and return the file path."""

    # ── File name ──────────────────────────────────────────────────────────────
    safe_ts   = timestamp.replace(":", "-").replace(" ", "_")
    filename  = f"report_{PATIENT_ID}_{safe_ts}.pdf"
    filepath  = os.path.join(os.getcwd(), filename)

    doc    = SimpleDocTemplate(filepath, pagesize=A4,
                               topMargin=15*mm, bottomMargin=15*mm,
                               leftMargin=18*mm, rightMargin=18*mm)
    styles = getSampleStyleSheet()

    # ── Custom styles ──────────────────────────────────────────────────────────
    title_style = ParagraphStyle("title",
        fontSize=22, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0a1628"),
        alignment=TA_CENTER, spaceAfter=4)

    sub_style = ParagraphStyle("sub",
        fontSize=10, fontName="Helvetica",
        textColor=colors.HexColor("#4a6a88"),
        alignment=TA_CENTER, spaceAfter=2)

    section_style = ParagraphStyle("section",
        fontSize=11, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0a1628"),
        spaceBefore=10, spaceAfter=4,
        borderPad=4)

    normal_style = ParagraphStyle("norm",
        fontSize=10, fontName="Helvetica",
        textColor=colors.HexColor("#1a2e42"),
        leading=16, spaceAfter=4)

    ai_style = ParagraphStyle("ai",
        fontSize=10, fontName="Helvetica",
        textColor=colors.HexColor("#1a2e42"),
        leading=16, spaceAfter=6,
        leftIndent=8)

    story = []

    # ── Header band ───────────────────────────────────────────────────────────
    story.append(Paragraph("MediWatch", title_style))
    story.append(Paragraph("Real-Time Patient Vitals Report", sub_style))
    story.append(Paragraph(f"Generated: {timestamp}", sub_style))
    story.append(HRFlowable(width="100%", thickness=2,
                            color=colors.HexColor("#00d4ff"), spaceAfter=10))

    # ── Patient info table ────────────────────────────────────────────────────
    story.append(Paragraph("Patient Information", section_style))
    info_data = [
        ["Patient Name", PATIENT_NAME,  "Patient ID",  PATIENT_ID],
        ["Age",          f"{PATIENT_AGE} years", "Gender", PATIENT_GENDER],
        ["Bed",          PATIENT_BED,    "Attending",   DOCTOR_NAME],
        ["Ward",         "ICU Ward 3",   "Report Time", timestamp],
    ]
    info_table = Table(info_data, colWidths=[38*mm, 58*mm, 38*mm, 58*mm])
    info_table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (0, -1), colors.HexColor("#e8f4fd")),
        ("BACKGROUND",  (2, 0), (2, -1), colors.HexColor("#e8f4fd")),
        ("TEXTCOLOR",   (0, 0), (0, -1), colors.HexColor("#0a1628")),
        ("TEXTCOLOR",   (2, 0), (2, -1), colors.HexColor("#0a1628")),
        ("FONTNAME",    (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",    (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (1, 0), (1, -1), [colors.white]),
        ("ROWBACKGROUNDS", (3, 0), (3, -1), [colors.white]),
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#d0e4f0")),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 8))

    # ── Vitals table ──────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1,
                            color=colors.HexColor("#d0e4f0"), spaceAfter=6))
    story.append(Paragraph("Current Vitals", section_style))

    def vital_status(key, value):
        thresholds = {
            "hr_pulse":    (60, 100),
            "hr_max30100": (60, 100),
            "spo2":        (95, 100),
            "body_temp":   (36.1, 37.2),
            "room_temp":   (18, 26),
            "humidity":    (40, 70),
        }
        lo, hi = thresholds.get(key, (None, None))
        if lo is None: return "—"
        if value < lo or value > hi: return "ABNORMAL"
        return "NORMAL"

    def status_color(s):
        return colors.HexColor("#dc2626") if s == "ABNORMAL" else colors.HexColor("#16a34a")

    vital_rows = [
        ["Vital Sign", "Value", "Unit", "Normal Range", "Status"],
        ["HR Pulse",       data["hr_pulse"],    "BPM", "60–100",     vital_status("hr_pulse",    data["hr_pulse"])],
        ["HR (Sensor)",    data["hr_max30100"], "BPM", "60–100",     vital_status("hr_max30100", data["hr_max30100"])],
        ["SpO2",           data["spo2"],        "%",   "95–100",     vital_status("spo2",        data["spo2"])],
        ["Body Temp",      data["body_temp"],   "°C",  "36.1–37.2",  vital_status("body_temp",   data["body_temp"])],
        ["Room Temp",      data["room_temp"],   "°C",  "18–26",      vital_status("room_temp",   data["room_temp"])],
        ["Humidity",       data["humidity"],    "%",   "40–70",      vital_status("humidity",    data["humidity"])],
    ]

    vt = Table(vital_rows, colWidths=[45*mm, 28*mm, 18*mm, 38*mm, 35*mm])
    vt_style = [
        ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#0a1628")),
        ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, -1), 9),
        ("ALIGN",        (1, 0), (-1, -1), "CENTER"),
        ("ALIGN",        (0, 0), (0, -1), "LEFT"),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.HexColor("#f8fcff"), colors.white]),
        ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#d0e4f0")),
    ]
    # Colour ABNORMAL cells red
    for i, row in enumerate(vital_rows[1:], start=1):
        if row[4] == "ABNORMAL":
            vt_style.append(("TEXTCOLOR",    (4, i), (4, i), colors.HexColor("#dc2626")))
            vt_style.append(("FONTNAME",     (4, i), (4, i), "Helvetica-Bold"))
            vt_style.append(("BACKGROUND",   (4, i), (4, i), colors.HexColor("#fee2e2")))
        else:
            vt_style.append(("TEXTCOLOR",    (4, i), (4, i), colors.HexColor("#16a34a")))
            vt_style.append(("FONTNAME",     (4, i), (4, i), "Helvetica-Bold"))

    vt.setStyle(TableStyle(vt_style))
    story.append(vt)
    story.append(Spacer(1, 8))

    # ── Active alerts ─────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1,
                            color=colors.HexColor("#d0e4f0"), spaceAfter=6))
    story.append(Paragraph("Active Alerts", section_style))

    if not alerts:
        story.append(Paragraph("✓  No active alerts — all vitals within normal range.",
                                ParagraphStyle("ok", fontSize=10, fontName="Helvetica",
                                               textColor=colors.HexColor("#16a34a"), leading=14)))
    else:
        for a in alerts:
            level = "EMERGENCY" if "EMERGENCY" in a else "CRITICAL" if "CRITICAL" in a else "WARNING"
            bg    = {"EMERGENCY": "#fee2e2", "CRITICAL": "#fff3e0", "WARNING": "#fffde7"}[level]
            tc    = {"EMERGENCY": "#991b1b", "CRITICAL": "#b45309", "WARNING": "#854d0e"}[level]
            a_tbl = Table([[f"  {level}", f"  {a}"]], colWidths=[28*mm, 148*mm])
            a_tbl.setStyle(TableStyle([
                ("BACKGROUND",   (0, 0), (0, 0), colors.HexColor(bg)),
                ("BACKGROUND",   (1, 0), (1, 0), colors.HexColor(bg)),
                ("TEXTCOLOR",    (0, 0), (-1, 0), colors.HexColor(tc)),
                ("FONTNAME",     (0, 0), (0, 0), "Helvetica-Bold"),
                ("FONTNAME",     (1, 0), (1, 0), "Helvetica"),
                ("FONTSIZE",     (0, 0), (-1, 0), 9),
                ("TOPPADDING",   (0, 0), (-1, 0), 5),
                ("BOTTOMPADDING",(0, 0), (-1, 0), 5),
                ("LEFTPADDING",  (0, 0), (-1, 0), 6),
                ("BOX",          (0, 0), (-1, 0), 0.5, colors.HexColor(tc)),
            ]))
            story.append(a_tbl)
            story.append(Spacer(1, 3))

    story.append(Spacer(1, 8))

    # ── AI assessment ─────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1,
                            color=colors.HexColor("#d0e4f0"), spaceAfter=6))
    story.append(Paragraph("AI Clinical Assessment  (Llama 3 via OpenRouter)", section_style))

    ai_bg_table = Table([[Paragraph(ai_text.replace("\n", "<br/>"), ai_style)]],
                        colWidths=[174*mm])
    ai_bg_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#f0f9ff")),
        ("BOX",           (0, 0), (-1, -1), 0.8, colors.HexColor("#00d4ff")),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(ai_bg_table)
    story.append(Spacer(1, 10))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1,
                            color=colors.HexColor("#d0e4f0"), spaceAfter=4))
    footer_style = ParagraphStyle("footer", fontSize=8, fontName="Helvetica",
                                  textColor=colors.HexColor("#4a6a88"),
                                  alignment=TA_CENTER)
    story.append(Paragraph(
        f"MediWatch Auto-Report  |  {DOCTOR_NAME}  |  ICU Ward 3  |  {timestamp}",
        footer_style))
    story.append(Paragraph(
        "This report is AI-assisted. All clinical decisions must be verified by a licensed physician.",
        footer_style))

    # ── Build ─────────────────────────────────────────────────────────────────
    doc.build(story)
    return filepath


# ── 6. Display in notebook ────────────────────────────────────────────────────
def display_data(data: dict, timestamp: str, alerts: list, ai: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  Timestamp    : {timestamp}")
    print(f"  Patient      : {PATIENT_NAME}  ({PATIENT_ID})")
    print(f"{'─' * 60}")
    print(f"  hr_pulse     : {data['hr_pulse']} BPM")
    print(f"  hr_max30100  : {data['hr_max30100']} BPM")
    print(f"  spo2         : {data['spo2']} %")
    print(f"  body_temp    : {data['body_temp']} C")
    print(f"  room_temp    : {data['room_temp']} C")
    print(f"  humidity     : {data['humidity']} %")
    for a in alerts:
        icon = "🚨" if "EMERGENCY" in a else "🔴" if "CRITICAL" in a else "🟡"
        print(f"  {icon} {a}")
    if ai:
        print(f"\n  🤖 AI Assessment:")
        for line in ai.split("\n"):
            print(f"     {line}")
    print(f"{'─' * 60}")


# ── 7. Post to dashboard ──────────────────────────────────────────────────────
def post_to_dashboard(data: dict, ai_text: str) -> None:
    try:
        payload = {
            "patient_id":        PATIENT_ID,
            "hr_pulse":          data["hr_pulse"],
            "hr_max30100":       data["hr_max30100"],
            "spo2":              data["spo2"],
            "body_temp":         data["body_temp"],
            "room_temp":         data["room_temp"],
            "humidity":          data["humidity"],
            "ai_interpretation": ai_text,
        }
        resp = requests.post(BACKEND_URL, json=payload, timeout=3)
        print(f"  Dashboard : {'OK' if resp.status_code == 200 else 'ERROR ' + str(resp.status_code)}")
    except requests.exceptions.ConnectionError:
        print("  Dashboard : Backend not reachable (is uvicorn running?)")
    except Exception as e:
        print(f"  Dashboard : POST failed — {e}")


# ── 8. Log to file ────────────────────────────────────────────────────────────
def log_to_file(data: dict, timestamp: str, alerts: list, ai: str) -> None:
    record = {"timestamp": timestamp, "data": data, "alerts": alerts, "ai_assessment": ai}
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


# ── 9. Main loop ──────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Wokwi Monitor  +  Llama 3 AI  +  PDF Report")
    print(f"  Patient   : {PATIENT_NAME} ({PATIENT_ID})")
    print(f"  Doctor    : {DOCTOR_NAME}")
    print(f"  Dashboard : http://localhost:5500/index.html")
    print(f"  Interval  : {POLL_INTERVAL}s")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)

    previous_data = None
    last_ai_text  = None

    while True:
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data      = get_simulated_vitals()   # 🔁 Replace with serial read
            alerts    = get_alerts(data)

            # Call AI only when vitals change significantly
            if has_changed(data, previous_data):
                if alerts:
                    print("\n  [AI] Getting assessment from Llama 3...")
                    last_ai_text = get_ai_interpretation(data, alerts)
                else:
                    last_ai_text = None
                previous_data = data.copy()

            display_data(data, timestamp, alerts, last_ai_text)
            post_to_dashboard(data, last_ai_text)

            # Generate PDF report every cycle
            print("\n  [PDF] Generating report...")
            pdf_path = generate_pdf_report(data, alerts, last_ai_text or "No alerts — all vitals normal.", timestamp)
            print(f"  [PDF] Saved → {pdf_path}")

            if LOG_TO_FILE:
                log_to_file(data, timestamp, alerts, last_ai_text)

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\n\nMonitoring stopped. Goodbye!")
            break


main()