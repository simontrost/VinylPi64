from flask import Blueprint, current_app

pages_bp = Blueprint("pages", __name__)

@pages_bp.get("/")
def index():
    return current_app.send_static_file("index.html")

@pages_bp.get("/settings.html")
def settings_page():
    return current_app.send_static_file("settings.html")

@pages_bp.get("/stats.html")
def stats_page():
    return current_app.send_static_file("stats.html")

@pages_bp.get("/about.html")
def about_page():
    return current_app.send_static_file("about.html")

@pages_bp.get("/pixoo.html")
def pixoo_page():
    return current_app.send_static_file("pixoo.html")
