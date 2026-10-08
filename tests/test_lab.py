"""Behavioral checks; run with python -m unittest discover -s tests -v."""
import csv
import io
import unittest
from concurrent.futures import ThreadPoolExecutor
from app import create_app
from simulation import Lab, desired_replicas


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.lab = Lab(self.clock)

    def test_repeated_reads_do_not_advance_clock_or_history(self):
        before = self.lab.snapshot()
        for _ in range(10):
            self.assertEqual(self.lab.snapshot(), before)

    def test_wall_clock_samples_every_two_seconds(self):
        self.clock.advance(7)
        state = self.lab.snapshot()
        self.assertEqual(state["elapsed"], 6)
        self.assertEqual([row["elapsed"] for row in state["history"]], [0, 2, 4, 6])

    def test_scaling_steps_respect_cooldown(self):
        self.lab.apply("autoscale", {"enabled": False})
        for _ in range(3):
            self.lab.apply("replicas", {"delta": -1})
        self.lab.apply("traffic", {"value": 100})
        self.lab.apply("autoscale", {"enabled": True})
        self.clock.advance(2)
        self.assertEqual(self.lab.snapshot()["firewall_replicas"], 2)
        self.clock.advance(4)
        self.assertEqual(self.lab.snapshot()["firewall_replicas"], 2)
        self.clock.advance(2)
        self.assertEqual(self.lab.snapshot()["firewall_replicas"], 3)

    def test_zero_firewalls_cannot_deliver_traffic(self):
        self.lab.apply("autoscale", {"enabled": False})
        for _ in range(3):
            self.lab.apply("replicas", {"delta": -1})
        state = self.lab.apply("failure", {})
        self.assertEqual(state["status"], "offline")
        self.assertEqual(state["metrics"]["throughput"], 0)
        self.assertEqual(state["metrics"]["packet_loss"], 100)
        self.assertEqual(state["metrics"]["availability"], 0)
        self.assertEqual(state["metrics"]["blocked_threats"], 0)

    def test_restore_recovers_capacity(self):
        self.lab.apply("failure", {})
        state = self.lab.apply("failure", {})
        self.assertEqual(state["status"], "healthy")
        self.assertEqual(state["metrics"]["healthy_firewalls"], 4)

    def test_pause_freezes_history_capture_and_scaling(self):
        self.lab.apply("security", {"capture": True})
        self.lab.apply("playback", {"paused": True})
        before = self.lab.snapshot()
        self.clock.advance(100)
        self.assertEqual(self.lab.snapshot(), before)
        self.lab.apply("playback", {"paused": False})
        self.clock.advance(2)
        after = self.lab.snapshot()
        self.assertEqual(after["elapsed"], 2)
        self.assertEqual(len(after["packets"]), 1)

    def test_packet_capture_stops_and_retains_samples(self):
        self.lab.apply("security", {"capture": True})
        self.clock.advance(6)
        captured = self.lab.snapshot()["packets"]
        self.assertEqual(len(captured), 3)
        self.lab.apply("security", {"capture": False})
        self.clock.advance(4)
        self.assertEqual(self.lab.snapshot()["packets"], captured)

    def test_scenarios_do_not_stack_incidents(self):
        self.lab.apply("scenario", {"scenario": "ddos"})
        state = self.lab.apply("scenario", {"scenario": "link"})
        self.assertFalse(state["ddos_active"])
        self.assertTrue(state["firewall_failed"])
        state = self.lab.apply("scenario", {"scenario": "flash"})
        self.assertFalse(state["firewall_failed"])
        self.assertEqual(state["traffic"], 94)

    def test_clear_preserves_policies(self):
        self.lab.apply("routing", {"mode": "cost"})
        self.lab.apply("security", {"capture": True, "encryption": False})
        self.lab.apply("scenario", {"scenario": "ddos"})
        state = self.lab.apply("scenario", {"scenario": "reset"})
        self.assertEqual(state["traffic"], 58)
        self.assertFalse(state["ddos_active"])
        self.assertEqual(state["routing_mode"], "cost")
        self.assertTrue(state["capture_enabled"])
        self.assertFalse(state["encryption"])

    def test_missions_require_observed_outcomes(self):
        self.lab.apply("scenario", {"scenario": "flash"})
        self.assertEqual(self.lab.snapshot()["completed"], [])
        self.clock.advance(2)
        self.assertIn("scale", self.lab.snapshot()["completed"])
        self.lab.apply("scenario", {"scenario": "link"})
        self.clock.advance(2)
        self.assertIn("resilience", self.lab.snapshot()["completed"])
        self.lab.apply("scenario", {"scenario": "ddos"})
        self.clock.advance(2)
        self.assertNotIn("security", self.lab.snapshot()["completed"])
        self.lab.apply("security", {"capture": True})
        self.clock.advance(6)
        self.assertEqual(self.lab.snapshot()["completed"], ["resilience", "scale", "security"])

    def test_high_load_and_loss_reduce_delivered_throughput(self):
        self.lab.apply("autoscale", {"enabled": False})
        for _ in range(3):
            self.lab.apply("replicas", {"delta": -1})
        state = self.lab.apply("traffic", {"value": 100})
        self.assertGreater(state["metrics"]["packet_loss"], 1)
        self.assertLessEqual(state["metrics"]["throughput"], 2.9)
        self.assertFalse(state["sla"]["loss"])

    def test_routing_changes_weights_latency_and_inspection_overhead(self):
        adaptive = self.lab.snapshot()["metrics"]["latency"]
        latency = self.lab.apply("routing", {"mode": "latency"})
        self.assertLess(latency["metrics"]["latency"], adaptive)
        self.assertEqual([r["share"] for r in latency["regions"]], [65, 25, 10])
        no_tls = self.lab.apply("security", {"encryption": False})
        self.assertAlmostEqual(latency["metrics"]["latency"] - no_tls["metrics"]["latency"], 1.4)
        cheaper = self.lab.apply("routing", {"mode": "cost"})
        self.assertLess(cheaper["metrics"]["hourly_cost"], no_tls["metrics"]["hourly_cost"])
        self.assertGreater(cheaper["metrics"]["latency"], no_tls["metrics"]["latency"])

    def test_bounded_history_packets_events_and_long_idle_catchup(self):
        self.lab.apply("security", {"capture": True})
        self.clock.advance(10000)
        state = self.lab.snapshot()
        self.assertEqual(state["elapsed"], 10000)
        self.assertEqual(len(state["history"]), 90)
        self.assertEqual(len(state["packets"]), 32)
        for _ in range(100):
            self.lab.apply("traffic", {"value": 58})
        self.assertEqual(len(self.lab.snapshot()["events"]), 80)

    def test_atomic_concurrent_commands(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _: self.lab.apply("failure", {}), range(40)))
        self.assertEqual(self.lab.snapshot()["revision"], 40)
        self.assertFalse(self.lab.snapshot()["firewall_failed"])

    def test_replica_limits_and_policy_formula(self):
        self.assertEqual(desired_replicas(58, 65), 4)
        self.assertEqual(desired_replicas(1000, 65), 5)
        self.lab.apply("autoscale", {"enabled": False})
        for _ in range(10):
            self.lab.apply("replicas", {"delta": -1})
        self.assertEqual(self.lab.snapshot()["firewall_replicas"], 1)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test-key"})
        self.client = self.app.test_client()

    def test_page_assets_and_headers(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Catch the intruder", page.data)
        for path in ["/static/app.js", "/static/styles.css", "/static/observatory.css"]:
            with self.client.get(path) as asset:
                self.assertEqual(asset.status_code, 200)
        response = self.client.get("/api/state")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])

    def test_sessions_are_isolated_and_persist_with_cookie(self):
        second = self.app.test_client()
        initial = self.client.get("/api/state").json
        self.client.post("/api/traffic", json={"value": 100})
        self.assertEqual(self.client.get("/api/state").json["traffic"], 100)
        other = second.get("/api/state").json
        self.assertEqual(other["traffic"], 58)
        self.assertNotEqual(initial["lab_id"], other["lab_id"])

    def test_invalid_payloads_return_json_without_mutation(self):
        cases = [
            ("traffic", {"value": "60"}), ("traffic", {"value": True}),
            ("traffic", {"value": 10.5}), ("traffic", {"value": 101}),
            ("traffic", {}), ("traffic", {"value": 60, "extra": 1}),
            ("autoscale", {"enabled": "false"}), ("profile", {"profile": "invalid"}),
            ("replicas", {"delta": 100}), ("routing", {"mode": []}),
            ("security", {"capture": "false"}), ("security", {}),
            ("scenario", {"scenario": "unknown"}), ("playback", {"paused": 1}),
            ("failure", {"extra": 1}),
        ]
        before = self.client.get("/api/state").json["revision"]
        for action, body in cases:
            with self.subTest(action=action, body=body):
                response = self.client.post("/api/" + action, json=body)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json)
        self.assertEqual(self.client.get("/api/state").json["revision"], before)

    def test_malformed_non_object_and_oversized_json(self):
        for kwargs in [dict(data="{", content_type="application/json"), dict(json=[]),
                       dict(data="abc", content_type="text/plain"), dict(json=None)]:
            response = self.client.post("/api/traffic", **kwargs)
            self.assertEqual(response.status_code, 400)
            self.assertIn("error", response.json)
        response = self.client.post("/api/traffic", data=" " * 5000, content_type="application/json")
        self.assertEqual(response.status_code, 413)
        self.assertIn("error", response.json)

    def test_manual_scaling_conflict_and_valid_commands(self):
        self.assertEqual(self.client.post("/api/replicas", json={"delta": -1}).status_code, 409)
        self.client.post("/api/autoscale", json={"enabled": False})
        self.assertEqual(self.client.post("/api/replicas", json={"delta": -1}).json["firewall_replicas"], 3)
        self.assertEqual(self.client.post("/api/missing", json={}).status_code, 404)
        for action, body in [("profile", {"profile": "latency"}), ("routing", {"mode": "cost"}),
                             ("security", {"capture": True}), ("playback", {"paused": True}),
                             ("scenario", {"scenario": "ddos"}), ("failure", {})]:
            self.assertEqual(self.client.post("/api/" + action, json=body).status_code, 200)

    def test_exports_are_parseable_and_match_session(self):
        self.client.post("/api/traffic", json={"value": 73})
        report = self.client.get("/api/export")
        self.assertEqual(report.json["traffic"], 73)
        self.assertEqual(report.json["report"]["version"], 2)
        self.assertIn("attachment", report.headers["Content-Disposition"])
        csv_response = self.client.get("/api/export?format=csv")
        rows = list(csv.DictReader(io.StringIO(csv_response.data.decode())))
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0]["effective_demand"]), 73)
        self.assertEqual(self.client.get("/api/export?format=xml").status_code, 400)

    def test_session_registry_is_bounded(self):
        for _ in range(130):
            self.app.test_client().get("/api/state")
        self.assertEqual(len(self.app.extensions["arc_labs"]), 128)


if __name__ == "__main__":
    unittest.main()
