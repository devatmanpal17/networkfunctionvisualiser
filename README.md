# Arc Network Lab

Arc is a Python-backed NFV service-chain simulator with a restrained, product-focused interface. It models traffic through Open vSwitch, virtual firewall and load-balancer functions, application nodes, and shared NFVI resources.

## Features

- Live throughput, latency, availability, packet-loss, and infrastructure metrics
- Three operating profiles with different autoscaling thresholds
- MANO-style automatic scaling and manual replica control
- Firewall failure injection, traffic rerouting, and service recovery
- Flash-crowd, DDoS mitigation, and primary-path outage scenarios
- Adaptive, latency-first, and cost-first routing objectives
- Regional traffic and latency analysis across Mumbai, Singapore, and Frankfurt
- Selectable topology nodes with control-plane and data-plane context
- Protocol composition, active-flow, queue-depth, energy, and hourly cost telemetry
- TLS inspection and diagnostic packet-capture controls
- An explainable decision engine for routing, scaling, and security actions
- Server-side simulation state and an event timeline
- Responsive light and dark interfaces

## Run locally

```bash
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8765`.

## Structure

- `app.py` — Flask application, simulation engine, and JSON API
- `templates/index.html` — application interface
- `static/styles.css` — visual system and responsive layout
- `static/app.js` — API binding and interface interactions
