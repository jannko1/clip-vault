import json

def app(environ, start_response):
    """Minimal WSGI app — no Flask, no imports, no deps."""
    status = '200 OK'
    headers = [('Content-Type', 'application/json')]
    start_response(status, headers)
    return [json.dumps({"ok": True, "msg": "Minimal WSGI works!"}).encode()]