# Arc — function-by-function code reference

This reference covers every explicitly named application function, test helper, and registered UI event handler. Python's dataclass-generated methods and library internals are not hand-written project functions.

For architecture, equations, API bodies, examples, and runtime limitations, read [PROJECT_GUIDE.md](PROJECT_GUIDE.md).

## 1. simulation.py

### Constants and LabState

- PROFILES holds each profile's display name, initial traffic, utilization target, and description.
- SAMPLE_SECONDS = 2 sets the telemetry interval.
- COOLDOWN_SECONDS = 6 sets the minimum time between automatic replica adjustments.
- REPLICA_CAPACITY = 29 sets the per-healthy-instance capacity in load units.
- ROUTES holds the latency factor and regional shares for each routing objective.
- LabState is a dataclass holding configuration and current incident flags. Dataclasses supplies an initializer and field representation; asdict() converts it to plain data for the API.

### desired_replicas(traffic, target) → int

Calculates ceil(traffic / (29 × target / 100)) and clamps the result to 1–5. Here traffic can mean effective demand including residual attack pressure. It is a pure function: it changes no state, records no events, and reads no clock.

Used by Lab.scale() and Lab.snapshot(). Failure compensation is added by those callers, keeping the utilization formula separate from the incident rule.

### Lab.__init__(clock=time.monotonic)

Creates an independent simulator with default LabState, a unique identity, a clock, an RLock, and bounded history/event/packet collections.

It initializes last_sample from the clock and last_scale to -6 so the first scaling adjustment can happen on the next sample. It sets mutation revision zero and an empty mission-completion set, records readiness, and stores the initial t=0 sample.

Injecting a callable clock lets tests advance time exactly without waiting for real seconds.

### Lab.record(kind, title, detail)

Adds a new event to the front of the 80-entry event deque. It stores an ISO UTC timestamp, current simulated elapsed time, event category, short title, and explanatory detail.

It does not alter the clock or revision. Normal callers already hold the lab lock; construction is private to a newly created Lab. Events use lab time visibly and actual wall time as the browser title tooltip.

### Lab.demand() → float

Returns legitimate traffic plus 16 load units when the attack flag is active. That fixed additional load represents hostile demand surviving the conceptual rate limiter. It is used consistently by scaling and metric formulas.

### Lab.scale()

Returns immediately when autoscaling is disabled. Otherwise it calculates the required pool size, adds one replica of compensation during a firewall failure, caps the result at five, and compares it with the current pool.

If the pool differs and six simulated seconds have passed since the last adjustment, it moves firewall replicas by one toward the target, sets balancer replicas to the same count, updates last_scale, and records the scaling event.

It runs only during simulation ticks, so pause freezes automatic changes. It deliberately changes one instance at a time rather than jumping straight to the desired size.

### Lab.metrics() → dict

The main numerical model. It reads state, finds healthy capacity and overload, and derives throughput, latency, packet loss, availability, p95 estimate, resource percentages, flows, queue, energy, threat estimate, and cost breakdown.

It also returns healthy_firewalls, capacity, and effective_demand so explanations and tests use the same quantities as the model. It calculates fictional egress cost from route shares and provisioned compute cost from replica counts.

There are no random numbers or side effects. The only tick-dependent variation is a small sine-wave latency term. The same configuration and tick produce the same values. Exact equations are in PROJECT_GUIDE.md.

### Lab.sample()

Appends the current metrics with elapsed time to the 90-point history deque.

If capture is enabled, it prepends one deterministic illustrative packet to the 32-record packet deque. An unavailable firewall pool produces DROP; every third attack tick can produce BLOCK; other records produce PASS.

It then evaluates the three mission conditions and adds successful mission IDs to a set. Conditions are checked on actual model samples, so applying a scenario alone does not immediately award completion.

### Lab.advance()

Finds complete two-second intervals between the current monotonic clock and last_sample. For each interval, increments tick, runs scale(), runs sample(), and moves the sampling reference forward by two seconds.

If paused, it refreshes the wall reference and returns without sampling. For very long idle periods, it skips old ticks and performs at most 90 sample iterations, bounding request work. The skipped portion's scaling evolution is not replayed.

This method explains why polling faster does not speed up the simulation: there must be new elapsed wall time before another tick can exist.

### Lab.snapshot() → dict

Acquires the reentrant lab lock, calls advance(), and builds a consistent dashboard response.

