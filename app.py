"""
AI X-Ray Pneumonia Detection Prototype
---------------------------------------

Educational science-exhibition project.

Flask application:
- Workstation interface
- Live camera streaming
- Image capture
- Image upload (file picker)
- AI model integration through ai_model.py
"""

from flask import Flask, render_template, jsonify, request, send_file
from PIL import Image
import io
import time
import os

from ai_model import analyze_image
from report_generator import generate_report_id, generate_report_pdf


app = Flask(__name__)


# ---------------------------------------------------------------------------
# PROJECT INFORMATION
# ---------------------------------------------------------------------------

PROJECT_INFO = {
    "name": "AI X-Ray Pneumonia Detection",
    "subtitle": "Educational AI Medical Imaging Prototype",
    "badge": "Science Exhibition Prototype",
    "disclaimer": "AI-Assisted Analysis — Not for Medical Diagnosis",
}


SCAN_RESULT = {
    "prediction": "No Analysis Yet",
    "confidence": "0%",
    "risk_level": "Low",
    "risk_class": "low",
    "scan_time": "0s",
    "study": "Chest PA",
    "patient_id": "DEMO-EXHIBIT-001",
}


# ---------------------------------------------------------------------------
# LATEST ANALYSIS CACHE
#
# /generate_report needs the prediction/confidence/scan-time from the
# most recent successful analysis so it can build a PDF without
# re-running the model. _build_analysis_response() is the only place
# that populates this, so there is exactly one place where "the
# latest result" is defined.
# ---------------------------------------------------------------------------
LAST_ANALYSIS = {}

SYSTEM_INFO = [
    {
        "label": "Software Version",
        "value": "v1.0-edu"
    },
    {
        "label": "Camera Status",
        "value": "Standby",
        "state": "neutral"
    },
    {
        "label": "AI Model Status",
        "value": "Loaded",
        "state": "good"
    },
    {
        "label": "Backend Framework",
        "value": "Flask"
    },
    {
        "label": "Interface Mode",
        "value": "Exhibition Demo"
    },
]


WORKFLOW_STEPS = [
    {
        "number": "01",
        "title": "Capture or Upload",
        "description": "Capture a chest X-ray with the camera box, or upload an image file.",
        "icon": "capture",
    },
    {
        "number": "02",
        "title": "AI Analysis",
        "description": "EfficientNetV2 analyzes the X-ray pattern.",
        "icon": "analysis",
    },
    {
        "number": "03",
        "title": "Display Results",
        "description": "Prediction and confidence are displayed.",
        "icon": "results",
    },
]


FEATURES = [
    {
        "title": "AI Assisted",
        "description": "Machine learning based image analysis.",
        "icon": "cpu",
    },
    {
        "title": "Fast Analysis",
        "description": "Results generated within seconds.",
        "icon": "bolt",
    },
    {
        "title": "Modern Interface",
        "description": "Radiology workstation inspired design.",
        "icon": "layout",
    },
    {
        "title": "Educational Prototype",
        "description": "Built for science exhibition demonstration.",
        "icon": "book",
    },
]


# ---------------------------------------------------------------------------
# IMAGE STORAGE / UPLOAD CONFIGURATION
# ---------------------------------------------------------------------------

CAPTURE_DIR = os.path.join("static", "captured")
CAPTURE_FILENAME = "latest_capture.jpg"
CAPTURE_PATH = os.path.join(CAPTURE_DIR, CAPTURE_FILENAME)

# Only these extensions are accepted from the upload endpoint.
ALLOWED_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# Reasonable upload size ceiling (10 MB) so a stray huge file can't
# stall the exhibition kiosk.
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# SHARED AI ANALYSIS RESPONSE BUILDER
# ---------------------------------------------------------------------------
#
# Both /analyze (camera-captured image) and /upload (uploaded image)
# need to run the exact same prediction pipeline against
# static/captured/latest_capture.jpg and return the exact same JSON
# shape. This single helper is the ONLY place that calls
# ai_model.analyze_image() and formats a response, so there is no
# duplicated prediction logic between routes.

