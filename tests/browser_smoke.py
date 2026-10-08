"""Optional end-to-end check using an isolated headless Chromium profile.

Install requirements-dev.txt, then run python tests/browser_smoke.py.
Screenshots are saved under output/previews.
"""
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright, expect
from app import create_app


def run_browser_checks():
    """Exercise real UI actions, responsive layouts, downloads, and recovery."""
    server = make_server("127.0.0.1", 8770, create_app(), threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = Path(__file__).resolve().parents[1] / "output" / "previews"
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    try:
        with sync_playwright() as playwright:
            executable = os.environ.get("ARC_BROWSER_EXECUTABLE")
            if not executable:
                candidates = [Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
                              Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")]
                executable = next((str(path) for path in candidates if path.exists()), None)
            browser = playwright.chromium.launch(headless=True, executable_path=executable)
            context = browser.new_context(viewport={"width": 1440, "height": 1100}, reduced_motion="reduce")
            page = context.new_page()
            page.on("pageerror", lambda error: (errors.append(str(error)), print("Browser error:", error)))
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.goto("http://127.0.0.1:8770")
            expect(page.locator("#connection-label")).to_have_text("Live model")
            expect(page.locator(".node")).to_have_count(5)
            page.screenshot(path=str(output / "desktop-dark.png"), full_page=True)
            page.screenshot(path=str(output / "desktop-viewport.png"))
            page.locator('[data-node="balancer"]').click()
            expect(page.locator('#node-explanation')).to_contain_text('distributes requests')
            page.locator('[data-node="firewall"]').click()
            page.locator('#traffic').focus()
            page.keyboard.press('ArrowRight')
            expect(page.locator('#traffic-value')).to_have_text('59%')
            expect(page.locator('#traffic')).to_be_enabled()
            page.locator('#routing-mode').select_option('latency')
            expect(page.locator('#region-table')).to_contain_text('65% traffic')
            page.locator('#routing-mode').select_option('adaptive')
            expect(page.locator('#encryption')).to_be_enabled()
            page.locator('#encryption').uncheck()
            expect(page.locator('#selected-node-detail')).to_contain_text('TLS inspection off')
            page.locator('#encryption').check()
            page.locator("#pin-baseline").click()
            expect(page.locator(".comparison-item")).to_have_count(4)
            page.locator('[data-launch="scale"]').click()
            expect(page.locator('[data-mission="scale"] .mission-status')).to_have_text("✓ Completed", timeout=15000)
            page.locator('[data-launch="security"]').click()
            expect(page.locator('#packet-capture')).to_be_enabled()
            page.locator('#packet-capture').check()
            expect(page.locator(".packet-badge.block").first).to_be_visible(timeout=15000)
            expect(page.locator('[data-mission="security"] .mission-status')).to_have_text("✓ Completed")
            page.locator('[data-launch="resilience"]').click()
            expect(page.locator('[data-mission="resilience"] .mission-status')).to_have_text("✓ Completed", timeout=10000)
            expect(page.locator("#mission-progress")).to_have_text("3 / 3 completed")
            page.locator('[data-scenario="reset"]').click()
            expect(page.locator("#system-label")).to_have_text("The chain is healthy")
            page.locator("#pause-button").click()
            expect(page.locator("#connection-label")).to_have_text("Paused")
            elapsed = page.locator("#elapsed-time").inner_text()
            page.wait_for_timeout(2500)
            assert page.locator("#elapsed-time").inner_text() == elapsed
            page.locator("#autoscale").uncheck()
            expect(page.locator("#replica-down")).to_be_enabled()
            for _ in range(4):
                if page.locator("#replica-down").is_enabled():
                    page.locator("#replica-down").click()
                    expect(page.locator("#failure-button")).to_be_enabled()
            page.locator("#failure-button").click()
            expect(page.locator("#system-label")).to_have_text("No firewall capacity")
            expect(page.locator("#throughput")).to_have_text("0.0")
            page.locator("#failure-button").click()
            expect(page.locator("#failure-button")).to_have_text("Simulate failure")
            page.locator('#event-filter').select_option('alert')
            expect(page.locator('#event-list .event.alert').first).to_be_visible()
            page.locator('#event-filter').select_option('all')
            page.locator('[data-chart="latency"]').click()
            expect(page.locator('#chart-summary')).to_contain_text('Latency / ms')
            page.locator('[data-chart="packet_loss"]').click()
            expect(page.locator('#chart-summary')).to_contain_text('Packet loss / %')
            page.locator('#clear-baseline').click()
            expect(page.locator('#comparison-results')).to_be_hidden()
            page.locator('#help-open').click()
            expect(page.locator('#help-dialog')).to_be_visible()
            page.keyboard.press('Escape')
            expect(page.locator('#help-dialog')).to_be_hidden()
            with page.expect_download() as download:
                page.locator('a[href="/api/export?format=csv"]').click()
            assert download.value.suggested_filename == 'arc-telemetry.csv'
            with page.expect_download() as download:
                page.locator('a[href="/api/export?format=json"]').click()
            assert download.value.suggested_filename == 'arc-lab-report.json'
            page.locator("#theme-toggle").click()
            expect(page.locator('html')).to_have_attribute('data-theme', 'light')
            expect(page.locator('#toast')).not_to_have_class('toast show', timeout=6000)
            page.screenshot(path=str(output / "desktop-light.png"), full_page=True)
            page.reload()
            expect(page.locator("#connection-label")).to_have_text("Paused")
            expect(page.locator('html')).to_have_attribute('data-theme', 'light')
            # Reset local presentation for screenshots while keeping earned progress.
            page.locator('#autoscale').check()
            page.locator('#pause-button').click()
            expect(page.locator("#connection-label")).to_have_text("Live model")
            page.locator("#theme-toggle").click()
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.locator('#toast')).not_to_have_class('toast show', timeout=6000)
            page.screenshot(path=str(output / "mobile-dark.png"), full_page=True)
            page.evaluate("scrollTo(0, 0)")
            page.screenshot(path=str(output / "mobile-viewport.png"))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile horizontal overflow"
            page.locator('#help-open').click()
            expect(page.locator('#help-dialog')).to_be_visible()
            page.screenshot(path=str(output / "mobile-guide.png"))
            page.keyboard.press('Escape')
            page.set_viewport_size({"width": 320, "height": 750})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Small mobile horizontal overflow"
            page.set_viewport_size({"width": 768, "height": 1024})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Tablet horizontal overflow"
            page.screenshot(path=str(output / "tablet-dark.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1100})
            # Abort polling once, then verify automatic recovery.
            page.route("**/api/state", lambda route: route.abort())
            expect(page.locator("#connection-label")).to_have_text("Reconnecting", timeout=10000)
            page.unroute("**/api/state")
            expect(page.locator("#connection-label")).to_have_text("Live model", timeout=15000)
            # A second browser context gets a fresh, independent simulation.
            second = browser.new_context()
            other = second.new_page()
            other.goto("http://127.0.0.1:8770")
            expect(other.locator("#mission-progress")).to_have_text("0 / 3 completed")
            expect(other.locator("#packet-capture")).not_to_be_checked()
            second.close()
            # Network failure is deliberately logged by Chromium.
            errors = [error for error in errors if "ERR_FAILED" not in error]
            assert not errors, errors
            context.close()
            browser.close()
            print("PASS: browser interactions, missions, playback, exports, themes, mobile/tablet layout, isolated sessions, and connection recovery.")
            print(f"Screenshots: {output}")
    finally:
        server.shutdown()


if __name__ == "__main__":
    run_browser_checks()