The payload includes state fields, lab identity, command revision, metrics, elapsed time, profiles, histories, events, packets, mission progress, desired capacity, cooldown, topology nodes, regions, traffic mix, policy explanations, and SLA booleans.

It assigns status offline when no healthy firewall exists; otherwise degraded for an incident, loss ≥1%, or latency ≥20 ms; otherwise healthy. Incident status can remain degraded even while SLA targets are met.

Lists are copied from deques for JSON serialization. It does not create an extra sample merely because it is called.

### Lab.apply(action, data) → dict

The atomic command entry point. It holds the lock, advances any existing elapsed time, changes fields for the validated action, and records an event.

| Action branch | What it changes |
| --- | --- |
| traffic | Sets legitimate load. |
| autoscale | Enables/disables the automatic scaling policy. |
| profile | Sets profile, its baseline load, and its target; other choices and incidents survive. |
| failure | Toggles one firewall replica's unavailable flag. |
| replicas | Requires manual mode, then clamps both VNF pools after ±1. |
| routing | Sets routing objective and regional-weight policy. |
| security | Applies supplied TLS-inspection and/or capture booleans. |
| playback | Sets pause state and resets the sampling reference. |
| scenario | Replaces scenario attack/failure flags and sets scenario load. |

After a valid command it increments revision, replaces the current history point with fresh metrics at the same lab time, and returns snapshot().

An RLock is required because apply() calls snapshot() while already holding the same lock. Reentrancy prevents a self-deadlock. A manual-replica attempt with autoscaling enabled raises ValueError, which the API converts to HTTP 409.

## 2. app.py

### create_app(test_config=None) → Flask

An application factory. It creates Flask, configures a secret key, HTTP-only SameSite session cookies, and a 4 KiB maximum request body. It creates a private OrderedDict of labs and a registry lock, registers all handlers, exposes the registry in app.extensions for tests, and returns the app.

The secret comes from ARC_SECRET_KEY if provided, otherwise cryptographically random bytes converted to text. A generated key changes on restart, matching the intentionally transient session store.

The optional test_config overlays settings, allowing independent test apps without modifying the running app. The module-level app = create_app() gives Flask and python app.py an entry point.

### get_lab() → Lab

A helper nested in the factory, sharing its registry and lock. It removes labs inactive for over six hours, reads the browser session's lab_id cookie field, creates a Lab if necessary, marks it recently touched, and moves it to the newest end of the OrderedDict.

It removes the oldest entries until there are at most 128 labs, then returns the selected Lab. This registry ID is a random lookup key; the snapshot's separate Lab identity lets the client detect a replacement lab.

### json_body() → dict

Reads request.get_json(), converts malformed/missing JSON content handling into ValueError, and rejects arrays, numbers, strings, and null. Commands always receive an object after this helper succeeds.

### validate(action, data) → dict

Checks command-specific key names, exact types, ranges, and allowed choices. It uses type(value) is int so booleans cannot masquerade as integer loads. It rejects unknown keys and missing fields.

Failure requires an empty object. Security permits one or both known boolean fields. Other actions require exactly one documented field. Validation occurs before fetching and mutating a Lab.

### index() → rendered HTML

Registered for GET /. Renders templates/index.html through Jinja. The template's url_for() expressions point to local static files.

### get_state() → JSON response

Registered for GET /api/state. Obtains the cookie-specific lab and serializes its snapshot.

### command(action) → JSON response

Registered for POST /api/<action>. Rejects unknown actions with 404, validates JSON input, and calls Lab.apply(). It returns the full dashboard state on success.

ValueError becomes an error JSON object: 409 for attempting manual replicas under autoscaling, otherwise 400. There is no arbitrary action-name reflection or code execution.

### export_report() → attachment response

Registered for GET /api/export. Reads one current snapshot. With format=csv, it writes a header and every retained numeric history row using csv.DictWriter and returns a CSV attachment.

With format=json or no format argument, it adds report name/version/model metadata and returns the full snapshot as an attachment. Unknown formats return HTTP 400. Export uses the requesting browser's lab and can advance elapsed simulation time like any other read.

### response_headers(response) → response

Runs after every response. Sets no-store on API responses so telemetry is not served from browser cache. Adds MIME-sniffing protection, same-origin referrer policy, and a Content Security Policy permitting local assets.

The CSP allows inline styles because the UI uses dynamically generated chart/bar style attributes. Scripts must come from the same origin; external inline executable scripts are not allowed in the live app.

### too_large(error) → JSON error, 413

