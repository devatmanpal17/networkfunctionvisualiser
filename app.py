"""Flask delivery and strict JSON API for Arc Network Lab."""
from __future__ import annotations

import csv
import io
import os
import secrets
import threading
import time
from collections import OrderedDict
from flask import Flask, Response, jsonify, render_template, request, session
from werkzeug.exceptions import BadRequest, UnsupportedMediaType
from simulation import Lab, PROFILES


def create_app(test_config=None):
    """Create an app with a bounded in-memory browser-session registry."""
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.environ.get("ARC_SECRET_KEY") or secrets.token_hex(32),
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", MAX_CONTENT_LENGTH=4096)
    if test_config:
        app.config.update(test_config)
    labs = OrderedDict()
    registry_lock = threading.Lock()
    app.extensions["arc_labs"] = labs

    def get_lab():
        """Get this cookie's lab; evict after six inactive hours or 128 entries."""
        with registry_lock:
            now = time.monotonic()
            for key in [key for key, (_, touched) in labs.items() if now - touched > 21600]:
                del labs[key]
            identity = session.get("lab_id")
            if identity not in labs:
                identity = secrets.token_hex(16)
                session["lab_id"] = identity
                labs[identity] = (Lab(), now)
            lab, _ = labs[identity]
            labs[identity] = (lab, now)
            labs.move_to_end(identity)
            while len(labs) > 128:
                labs.popitem(last=False)
            return lab

    def json_body():
        """Reject invalid JSON and values that aren't objects."""
        try:
            data = request.get_json()
        except (BadRequest, UnsupportedMediaType):
            raise ValueError("Send a valid JSON object with Content-Type: application/json.")
        if not isinstance(data, dict):
            raise ValueError("The request body must be a JSON object.")
        return data

    def validate(action, data):
        """Validate exact keys, types, ranges, and command choices."""
        specs = {
            "traffic": ("value", int, range(10, 101)),
            "autoscale": ("enabled", bool, None),
            "profile": ("profile", str, PROFILES),
            "replicas": ("delta", int, {-1, 1}),
            "routing": ("mode", str, {"adaptive", "latency", "cost"}),
            "scenario": ("scenario", str, {"flash", "ddos", "link", "reset"}),
            "playback": ("paused", bool, None),
        }
        if action == "failure":
            if data:
                raise ValueError("Failure expects an empty JSON object.")
        elif action == "security":
            if not data or set(data) - {"encryption", "capture"} or any(type(v) is not bool for v in data.values()):
                raise ValueError("Security expects encryption and/or capture as booleans.")
        else:
            key, kind, allowed = specs[action]
            if set(data) != {key} or type(data[key]) is not kind:
                raise ValueError(f"Provide only '{key}' with type {kind.__name__}.")
            if allowed is not None and data[key] not in allowed:
                raise ValueError(f"Invalid {key}; check the documented range or choices.")
        return data

    @app.get("/")
    def index():
        """Render the canonical app without external asset dependencies."""
        return render_template("index.html")

    @app.get("/api/state")
    def get_state():
        """Read this session's telemetry and history."""
        return jsonify(get_lab().snapshot())

    @app.post("/api/<action>")
    def command(action):
        """Validate and dispatch mutations, returning JSON errors."""
        if action not in {"traffic", "autoscale", "profile", "failure", "replicas", "routing", "security", "scenario", "playback"}:
            return jsonify(error="Unknown command."), 404
        try:
            data = validate(action, json_body())
            return jsonify(get_lab().apply(action, data))
        except ValueError as error:
            return jsonify(error=str(error)), 409 if action == "replicas" and "Disable" in str(error) else 400

    @app.get("/api/export")
    def export_report():
        """Download session JSON or telemetry history as CSV."""
        data = get_lab().snapshot()
        if request.args.get("format", "json") == "csv":
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fieldnames=list(data["history"][0]))
            writer.writeheader()
            writer.writerows(data["history"])
            return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=arc-telemetry.csv"})
        if request.args.get("format", "json") != "json":
            return jsonify(error="Export format must be json or csv."), 400
        data["report"] = {"name": "Arc Network Lab", "model": "Educational synthetic telemetry; no real packets or infrastructure.", "version": 2}
        response = jsonify(data)
        response.headers["Content-Disposition"] = "attachment; filename=arc-lab-report.json"
        return response

    @app.after_request
    def response_headers(response):
        """Prevent stale API responses and add local-app browser protection."""
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
        return response

    @app.errorhandler(413)
    def too_large(error):
        """Return a JSON error when a command exceeds the 4 KiB input limit."""
        return jsonify(error="Request too large. Maximum body size is 4 KiB."), 413

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False)
