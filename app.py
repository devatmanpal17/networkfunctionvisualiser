from __future__ import annotations

import math
import random
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request


app = Flask(__name__)


@dataclass
class LabState:
    traffic: int = 58
    autoscale: bool = True
    firewall_failed: bool = False
    profile: str = "balanced"
    firewall_replicas: int = 3
    balancer_replicas: int = 3
    policy_target: int = 65
    tick: int = 0


PROFILES = {
    "balanced": {"name": "Balanced", "traffic": 58, "target": 65, "description": "General-purpose policy"},
    "latency": {"name": "Low latency", "traffic": 42, "target": 52, "description": "Scale early for responsiveness"},
    "efficiency": {"name": "Efficiency", "traffic": 66, "target": 78, "description": "Consolidate compute usage"},
}

state = LabState()
events: deque[dict] = deque(maxlen=16)
state_lock = threading.Lock()


def utc_time() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def record(kind: str, title: str, detail: str) -> None:
    events.appendleft({"time": utc_time(), "kind": kind, "title": title, "detail": detail})


def desired_replicas(traffic: int, target: int) -> int:
    return max(1, min(5, math.ceil(traffic / max(target / 2.2, 1))))


def snapshot() -> dict:
    with state_lock:
        state.tick += 1
        jitter = math.sin(state.tick / 3.2) * 1.5 + random.uniform(-0.6, 0.6)
        planned = desired_replicas(state.traffic, state.policy_target) if state.autoscale else state.firewall_replicas
        if state.autoscale:
            state.firewall_replicas = planned
            state.balancer_replicas = planned

        healthy_firewalls = max(0, state.firewall_replicas - int(state.firewall_failed))
        capacity = max(1, healthy_firewalls) * 29
        pressure = max(0, state.traffic - capacity)
        throughput = max(0.2, state.traffic * 0.109 - pressure * 0.055 - (0.9 if state.firewall_failed else 0))
        latency = 2.2 + state.traffic * 0.032 + pressure * 0.18 + (5.8 if state.firewall_failed else 0) + jitter * 0.08
        packet_loss = max(0.01, pressure * 0.045 + (1.8 if state.firewall_failed else 0))
        cpu = min(99, round(state.traffic / max(healthy_firewalls, 1) + 28 + jitter))
        memory = min(96, round(31 + state.firewall_replicas * 7 + state.traffic * 0.13))
        network = min(98, round(state.traffic * 0.91 + jitter))
        availability = 99.99 if not state.firewall_failed else max(96.8, 99.4 - packet_loss)
        status = "degraded" if state.firewall_failed or latency >= 12 else "healthy"

        return {
            **asdict(state),
            "profile_name": PROFILES[state.profile]["name"],
            "status": status,
            "metrics": {
                "throughput": round(throughput, 1),
                "latency": round(latency, 1),
                "packet_loss": round(packet_loss, 2),
                "availability": round(availability, 2),
                "cpu": cpu,
                "memory": memory,
                "network": network,
            },
            "nodes": [
                {"id": "edge", "name": "Edge", "detail": "12 sources", "status": "healthy", "replicas": 1},
                {"id": "switch", "name": "Open vSwitch", "detail": "SFC ingress", "status": "healthy", "replicas": 1},
                {"id": "firewall", "name": "vFirewall", "detail": "Policy enforcement", "status": "failed" if state.firewall_failed else "healthy", "replicas": healthy_firewalls},
                {"id": "balancer", "name": "vBalancer", "detail": "Traffic distribution", "status": "healthy", "replicas": state.balancer_replicas},
                {"id": "apps", "name": "App pool", "detail": "3 regions", "status": "healthy", "replicas": 3},
            ],
            "events": list(events),
            "profiles": PROFILES,
        }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def get_state():
    return jsonify(snapshot())


@app.post("/api/traffic")
def set_traffic():
    value = int(request.get_json(force=True).get("value", state.traffic))
    value = max(10, min(100, value))
    with state_lock:
        state.traffic = value
        record("traffic", "Traffic updated", f"Ingress load set to {value}%")
    return jsonify(snapshot())


@app.post("/api/autoscale")
def set_autoscale():
    enabled = bool(request.get_json(force=True).get("enabled", True))
    with state_lock:
        state.autoscale = enabled
        record("policy", "Autoscaling changed", "MANO policy enabled" if enabled else "Replica count fixed")
    return jsonify(snapshot())


@app.post("/api/profile")
def set_profile():
    profile = request.get_json(force=True).get("profile", "balanced")
    if profile not in PROFILES:
        return jsonify({"error": "Unknown profile"}), 400
    config = PROFILES[profile]
    with state_lock:
        state.profile = profile
        state.traffic = config["traffic"]
        state.policy_target = config["target"]
        record("policy", f"{config['name']} profile applied", config["description"])
    return jsonify(snapshot())


@app.post("/api/failure")
def toggle_failure():
    with state_lock:
        state.firewall_failed = not state.firewall_failed
        if state.firewall_failed:
            record("alert", "vFirewall replica unavailable", "MANO rerouted flows to healthy capacity")
        else:
            record("recovery", "vFirewall restored", "Service chain returned to nominal health")
    return jsonify(snapshot())


@app.post("/api/replicas")
def change_replicas():
    delta = int(request.get_json(force=True).get("delta", 0))
    with state_lock:
        if state.autoscale:
            return jsonify({"error": "Disable autoscaling to set replicas manually"}), 409
        state.firewall_replicas = max(1, min(5, state.firewall_replicas + delta))
        state.balancer_replicas = max(1, min(5, state.balancer_replicas + delta))
        record("scale", "Capacity adjusted", f"Service functions set to {state.firewall_replicas} replicas")
    return jsonify(snapshot())


record("system", "Lab ready", "Five-node service chain initialized")
record("policy", "Balanced profile applied", "Target utilization set to 65%")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=True)