Registered as the HTTP 413 error handler. Returns a readable JSON error if a request exceeds the body-size limit. This keeps oversized-command errors compatible with the frontend's JSON handling.

### Module execution

The __main__ block starts Flask on 127.0.0.1:8765 with debug=False. The loopback binding and absence of debug reload suit the local simulator; this is not a production hosting setup.

## 3. static/app.js — helpers and client state

### $(selector) → Element or null

Shortens document.querySelector(). Used when a single UI element is expected.

### $$(selector) → Element[]

Converts document.querySelectorAll() into an array, allowing forEach(), map(), and related array operations.

### escapeHtml(value) → string

Converts a value to a string and escapes ampersands, angle brackets, quotation marks, and apostrophes before using it inside generated HTML. Plain-text labels instead go through setText().

### setText(id, value)

Finds an element by ID and updates textContent only if the new string differs. Avoids unnecessary text mutations and never interprets the supplied text as HTML.

### formatTime(seconds) → string

Converts elapsed seconds into a padded minutes:seconds display, such as 00:08. Minutes can grow beyond 59; it is an elapsed-duration label rather than a time of day.

### storageGet(key) → string or null

Reads localStorage inside a try/catch. Returns null if storage access is blocked. Used for the saved theme.

### storageSet(key, value)

Writes localStorage and tolerates blocked preference storage. Theme switching still works during the current page session if persistence is unavailable.

### api(path, body?) → Promise<object>

The fetch wrapper. Omitting body makes a GET; providing it makes a JSON POST. Uses no-store and an eight-second AbortSignal timeout.

It requires a JSON response content type, parses the response, and throws a useful error if the HTTP status is unsuccessful. Same-origin fetch automatically retains the Flask session cookie.

### syncControls()

Disables mutable controls when disconnected, during commands, or while a traffic preview is pending. Keeps the slider responsive during the debounce interval itself. Adds capacity-specific rules: replica buttons remain disabled under autoscaling, at the minimum, or at the maximum.

It leaves reading/navigation tools such as help, event filters, chart selection, and theme switching available.

### setConnection(value)

Updates the connected flag, header classes, and live/reconnecting/paused label, then applies syncControls(). This makes connection failures visibly different from a healthy running model.

## 4. static/app.js — rendering functions

### renderTopology(nodes)

Builds the five node cards from server node data and local SVG icons. A JSON signature of nodes plus selection prevents unchanged data from replacing DOM buttons on every poll.

When the topology genuinely changes, it recreates cards and restores focus to the previously focused node if necessary. Class names expose degraded/offline state and aria-pressed identifies selection.

### renderSelectedNode()

Finds selectedNode in the latest state and displays its name, active instance count, and current role-specific details. Firewall detail follows actual TLS-inspection choice and block estimate; balancer detail follows routing.

It updates the explanatory paragraph from nodeNotes so the topology teaches the component's purpose.

### renderRegions(regions)

Creates the three region chips and the regional traffic/latency table. Status determines the visual health class. Shares and latency come from the server.

### renderAnalysis(state)

Builds a conic-gradient donut from the current traffic mix, renders its legend and decision explanations, synchronizes routing/security inputs, and updates infrastructure quantities.

It also shows whether MANO is converged, pursuing a target, or in manual mode, and displays the remaining scaling cooldown.

### renderEvents()

Filters current events by all, incidents, scaling, or policies. Policy filtering includes routing/security categories. Displays the latest six matches.

Each row includes an elapsed lab-time label, event icon, title, detail, and an actual timestamp tooltip. Shows an informative empty state when no event matches.

### renderChart()

Reads the selected metric from retained server history, determines its vertical range, and creates SVG grid, optional SLA threshold, area, line, and endpoint.

The x-axis uses elapsed time with a minimum 20-second viewing span. Y-axis units depend on metric; throughput starts with a 10 Gbps range, latency at 24 ms, and loss at 2%, growing if necessary.

It updates the chart's accessible description, textual caption, and the compact throughput bars from the same real model samples. It generates no random values.

### renderComparison()

Shows or hides baseline results and clears/replace-baseline actions. With a baseline, it compares throughput, latency, packet loss, and cost against current metrics.

It treats higher throughput as favorable and lower latency/loss/cost as favorable. Deltas are displayed with units and a neutral trade-off label when a metric moves in the opposite direction.

### renderPackets(state)

Displays capture state and up to six newest synthetic packet records, with PASS/BLOCK/DROP badges. If no rows exist, explains whether capture is off or waiting for the next tick.

