from flask import Flask, render_template_string, request, redirect, url_for, jsonify
from pathlib import Path
import json

CONFIG_PATH = Path("config.json")
STATUS_PATH = Path("/tmp/vinylpi_status.json") 

app = Flask(__name__)

def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}

def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=4), encoding="utf-8")

def rgb_list_to_hex(rgb_list):
    r, g, b = rgb_list
    return f"#{r:02x}{g:02x}{b:02x}"

def hex_to_rgb_list(hex_str):
    hex_str = hex_str.lstrip("#")
    r = int(hex_str[0:2], 16)
    g = int(hex_str[2:4], 16)
    b = int(hex_str[4:6], 16)
    return [r, g, b]

@app.route("/")
def index():
    cfg = load_config()
    img_cfg = cfg.get("image", {})
    fallback_cfg = cfg.get("fallback", {})

    text_color_hex = rgb_list_to_hex(img_cfg.get("text_color", [255, 255, 255]))
    bg_color_hex   = rgb_list_to_hex(img_cfg.get("manual_bg_color", [0, 0, 0]))
    fallback_path  = fallback_cfg.get("image_path", "")

    status = {}
    if STATUS_PATH.exists():
        status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))

    html = """
    <html>
    <head>
        <title>VinylPi Dashboard</title>
    </head>
    <body>
        <h1>VinylPi64 Dashboard</h1>

        <h2>Aktueller Song</h2>
        {% if status %}
            <p><b>{{ status.artist }}</b> – {{ status.title }}</p>
        {% else %}
            <p>Keine Daten vorhanden.</p>
        {% endif %}

        <h2>Text & Hintergrund</h2>
        <form method="post" action="{{ url_for('update_config') }}">
            <label>Textfarbe:</label>
            <input type="color" name="text_color" value="{{ text_color_hex }}"><br><br>

            <label>Manuelle Hintergrundfarbe:</label>
            <input type="color" name="bg_color" value="{{ bg_color_hex }}"><br><br>

            <label>Fallback-Bildpfad:</label>
            <input type="text" name="fallback_image" value="{{ fallback_path }}"><br><br>

            <label>Dynamic Background:</label>
            <input type="checkbox" name="use_dynamic_bg" {% if img_cfg.use_dynamic_bg %}checked{% endif %}><br>

            <label>Dynamic Text Color:</label>
            <input type="checkbox" name="use_dynamic_text_color" {% if img_cfg.use_dynamic_text_color %}checked{% endif %}><br><br>

            <button type="submit">Speichern</button>
        </form>
    </body>
    </html>
    """
    return render_template_string(html,
                                  text_color_hex=text_color_hex,
                                  bg_color_hex=bg_color_hex,
                                  fallback_path=fallback_path,
                                  img_cfg=img_cfg,
                                  status=status)

@app.route("/update", methods=["POST"])
def update_config():
    cfg = load_config()
    img_cfg = cfg.setdefault("image", {})
    fallback_cfg = cfg.setdefault("fallback", {})

    text_hex = request.form.get("text_color", "#ffffff")
    bg_hex   = request.form.get("bg_color", "#000000")
    fallback_image = request.form.get("fallback_image", "")

    img_cfg["text_color"] = hex_to_rgb_list(text_hex)
    img_cfg["manual_bg_color"] = hex_to_rgb_list(bg_hex)
    img_cfg["use_dynamic_bg"] = "use_dynamic_bg" in request.form
    img_cfg["use_dynamic_text_color"] = "use_dynamic_text_color" in request.form

    fallback_cfg["image_path"] = fallback_image

    save_config(cfg)


    return redirect(url_for("index"))

@app.route("/api/status")
def api_status():
    if STATUS_PATH.exists():
        return jsonify(json.loads(STATUS_PATH.read_text(encoding="utf-8")))
    return jsonify({"error": "no status"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