def _build_analysis_response(start_time):
    """
    Run AI analysis on the current captured/uploaded image and return
    a Flask JSON response in the standard success/failure shape.
    """

    if not os.path.exists(CAPTURE_PATH):

        return jsonify({
            "status": "error",
            "message": "No captured image found"
        })

    result = analyze_image(CAPTURE_PATH)

    # ai_model.py returned an error
    if "error" in result:

        return jsonify({
            "status": "error",
            "message": result["error"]
        })

    scan_time = round(
        time.time() - start_time,
        2
    )

    confidence = result["confidence"]

    # Cache the fields the PDF report needs. This is intentionally the
    # only place LAST_ANALYSIS is written, so /generate_report always
    # reflects exactly the result the user just saw on screen.
    LAST_ANALYSIS.update({
        "prediction": result["prediction"],
        "confidence": confidence,
        "scan_time": scan_time,
        "image_path": CAPTURE_PATH,
    })

    return jsonify({

    "status": "ok",

    "prediction": result["prediction"],

    "confidence": confidence,

    "risk": (
        "Moderate"
        if "Pneumonia" in result["prediction"]
        else "Low"
    ),

    "riskClass": (
        "moderate"
        if "Pneumonia" in result["prediction"]
        else "low"
    ),

    "scanTime": f"{scan_time}s"

})


# ---------------------------------------------------------------------------
# HOME PAGE
# ---------------------------------------------------------------------------

@app.route("/")
def index():

    system_info = [
        item.copy()
        for item in SYSTEM_INFO
    ]


    for item in system_info:
        if item["label"] == "Camera Status":
            item["value"] = "Browser Camera"
            item["state"] = "good"


    return render_template(
        "index.html",
        project=PROJECT_INFO,
        result=SCAN_RESULT,
        system_info=system_info,
        workflow_steps=WORKFLOW_STEPS,
        features=FEATURES,
    )

@app.route("/capture", methods=["POST"])
def capture():

    if "image" not in request.files:
        return jsonify({
            "status": "error",
            "message": "No camera image received"
        })

    os.makedirs(CAPTURE_DIR, exist_ok=True)

    image = Image.open(request.files["image"].stream)
    image = image.convert("RGB")
    image.save(CAPTURE_PATH, format="JPEG", quality=92)

    return jsonify({
        "status": "ok",
        "path": "/static/captured/latest_capture.jpg"
    })

# ---------------------------------------------------------------------------
# UPLOAD IMAGE (file picker)
# ---------------------------------------------------------------------------

@app.route("/upload", methods=["POST"])
def upload():

    start_time = time.time()


    if "image" not in request.files:

        return jsonify({
            "status": "error",
            "message": "No image file was included in the upload"
        })


    uploaded_file = request.files["image"]


    if uploaded_file.filename == "":

        return jsonify({
            "status": "error",
            "message": "No file selected"
        })


    _, ext = os.path.splitext(uploaded_file.filename)
    ext = ext.lower()


    if ext not in ALLOWED_UPLOAD_EXTENSIONS:

        return jsonify({
            "status": "error",
            "message": "Unsupported file type. Please upload a .jpg, .jpeg, or .png image."
        })


    try:

        os.makedirs(CAPTURE_DIR, exist_ok=True)

        # Open with Pillow and normalize to RGB JPEG regardless of the
        # source format (JPEG or PNG, including PNGs with an alpha
        # channel). This guarantees the file on disk is always a
        # valid latest_capture.jpg that ai_model.py can load.
        image = Image.open(uploaded_file.stream)
        image = image.convert("RGB")
        image.save(CAPTURE_PATH, format="JPEG", quality=92)

    except Exception as exc:

        return jsonify({
            "status": "error",
            "message": f"Failed to process uploaded image: {exc}"
        })


    # Same pipeline, same response shape as a camera capture.
    return _build_analysis_response(start_time)


# ---------------------------------------------------------------------------
# AI ANALYSIS (works for whichever image is currently at
# static/captured/latest_capture.jpg, camera-captured or uploaded)
# ---------------------------------------------------------------------------

@app.route("/analyze", methods=["POST"])
def analyze():

    start_time = time.time()

    return _build_analysis_response(start_time)


# ---------------------------------------------------------------------------
# PDF REPORT GENERATION
#
# Builds a PDF for the most recent successful analysis (cached in
# LAST_ANALYSIS by _build_analysis_response) and returns it as a
# downloadable file. All PDF layout/formatting lives in
# report_generator.py -- this route only gathers data and hands it
# off, so there is no report-formatting logic duplicated here.
# ---------------------------------------------------------------------------

@app.route("/generate_report", methods=["POST"])
def generate_report():

    if not LAST_ANALYSIS:

        return jsonify({
            "status": "error",
            "message": "No analysis has been run yet. Capture, upload, or "
                       "analyze an X-ray before generating a report."
        }), 400

    report_id = generate_report_id()

    pdf_bytes = generate_report_pdf(
        report_id=report_id,
        prediction=LAST_ANALYSIS["prediction"],
        confidence=LAST_ANALYSIS["confidence"],
        analysis_time=LAST_ANALYSIS["scan_time"],
        image_path=LAST_ANALYSIS.get("image_path"),
    )

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"ScanSense_Report_{report_id}.pdf",
    )



if __name__ == "__main__":

    app.run(
        debug=True
    )