Turning capture off does not remove retained rows.

### renderMissions(state)

Updates each mission card's ready/running/completed presentation and the total completed count from server-confirmed mission IDs.

Tracks previous completion IDs and shows a toast only for new progress after initial rendering. Initial page load or reload does not reannounce old achievements.

### render(state)

The main presentation coordinator. If lab identity changed, clears the old client baseline and render/progress tracking. Within the same lab, ignores responses with older revisions or older elapsed time at the same revision.

Stores the accepted currentState, updates load/configuration, metric text, per-metric SLA indicators, resource meters, health summary, replica controls, profile/scenario selection, policy labels, and clock.

It sets root attributes controlling animation pause/offline state, calls all sub-renderers, and marks the connection successful.

The traffic preview is not overwritten while a debounced slider command is pending.

## 5. static/app.js — commands and startup

### showToast(message)

Displays a text-only notification and resets its dismissal timer to four seconds. Used for errors, baseline actions, mission completion, and connection changes.

### update(path, body, message?) → Promise<state or null>

Adds a mutation to commandQueue, increments the pending count, and disables relevant controls. When its turn arrives, calls api(), renders returned state, and optionally shows a success message.

On failure it restores current controls from the last accepted state, reports the error, and marks transport/timeout failures disconnected. It returns null for failure so mission launch can stop its dependent steps.

The finally block decrements pending and re-evaluates enabled controls. All normal tasks catch their own errors, allowing the queue to continue after a failed command.

### poll() → Promise<void>

Cancels the previous timer, avoids duplicate polling, and fetches state when the page is visible and no mutation is pending.

Success renders state and resets retry count. Failure marks the connection unavailable and shows the first disconnect notification. Schedules another attempt with a two-second normal delay or incremental backoff capped at ten seconds.

### launchMission(id) → Promise<void>

Requires a loaded lab, resumes a paused clock if necessary, enables autoscaling if necessary, and applies the mission's scenario through sequential queued commands.

It aborts remaining dependent steps if any command fails. On success it scrolls to the topology so the experiment's capacity response is visible. Capture is deliberately left to the learner for the security mission.

### openGuide()

Calls showModal() on the native help dialog. Native dialog behavior provides modal focus and Escape handling.

### bindEvents()

Registers the interface callbacks listed in the next section. Uses delegated topology clicks so newly rendered node buttons need no new listener.

### initialise()

Loads a valid saved theme if present, sets the theme button's accessible label, binds events, applies initial disabled control states, and starts poll(). Called once at the bottom of the script.

## 6. Every UI event handler

These callbacks live inside bindEvents(), rather than separate named functions.

| Event / element | Behavior |
| --- | --- |
| Topology click | Finds the nearest node button, updates selectedNode, rerenders selection and explanation. |
| Traffic input | Previews value/progress immediately; cancels the old debounce and sends the new integer after 180 ms; then ends preview state. |
| Autoscale change | POSTs the actual checkbox boolean. |
| Failure click | Sends an empty object to toggle one replica failure. |
| Replica minus/plus | POSTs delta -1 or 1. |
| Routing change | Sends the selected routing mode. |
| TLS-inspection change | Sends encryption as a boolean, retaining the historical API key. |
| Capture change | Sends capture as a boolean. |
| Pause click | Sends the inverse of the accepted current pause state. |
| Scenario button | Sends the button's scenario identifier. |
| Profile button | Sends the selected profile identifier. |
| Mission launch button | Calls launchMission() with the mission ID. |
| Chart metric button | Updates chartMetric, selected/pressed button states, and the chart. |
| Pin baseline | structuredClone() copies the current snapshot; shows comparison and confirmation. |
| Clear baseline | Sets baseline to null and hides comparison results. |
| Event-filter change | Renders events with the new filter. |
| Navigation click | Updates active nav style and scrolls to the matching data-section anchor. |
| Theme click | Switches root data-theme, updates accessible button label, and saves preference. |
| Header/footer help click | Opens the same field guide. |
| Help-close click | Closes the native dialog. |
| Dialog backdrop click | Closes only if the pointer is outside the dialog rectangle. |
| visibilitychange | Calls poll() when the page becomes visible. |
| pagehide | Cancels polling and outstanding slider debounce timers. |
| pageshow | Restarts polling if restored from the browser back/forward cache. |
| resize | Recalculates chart geometry so labels retain readable sizes at each viewport width. |

