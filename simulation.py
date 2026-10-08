"""Deterministic educational NFV model. No real network traffic is generated."""
from __future__ import annotations

import math
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

PROFILES = {
    "balanced": {"name": "Balanced", "traffic": 58, "target": 65, "description": "A measured balance of headroom and compute cost."},
    "latency": {"name": "Low latency", "traffic": 42, "target": 52, "description": "Reserve more capacity to keep response times low."},
    "efficiency": {"name": "Efficiency", "traffic": 66, "target": 78, "description": "Use fewer instances at higher utilization."},
}
SAMPLE_SECONDS = 2
COOLDOWN_SECONDS = 6
REPLICA_CAPACITY = 29
ROUTES = {
    "adaptive": {"factor": .82, "shares": [44, 34, 22]},
    "latency": {"factor": .72, "shares": [65, 25, 10]},
    "cost": {"factor": 1.08, "shares": [25, 25, 50]},
}


@dataclass
class LabState:
    traffic: int = 58
    autoscale: bool = True
    firewall_failed: bool = False
    profile: str = "balanced"
    firewall_replicas: int = 4
    balancer_replicas: int = 4
    policy_target: int = 65
    routing_mode: str = "adaptive"
    encryption: bool = True  # Historical API name: enables modeled TLS inspection.
    ddos_active: bool = False
    capture_enabled: bool = False
    paused: bool = False
    scenario: str = "baseline"
    tick: int = 0


def desired_replicas(traffic: float, target: int) -> int:
    """Capacity needed to keep per-instance utilization near the target."""
    return max(1, min(5, math.ceil(traffic / (REPLICA_CAPACITY * target / 100))))


