# Arc / Network Observatory

A hands-on NFV and SDN learning lab. Turn up demand, lose a firewall replica, inspect a simulated attack, and follow how policy changes performance, capacity, and cost.

![Arc network observatory](output/previews/desktop-viewport.png)

## Run locally

From this project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:8765**. Stop with Ctrl+C. Python 3.10+ is required; verified with Python 3.13.

The root index.html is a launcher. The actual application is served by Flask from templates/index.html.

## Explore

- A live five-node service chain with animated flow and component explanations.
- Traffic control, three operating profiles, automatic/manual capacity, and replica failure.
- Actual two-second simulation history, metric selection, and SLA overlays.
- A pinned baseline with before/after performance and fictional cost comparisons.
- Flash-crowd, DDoS, and path-outage scenarios.
- Three guided missions with model-verified completion.
- Regional routing objectives with latency and modeled egress-cost trade-offs.
- Diagnostic sampling with PASS, BLOCK, and DROP records.
- Pause/resume, filtered event timeline, and JSON/CSV downloads.
- Cookie-isolated browser labs, request validation, and reconnect handling.
- Dark/light themes, keyboard controls, mobile navigation, and a built-in field guide.

All infrastructure, packets, threat counts, prices, and telemetry are **synthetic educational model outputs**. Arc does not run real Open vSwitch/Ryu/Docker services or perform attacks. State lives in memory and clears when the server restarts.

## Detailed project solution

- [Complete project guide](docs/PROJECT_GUIDE.md): purpose, technologies, components, architecture, request lifecycle, exact model equations, API, demonstrations, testing, and limitations.
- [Every function explained](docs/FUNCTION_REFERENCE.md): Python functions, JavaScript helpers/renderers, all UI event handlers, and tests.
- [Screenshots](output/previews): desktop, mobile, tablet, and field-guide views.

## Code map

| File | Responsibility |
| --- | --- |
| app.py | Flask factory, session registry, validation, API, downloads |
| simulation.py | Model state, clock, autoscaling, metrics, missions, diagnostics |
| templates/index.html | Canonical application UI |
| static/app.js | API binding, rendering, comparisons, events, retry behavior |
| static/styles.css / observatory.css | Base components and observatory design |
| tests/test_lab.py | 22 backend behavioral tests |
| tests/browser_smoke.py | Optional end-to-end browser verification |

Earlier standalone visualizations are preserved in output/.

## Verify

```powershell
python -m unittest discover -s tests -v
node --check static/app.js
```

Optional browser checks:

```powershell
python -m pip install -r requirements-dev.txt
python tests/browser_smoke.py
```

The browser test uses an installed Chrome/Edge on Windows; otherwise install a Playwright browser with python -m playwright install chromium or set ARC_BROWSER_EXECUTABLE. It serves a disposable test app on port 8770 and saves screenshots under output/previews.
