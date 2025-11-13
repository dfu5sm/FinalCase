import os
import colorsys
import json
import sqlite3
from datetime import datetime

import numpy as np
from flask import Flask, request, jsonify, send_file, render_template_string
from PIL import Image

app = Flask(__name__)

DB_PATH = os.getenv("DB_PATH", "assets/results.db")
CSV_PATH = os.getenv("CSV_PATH", "assets/results.csv")
os.makedirs("assets", exist_ok=True)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            filename TEXT NOT NULL,
            mean_rgb TEXT NOT NULL,
            mean_hsv TEXT NOT NULL,
            hex TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def save_result_sqlite(filename, result):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO analyses (ts, filename, mean_rgb, mean_hsv, hex) VALUES (?, ?, ?, ?, ?)",
        (
            datetime.utcnow().isoformat(timespec="seconds") + "Z",
            filename,
            json.dumps(result["mean_rgb"]),
            json.dumps(result["mean_hsv"]),
            result["hex"],
        ),
    )
    conn.commit()
    conn.close()


def extract_mean_hsv(pil_img: Image.Image) -> dict:
    img = pil_img.convert("RGB")
    arr = np.array(img)
    if arr.size == 0:
        raise ValueError("Image has no pixels")

    pixels = arr.reshape(-1, 3)
    mean_rgb = pixels.mean(axis=0)
    r, g, b = mean_rgb / 255.0
    h, s, v = colorsys.rgb_to_hsv(r, g, b)

    mean_rgb_rounded = {
        "r": float(round(mean_rgb[0], 2)),
        "g": float(round(mean_rgb[1], 2)),
        "b": float(round(mean_rgb[2], 2)),
    }
    mean_hsv_rounded = {
        "h_degrees": float(round(h * 360.0, 2)),
        "s": float(round(s, 3)),
        "v": float(round(v, 3)),
    }
    hex_code = "#{:02x}{:02x}{:02x}".format(
        int(mean_rgb[0]), int(mean_rgb[1]), int(mean_rgb[2])
    )

    return {
        "mean_rgb": mean_rgb_rounded,
        "mean_hsv": mean_hsv_rounded,
        "hex": hex_code,
    }


@app.get("/")
def index():
    return """
    <html>
      <head><title>Image Color Extractor</title></head>
      <body style="font-family: Arial; margin: 40px;">
        <h1>Image Color Extractor</h1>
        <p>Upload an image to see its average color (RGB, HSV, and Hex).</p>
        <form action="/analyze" method="post" enctype="multipart/form-data">
          <input type="file" name="file" accept="image/*" required />
          <button type="submit">Analyze</button>
        </form>
        <p style="margin-top:20px;">
          <a href="/history">View recent results (JSON)</a> |
          <a href="/download/csv">Download CSV log</a>
        </p>
      </body>
    </html>
    """


@app.post("/analyze")
def analyze():
    uploaded = request.files.get("file")
    if uploaded is None or uploaded.filename == "":
        return jsonify({"error": "No file uploaded"}), 400

    try:
        img = Image.open(uploaded.stream)
        result = extract_mean_hsv(img)
        save_result_sqlite(uploaded.filename, result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Render HTML page showing the color visually
    html_template = """
    <html>
      <head><title>Analysis Result</title></head>
      <body style="font-family: Arial; margin: 40px;">
        <h2>Analysis Result for {{ filename }}</h2>
        <div style="display:flex; align-items:center; gap:20px;">
          <div style="width:150px; height:150px; background-color:{{ color }}; border:1px solid #000;"></div>
          <div>
            <p><strong>Average Color (Hex):</strong> {{ color }}</p>
            <p><strong>Average RGB:</strong> {{ rgb }}</p>
            <p><strong>Average HSV:</strong> {{ hsv }}</p>
          </div>
        </div>
        <br>
        <a href="/">Upload another image</a> |
        <a href="/history">View history</a>
      </body>
    </html>
    """
    return render_template_string(
        html_template,
        filename=uploaded.filename,
        color=result["hex"],
        rgb=result["mean_rgb"],
        hsv=result["mean_hsv"],
    )


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.get("/history")
def history():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT ts, filename, mean_rgb, mean_hsv, hex FROM analyses ORDER BY id DESC LIMIT 50"
    ).fetchall()
    conn.close()
    data = [
        {
            "ts": ts,
            "filename": fn,
            "mean_rgb": json.loads(rgb_json),
            "mean_hsv": json.loads(hsv_json),
            "hex": hx,
        }
        for ts, fn, rgb_json, hsv_json, hx in rows
    ]
    return jsonify({"count": len(data), "items": data}), 200


@app.get("/download/csv")
def download_csv():
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", encoding="utf-8") as f:
            f.write("ts,filename,r,g,b,h_degrees,s,v,hex\n")
    return send_file(CSV_PATH, as_attachment=True, download_name="results.csv")


if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
