"""Fresh headless browser checks. Creates only unapproved synthetic test records."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"data/reports/validation/browser_checks"
OUT.mkdir(parents=True, exist_ok=True)
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    context = browser.new_context(viewport={"width":1360,"height":900}, accept_downloads=True)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8788/static/validation/index.html")
    page.wait_for_load_state("networkidle")
    assert page.locator(".case").count() == 30
    assert page.locator("#title").inner_text() == "enginuity_01"
    assert page.locator("#reference-card").is_hidden()
    assert page.locator("#prediction-card").is_hidden()
    assert page.locator("#pages img").count() == 2
    assert page.locator("#independent").is_enabled()
    page.locator("#reference").click()
    assert page.locator("#reference-card").is_visible()
    assert page.locator("#independent").is_disabled()
    page.locator("#prediction").click()
    assert "external_reference_v3_direct" in page.locator("#prediction-json").inner_text()
    page.screenshot(path=str(OUT/"review_desktop.png"), full_page=True)
    page.locator("#filter").select_option("synthetic")
    assert page.locator(".case").count() == 40
    page.locator("#reviewer").fill("AUTOMATED_UI_TEST_NOT_A_HUMAN_APPROVAL")
    page.locator("#components").fill(json.dumps([{"part_number":"TEST", "quantity":None, "source_page":1}]))
    page.locator("#save").click()
    assert "已记录" in page.locator("#message").inner_text()
    with page.expect_download() as download:
        page.locator("#export").click()
    data = json.loads(Path(download.value.path()).read_text(encoding="utf-8"))
    assert len(data["reviews"]) == 1
    record = data["reviews"][0]
    assert record["status"] == "needs_review" and not record["independent"] and record["synthetic"]
    page.set_viewport_size({"width":390,"height":844})
    page.screenshot(path=str(OUT/"review_mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.goto("http://127.0.0.1:8788/")
    page.wait_for_load_state("networkidle")
    assert "BOM 与图纸纠错" in page.locator("body").inner_text()
    assert not errors, errors
    browser.close()
(OUT/"result.json").write_text(json.dumps({"status":"passed", "checks":["30/40 case switching", "source images", "hidden labels", "exposure disables independence", "model results", "unapproved synthetic save/export", "mobile no horizontal overflow", "combined entry", "no page errors"], "human_approvals_created":0}, ensure_ascii=False, indent=2), encoding="utf-8")
print("PASS: headless review UI; zero human approvals created")
