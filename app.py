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
    routing_mode: str = "adaptive"
    encryption: bool = True
    ddos_active: bool = False
    capture_enabled: bool = False
    selected_node: str = "firewall"
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
        attack_pressure = 18 if state.ddos_active else 0
        route_factor = {"adaptive": 0.82, "latency": 0.72, "cost": 1.08}[state.routing_mode]
        packet_loss = max(0.01, pressure * 0.045 + (1.8 if state.firewall_failed else 0) + attack_pressure * 0.025)
        cpu = min(99, round(state.traffic / max(healthy_firewalls, 1) + 28 + jitter))
        memory = min(96, round(31 + state.firewall_replicas * 7 + state.traffic * 0.13))
        network = min(98, round(state.traffic * 0.91 + jitter))
        latency = latency * route_factor + (1.4 if state.encryption else 0) + attack_pressure * .04
        availability = 99.99 if not state.firewall_failed else max(96.8, 99.4 - packet_loss)
        status = "degraded" if state.firewall_failed or state.ddos_active or latency >= 12 else "healthy"
        active_flows = round((state.traffic * 183 + jitter * 14) * (1.22 if state.ddos_active else 1))
        queue_depth = max(2, round(pressure * 8.4 + attack_pressure * 3 + random.uniform(0, 8)))
        hourly_cost = round((state.firewall_replicas + state.balancer_replicas) * 0.19 + 0.46, 2)
        energy = round(72 + cpu * 1.45 + state.balancer_replicas * 11, 0)
        blocked_threats = round(48 + state.traffic * .7 + (740 if state.ddos_active else 0))

        return {
            **asdict(state),
            "profile_name": PROFILES[state.profile]["name"],
            "status": status,
            "metrics": {
                "throughput": round(throughput, 1),
                "latency": round(latency, 1),
                "packet_loss": round(packet_loss, 2),
                "availability": round(availability, 2),
                "p95_latency": round(latency * 1.42, 1),
                "cpu": cpu,
                "memory": memory,
                "network": network,
                "active_flows": active_flows,
                "queue_depth": queue_depth,
                "hourly_cost": hourly_cost,
                "energy": energy,
                "blocked_threats": blocked_threats,
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
            "regions": [
                {"name": "Mumbai", "code": "BOM", "share": 44, "latency": round(latency * .82, 1), "status": "healthy"},
                {"name": "Singapore", "code": "SIN", "share": 34, "latency": round(latency * 1.08, 1), "status": "healthy"},
                {"name": "Frankfurt", "code": "FRA", "share": 22, "latency": round(latency * 1.65, 1), "status": "degraded" if state.firewall_failed else "healthy"},
            ],
            "traffic_mix": [
                {"name": "HTTPS", "value": 56, "color": "blue"},
                {"name": "API", "value": 27, "color": "purple"},
                {"name": "Streaming", "value": 12, "color": "green"},
                {"name": "Other", "value": 5, "color": "gray"},
            ],
            "decisions": [
                {"label": "Route selection", "value": state.routing_mode.title(), "reason": "Lowest weighted path score"},
                {"label": "Scale decision", "value": f"{planned} replicas", "reason": f"Target utilization {state.policy_target}%"},
                {"label": "Security action", "value": "Mitigating" if state.ddos_active else "Observe", "reason": f"{blocked_threats} threats blocked"},
            ],
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


@app.post("/api/routing")
def set_routing():
    mode = request.get_json(force=True).get("mode", "adaptive")
    if mode not in {"adaptive", "latency", "cost"}:
        return jsonify({"error": "Unknown routing mode"}), 400
    with state_lock:
        state.routing_mode = mode
        record("route", "Routing policy changed", f"Path selection now optimizes for {mode}")
    return jsonify(snapshot())


@app.post("/api/security")
def set_security():
    data = request.get_json(force=True)
    with state_lock:
        if "encryption" in data:
            state.encryption = bool(data["encryption"])
            record("security", "Encryption policy updated", "TLS inspection enabled" if state.encryption else "TLS inspection bypassed")
        if "capture" in data:
            state.capture_enabled = bool(data["capture"])
            record("security", "Packet capture updated", "Diagnostic capture running" if state.capture_enabled else "Diagnostic capture stopped")
    return jsonify(snapshot())


@app.post("/api/scenario")
def run_scenario():
    scenario = request.get_json(force=True).get("scenario", "reset")
    with state_lock:
        if scenario == "flash":
            state.traffic = 94
            state.ddos_active = False
            record("traffic", "Flash crowd detected", "Legitimate demand rose to 94%; scaling policy engaged")
        elif scenario == "ddos":
            state.traffic = 86
            state.ddos_active = True
            record("alert", "Volumetric attack detected", "Firewall rate limits and adaptive routing engaged")
        elif scenario == "link":
            state.firewall_failed = True
            record("alert", "Primary service path lost", "Flows shifted to the surviving firewall replicas")
        elif scenario == "reset":
            state.traffic = PROFILES[state.profile]["traffic"]
            state.ddos_active = False
            state.firewall_failed = False
            record("recovery", "Scenario cleared", "Traffic and service health returned to baseline")
        else:
            return jsonify({"error": "Unknown scenario"}), 400
    return jsonify(snapshot())


record("system", "Lab ready", "Five-node service chain initialized")
record("policy", "Balanced profile applied", "Target utilization set to 65%")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=True)
