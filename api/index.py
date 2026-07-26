"""Vercel serverless entry point for ClipVault."""
import sys, os, traceback, json

# Add parent to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Try importing — if it fails, return a diagnostic response
try:
    from app import app
except Exception as e:
    # Create a minimal Flask app that shows the error
    from flask import Flask
    app = Flask(__name__)
    
    @app.route("/")
    @app.route("/<path:path>")
    def error_page(path=""):
        return json.dumps({
            "error": "Import failed",
            "detail": str(e),
            "trace": traceback.format_exc().split("\n")[-5:]
        }), 500, {"Content-Type": "application/json"}
