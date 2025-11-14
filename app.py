"""
WattCompare Backend API (PyTesseract OCR + Energy Analysis)
Author: Astronaut 🌍

Features:
- OCR using PyTesseract (multilingual supported)
- Extracts kWh/year or kW from energy labels
- Stores appliances in SQLite
- Compare two appliances (cost + carbon footprint)
- PDF report export
- Backend only (API endpoints)
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import pytesseract
import cv2
import numpy as np
import re
import sqlite3
import os
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

app = Flask(__name__)
CORS(app)
DB_FILE = "wattcompare.db"

# Tell PyTesseract where the binary is located (Render installs it system-wide)
pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"

# ---------------- Database Setup ----------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS appliances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        energy_kwh REAL,
        price REAL,
        energy_rate REAL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------------- OCR Extraction ----------------
def extract_energy_from_image(image_bytes):
    np_img = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 75, 75)

    text = pytesseract.image_to_string(gray, lang="eng+hin+tam+tel+fra+deu+spa+ita+por+jpn+kor+ara")

    text_low = text.lower()

    # Look for patterns: 250 kwh, 300 kwh/year, 0.8 kw
    match = re.search(r"(\d+\.?\d*)\s*(kwh|kw)", text_low)

    if match:
        val = float(match.group(1))
        unit = match.group(2)

        if unit == "kw":
            # Convert kW → kWh/year
            val = (val * 24 * 365)

        return val, text

    return None, text

# ---------------- API Routes ----------------
@app.route("/")
def home():
    return jsonify({
        "message": "🌍 WattCompare Backend (PyTesseract Version)",
        "endpoints": {
            "POST /ocr": "Upload image → returns detected kWh/kW",
            "POST /add_appliance": "Save appliance",
            "GET /list_appliances": "List all appliances",
            "POST /compare": "Compare two appliances",
            "GET /export_pdf": "Download PDF report"
        }
    })

@app.route("/ocr", methods=["POST"])
def ocr_route():
    if "image" not in request.files:
        return jsonify({"error": "No image uploaded"}), 400

    img = request.files["image"].read()
    energy, raw = extract_energy_from_image(img)

    return jsonify({
        "energy_kwh": energy,
        "raw_text": raw
    })

@app.route("/add_appliance", methods=["POST"])
def add_appliance():
    name = request.form.get("name")
    price = float(request.form.get("price", 0))
    energy_rate = float(request.form.get("energy_rate", 0))
    image = request.files.get("image")

    energy_kwh = None
    if image:
        energy_kwh, _ = extract_energy_from_image(image.read())

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT INTO appliances (name, energy_kwh, price, energy_rate) VALUES (?, ?, ?, ?)",
                (name, energy_kwh, price, energy_rate))
    conn.commit()
    conn.close()

    return jsonify({"message": "Saved", "name": name, "energy_kwh": energy_kwh})

@app.route("/list_appliances", methods=["GET"])
def list_appliances():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM appliances")
    rows = cur.fetchall()
    conn.close()

    return jsonify([
        {
            "id": r[0], "name": r[1],
            "energy_kwh": r[2], "price": r[3],
            "energy_rate": r[4], "timestamp": r[5]
        } for r in rows
    ])

@app.route("/compare", methods=["POST"])
def compare():
    ids = request.json.get("ids")
    if not ids or len(ids) != 2:
        return jsonify({"error": "Exactly 2 IDs required"}), 400

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM appliances WHERE id IN (?, ?)", (ids[0], ids[1]))
    rows = cur.fetchall()
    conn.close()

    if len(rows) != 2:
        return jsonify({"error": "Invalid appliance IDs"}), 404

    a1, a2 = rows

    def total_cost(a):
        if a[2] and a[4]:
            return a[2] * a[4]
        return None

    cost1 = total_cost(a1)
    cost2 = total_cost(a2)

    carbon1 = cost1 * 0.82 if cost1 else None
    carbon2 = cost2 * 0.82 if cost2 else None

    recommended = a1 if cost1 < cost2 else a2

    return jsonify({
        "compare": {
            "A": {"name": a1[1], "annual_cost": cost1, "carbon": carbon1},
            "B": {"name": a2[1], "annual_cost": cost2, "carbon": carbon2},
            "recommended": recommended[1]
        }
    })

@app.route("/export_pdf", methods=["GET"])
def export_pdf():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT name, energy_kwh, price, energy_rate FROM appliances")
    data = cur.fetchall()
    conn.close()

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(200, 800, "⚡ WattCompare Report")

    pdf.setFont("Helvetica", 12)
    y = 770
    for row in data:
        pdf.drawString(40, y, f"Name: {row[0]} | Energy: {row[1]} kWh | Price: {row[2]} | Rate: {row[3]}")
        y -= 20
        if y < 100:
            pdf.showPage()
            y = 800

    pdf.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name="WattCompare_Report.pdf",
                     mimetype="application/pdf")

# ---------------- Main ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Running on port {port}")
    app.run(host="0.0.0.0", port=port)
