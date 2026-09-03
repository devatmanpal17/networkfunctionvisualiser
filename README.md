# Arc Network Lab

Arc is a Python-backed NFV service-chain simulator with a restrained, product-focused interface. It models traffic through Open vSwitch, virtual firewall and load-balancer functions, application nodes, and shared NFVI resources.

## Features

- Live throughput, latency, availability, packet-loss, and infrastructure metrics
- Three operating profiles with different autoscaling thresholds
- MANO-style automatic scaling and manual replica control
- Firewall failure injection, traffic rerouting, and service recovery
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