CSV/JSON export links use normal browser downloads and need no JavaScript event handler. Native Escape closes the guide without a custom keyboard callback.

## 7. Test helpers and functions

### Clock.__init__(), Clock.__call__(), Clock.advance(seconds)

The injected fake clock starts at zero, returns its current time when called, and moves by the exact requested interval. It lets model tests verify pause, cooldown, and history behavior without sleeping.

### SimulationTests.setUp()

Creates a new fake Clock and Lab before each simulation test, preventing tests from sharing state.

| Simulation test function | Contract verified |
| --- | --- |
| test_repeated_reads_do_not_advance_clock_or_history | Identical same-time reads produce identical snapshots. |
| test_wall_clock_samples_every_two_seconds | Seven elapsed seconds produce three complete ticks and the correct history. |
| test_scaling_steps_respect_cooldown | Capacity advances by one at first step and waits six seconds for another. |
| test_zero_firewalls_cannot_deliver_traffic | Complete firewall outage means offline, zero throughput/availability, 100% loss, zero blocks. |
| test_restore_recovers_capacity | Toggling failure off restores healthy baseline capacity. |
| test_pause_freezes_history_capture_and_scaling | Paused wall time creates no telemetry; resume starts with a fresh interval. |
| test_packet_capture_stops_and_retains_samples | Disabling capture stops additions without deleting records. |
| test_scenarios_do_not_stack_incidents | A new scenario clears the previous scenario's incident flags. |
| test_clear_preserves_policies | Clearing an incident keeps routing/inspection/capture choices. |
| test_missions_require_observed_outcomes | Each mission requires its modeled result; security requires capture. |
| test_high_load_and_loss_reduce_delivered_throughput | Underprovisioning raises loss and reduces delivered traffic. |
| test_routing_changes_weights_latency_and_inspection_overhead | Routing changes weights/latency/cost; inspection contributes exactly 1.4 ms. |
| test_bounded_history_packets_events_and_long_idle_catchup | Long inactivity and many commands respect storage bounds and elapsed time. |
| test_atomic_concurrent_commands | Concurrent failure toggles have no lost revision or state updates. |
| test_replica_limits_and_policy_formula | Target calculation and minimum pool capacity remain bounded. |

### ApiTests.setUp()

Creates an independent Flask app with a test secret and a cookie-preserving test client before every API test.

| API test function | Contract verified |
| --- | --- |
| test_page_assets_and_headers | Canonical page/assets load; API no-store and local-script CSP are set. |
| test_sessions_are_isolated_and_persist_with_cookie | A cookie retains changes; another client has independent defaults and identity. |
| test_invalid_payloads_return_json_without_mutation | Wrong keys/types/ranges produce JSON 400 errors without command revisions. |
| test_malformed_non_object_and_oversized_json | Invalid JSON, non-objects, wrong content type, and oversized bodies fail correctly. |
| test_manual_scaling_conflict_and_valid_commands | Manual scaling conflict is 409; supported valid commands succeed; unknown commands are 404. |
| test_exports_are_parseable_and_match_session | JSON/CSV are downloadable, parseable, and match the selected session. |
| test_session_registry_is_bounded | Creating 130 clients retains only 128 labs. |

### run_browser_checks() in tests/browser_smoke.py

Starts a disposable Flask app on localhost port 8770, chooses an installed Chromium executable or Playwright's browser, and launches an isolated headless profile.

It drives visible controls, asserts actual DOM results, captures screenshots, checks narrow-layout width, validates file downloads, tests independent browser sessions, and deliberately interrupts polling to verify automatic recovery.

It records page/console errors and fails if unexpected errors occurred. A finally block shuts down the local test server. The deliberately generated network ERR_FAILED log is excluded because it is part of the disconnect test.

Inline callbacks attach error collectors to Playwright, simulate network aborts, and execute simple layout/scroll assertions inside the test page. They are test plumbing rather than runtime application functions.

## 8. Files without application functions

- templates/index.html declares page sections, controls, their IDs/data attributes, and the help dialog.
- static/styles.css supplies base styles; static/observatory.css supplies theme overrides, new panels, breakpoints, focus rules, and animations.
- static/favicon.svg is the vector icon.
- index.html is a local launcher with commands and documentation links.
- requirements files declare dependencies; documentation and output artifacts do not run as part of Flask.

When adding a feature, start with the state/model behavior and a behavioral test, expose a validated API command, add the UI control, then connect it in bindEvents() and the relevant renderer.