class Lab:
    """One browser session's state, bounded telemetry, and atomic mutations."""

    def __init__(self, clock=time.monotonic):
        self.state = LabState()
        self.identity = uuid.uuid4().hex
        self.clock = clock
        self.last_sample = clock()
        self.last_scale = -COOLDOWN_SECONDS
        self.lock = threading.RLock()
        self.events = deque(maxlen=80)
        self.history = deque(maxlen=90)
        self.packets = deque(maxlen=32)
        self.revision = 0
        self.completed = set()
        self.record("system", "Your lab is ready", "An isolated, simulated five-node service chain.")
        self.sample()

    def record(self, kind: str, title: str, detail: str):
        """Prepend a timestamped event; callers hold the lab lock."""
        self.events.appendleft({"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "elapsed": self.state.tick * SAMPLE_SECONDS,
                                "kind": kind, "title": title, "detail": detail})

    def demand(self) -> float:
        """Rate-limited hostile demand adds 16 effective load units."""
        return self.state.traffic + (16 if self.state.ddos_active else 0)

    def scale(self):
        """Move one replica toward the target every six simulated seconds."""
        s = self.state
        if not s.autoscale:
            return
        target = min(5, desired_replicas(self.demand(), s.policy_target) + int(s.firewall_failed))
        elapsed = s.tick * SAMPLE_SECONDS
        if target != s.firewall_replicas and elapsed - self.last_scale >= COOLDOWN_SECONDS:
            s.firewall_replicas += 1 if target > s.firewall_replicas else -1
            s.balancer_replicas = s.firewall_replicas
            self.last_scale = elapsed
            self.record("scale", "MANO adjusted capacity", f"{s.firewall_replicas} replicas per VNF; desired {target}, target {s.policy_target}%.")

    def metrics(self) -> dict:
        """Derive telemetry from demand, available capacity, and policies."""
        s = self.state
        healthy = max(0, s.firewall_replicas - int(s.firewall_failed))
        capacity = min(healthy, s.balancer_replicas) * REPLICA_CAPACITY
        demand = self.demand()
        pressure = max(0, demand - capacity)
        jitter = math.sin(s.tick / 3.2) * .12
        loss = 100.0 if capacity == 0 else min(100, .01 + pressure / demand * 100)
        throughput = min(10, s.traffic * .1 * (1 - loss / 100))
        latency = (2.2 + demand * .032 + pressure * .18 + (1.2 if s.firewall_failed else 0))
        latency *= ROUTES[s.routing_mode]["factor"]
        latency += (1.4 if s.encryption else 0) + (.7 if s.ddos_active else 0) + jitter
        # Fictional regional egress prices, in dollars per Gbps-hour.
        egress = s.traffic * .1 * sum(share / 100 * price for share, price in
                                    zip(ROUTES[s.routing_mode]["shares"], [.16, .12, .05]))
        compute_cost = (s.firewall_replicas + s.balancer_replicas) * .19 + .46
        return {
            "throughput": round(throughput, 2), "latency": round(max(0, latency), 2),
            "packet_loss": round(loss, 2), "availability": round(max(0, 99.99 - loss), 2),
            "p95_latency": round(latency * 1.42, 2),
            "cpu": min(100, round(demand / max(capacity, 1) * 100)),
            "memory": min(100, round(23 + s.firewall_replicas * 8 + demand * .12)),
            "network": min(100, round(demand)), "active_flows": round(demand * 183),
            "queue_depth": round(pressure * 8.4),
            "hourly_cost": round(compute_cost + egress, 2),
            "compute_cost": round(compute_cost, 2), "egress_cost": round(egress, 2),
            "energy": round(72 + demand * 1.2 + (s.firewall_replicas + s.balancer_replicas) * 11),
            "blocked_threats": round(48 + s.traffic * .7 + (740 if s.ddos_active else 0)) if healthy else 0,
            "capacity": capacity, "effective_demand": demand, "healthy_firewalls": healthy,
        }

    def sample(self):
        """Append a model sample and an optional synthetic packet row."""
        m = self.metrics()
        self.history.append({"elapsed": self.state.tick * SAMPLE_SECONDS, **m})
        if self.state.capture_enabled:
            protocol = ["HTTPS", "API", "HTTPS", "Streaming"][self.state.tick % 4]
            blocked = self.state.ddos_active and self.state.tick % 3 == 0
            self.packets.appendleft({"id": self.state.tick, "elapsed": self.state.tick * SAMPLE_SECONDS,
                                     "source": f"192.0.2.{10 + self.state.tick % 200}", "protocol": protocol,
                                     "bytes": 64 if blocked else 1200 + self.state.tick % 260,
                                     "action": "DROP" if not m["healthy_firewalls"] else "BLOCK" if blocked else "PASS"})
        if self.state.scenario == "flash" and self.state.autoscale and m["cpu"] <= self.state.policy_target:
            self.completed.add("scale")
        if self.state.scenario == "link" and self.state.firewall_failed and m["packet_loss"] < 1:
            self.completed.add("resilience")
        if self.state.scenario == "ddos" and self.state.capture_enabled and any(p["action"] == "BLOCK" for p in self.packets):
            self.completed.add("security")

    def advance(self):
        """Catch up wall time on access; repeated GETs cannot accelerate time."""
        now = self.clock()
        if self.state.paused:
            self.last_sample = now
            return
        steps = int((now - self.last_sample) / SAMPLE_SECONDS)
        if steps > 90:
            self.state.tick += steps - 90
            self.last_sample += (steps - 90) * SAMPLE_SECONDS
            steps = 90
        for _ in range(steps):
            self.state.tick += 1
            self.scale()
            self.sample()
            self.last_sample += SAMPLE_SECONDS

    def snapshot(self) -> dict:
        """Produce one consistent payload for the whole dashboard."""
        with self.lock:
            self.advance()
            s = self.state
            m = self.metrics()
            status = "offline" if m["healthy_firewalls"] == 0 else "degraded" if s.firewall_failed or s.ddos_active or m["packet_loss"] >= 1 or m["latency"] >= 20 else "healthy"
            desired = min(5, desired_replicas(self.demand(), s.policy_target) + int(s.firewall_failed))
            shares = ROUTES[s.routing_mode]["shares"]
            return {**asdict(s), "lab_id": self.identity, "revision": self.revision, "status": status, "metrics": m,
                    "elapsed": s.tick * SAMPLE_SECONDS, "profile_name": PROFILES[s.profile]["name"],
                    "profiles": PROFILES, "history": list(self.history), "events": list(self.events),
                    "packets": list(self.packets), "completed": sorted(self.completed),
                    "desired_replicas": desired, "cooldown_remaining": max(0, COOLDOWN_SECONDS - (s.tick * SAMPLE_SECONDS - self.last_scale)),
                    "nodes": [
                        {"id": "edge", "name": "Edge gateway", "detail": "12 simulated peers", "status": "healthy", "replicas": 1},
                        {"id": "switch", "name": "Open vSwitch", "detail": "Service-chain ingress", "status": "healthy", "replicas": 1},
                        {"id": "firewall", "name": "vFirewall", "detail": "1 replica unavailable" if s.firewall_failed else "Policy enforcement", "status": status if s.firewall_failed else "healthy", "replicas": m["healthy_firewalls"]},
                        {"id": "balancer", "name": "vBalancer", "detail": "Traffic distribution", "status": "healthy", "replicas": s.balancer_replicas},
                        {"id": "apps", "name": "Application pool", "detail": "3 modeled regions", "status": "offline" if status == "offline" else "healthy", "replicas": 3}],
                    "regions": [{"name": name, "code": code, "share": shares[i], "latency": round(m["latency"] * factor, 1), "status": status}
                                for i, (name, code, factor) in enumerate([("Mumbai", "BOM", .82), ("Singapore", "SIN", 1.08), ("Frankfurt", "FRA", 1.65)])],
                    "traffic_mix": [{"name": n, "value": v, "color": c} for n, v, c in
                                    ([("HTTPS", 36, "blue"), ("API", 17, "purple"), ("Streaming", 7, "green"), ("Hostile", 40, "red")] if s.ddos_active else
                                     [("HTTPS", 56, "blue"), ("API", 27, "purple"), ("Streaming", 12, "green"), ("Other", 5, "gray")])],
                    "decisions": [
                        {"label": "Route selection", "value": s.routing_mode.title(), "reason": f"Regional split: {shares[0]} / {shares[1]} / {shares[2]}%."},
                        {"label": "Scale decision", "value": f"{desired if s.autoscale else s.firewall_replicas} replicas", "reason": f"{m['cpu']}% compute load; target {s.policy_target}%." if s.autoscale else "Manual capacity; automatic scaling is disabled."},
                        {"label": "Security action", "value": "Rate limiting" if s.ddos_active else "Observing", "reason": f"{m['blocked_threats']} modeled threats blocked per sample."}],
                    "sla": {"latency": m["latency"] < 20, "loss": m["packet_loss"] < 1, "availability": m["availability"] >= 99},
                    }

    def apply(self, action: str, data: dict) -> dict:
        """Atomically apply a validated API command and return state."""
        with self.lock:
            self.advance()
            s = self.state
            if action == "traffic":
                s.traffic = data["value"]
                self.record("traffic", "Traffic adjusted", f"Ingress demand is {s.traffic}% of the 10 Gbps line.")
            elif action == "autoscale":
                s.autoscale = data["enabled"]
                self.record("policy", "Scaling policy updated", "MANO enabled." if s.autoscale else "Manual capacity enabled.")
            elif action == "profile":
                s.profile = data["profile"]
                config = PROFILES[s.profile]
                s.traffic, s.policy_target = config["traffic"], config["target"]
                self.record("policy", f"{config['name']} profile applied", config["description"])
            elif action == "failure":
                s.firewall_failed = not s.firewall_failed
                self.record("alert" if s.firewall_failed else "recovery", "Firewall failure injected" if s.firewall_failed else "Firewall restored", "One replica removed from healthy capacity." if s.firewall_failed else "All configured replicas are available.")
            elif action == "replicas":
                if s.autoscale:
                    raise ValueError("Disable autoscaling before changing replicas.")
                s.firewall_replicas = max(1, min(5, s.firewall_replicas + data["delta"]))
                s.balancer_replicas = s.firewall_replicas
                self.record("scale", "Manual capacity changed", f"{s.firewall_replicas} replicas per VNF.")
            elif action == "routing":
                s.routing_mode = data["mode"]
                self.record("route", "Routing objective changed", f"Regional weights now optimize for {s.routing_mode}.")
            elif action == "security":
                if "encryption" in data:
                    s.encryption = data["encryption"]
                if "capture" in data:
                    s.capture_enabled = data["capture"]
                self.record("security", "Inspection settings updated", f"TLS inspection {'on' if s.encryption else 'off'}; sampling {'on' if s.capture_enabled else 'off'}.")
            elif action == "playback":
                s.paused = data["paused"]
                self.last_sample = self.clock()
                self.record("system", "Simulation paused" if s.paused else "Simulation resumed", "Clock and packet sampling are frozen." if s.paused else "Two-second telemetry sampling resumed.")
            elif action == "scenario":
                scenario = data["scenario"]
                s.scenario = "baseline" if scenario == "reset" else scenario
                s.ddos_active = scenario == "ddos"
                s.firewall_failed = scenario == "link"
                s.traffic = {"flash": 94, "ddos": 86}.get(scenario, PROFILES[s.profile]["traffic"])
                self.record("recovery" if scenario == "reset" else "alert", {"flash": "Flash crowd arrived", "ddos": "DDoS scenario started", "link": "Primary firewall replica lost", "reset": "Scenario returned to baseline"}[scenario], "Watch capacity, SLA, and the decision engine respond.")
            self.revision += 1
            if self.history:
                self.history[-1] = {"elapsed": s.tick * SAMPLE_SECONDS, **self.metrics()}
            return self.snapshot()
