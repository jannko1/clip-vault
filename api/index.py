"""Vercel serverless entry point for ClipVault."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app import app
except Exception as e:
    import json, traceback
    def app(environ, start_response):
        body = json.dumps({"error": str(e), "trace": traceback.format_exc()})
        start_response('500 OK', [('Content-Type', 'application/json')])
        return [body.encode()]