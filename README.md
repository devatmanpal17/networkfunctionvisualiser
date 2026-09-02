# Network Function Visualiser

An interactive NFV (Network Function Virtualization) service-chain dashboard based on an ETSI-style architecture.

The model visualizes traffic flowing through:

- Client traffic sources
- Open vSwitch service-chain ingress
- Containerized vFirewall and vLoadBalancer VNFs
- Application server pool
- Ryu SDN control plane
- NFV MANO orchestration
- Shared compute, switching, and storage infrastructure

## Interactive features

- Adjustable traffic load
- MANO-style automatic VNF scaling
- vFirewall failure injection and recovery
- Animated packet flow
- Live throughput, latency, and compute-utilization metrics
- Responsive desktop and mobile layouts

## Run locally

Open `index.html` directly in a modern browser, or serve the repository:

```bash
python -m http.server 8765
```

Then visit `http://127.0.0.1:8765/`.

## Project files

- `index.html` - standalone runnable dashboard
- `output/nfv-lab-visualization.html` - editable visualization fragment
- `output/running-model/index.html` - packaged standalone build
