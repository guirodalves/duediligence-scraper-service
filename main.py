from fastapi import FastAPI
from pydantic import BaseModel
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import base64
import os
from datetime import datetime

app = FastAPI()

class RequestData(BaseModel):
    cnpj: str

@app.get("/")
def root():
    return {"message": "API OK"}

@app.get("/health")
def health():
    return {"status": "ok"}

def _log(msg: str):
    print(f"[{datetime.utcnow().isoformat()}] {msg}", flush=True)

def _screenshot_b64(page, label: str) -> str:
    """Take a screenshot and return it as a base64 string for inline debug output."""
    try:
        data = page.screenshot(full_page=True)
        encoded = base64.b64encode(data).decode()
        _log(f"Screenshot captured: {label} ({len(data)} bytes)")
        return encoded
    except Exception as exc:
        _log(f"Screenshot failed ({label}): {exc}")
        return ""

def _dump_page_inputs(page) -> list[dict]:
    """Return a list of all input elements found on the main frame."""
    try:
        inputs = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('input')).map(el => ({
                type: el.type,
                name: el.name,
                id: el.id,
                value: el.value,
                placeholder: el.placeholder,
                visible: el.offsetParent !== null
            }));
        }""")
        return inputs
    except Exception as exc:
        _log(f"Could not dump inputs: {exc}")
        return []

def _dump_iframes(page) -> list[str]:
    """Return src/name of every iframe on the page."""
    try:
        return page.evaluate("""() =>
            Array.from(document.querySelectorAll('iframe')).map(f =>
                f.src || f.name || '(no src)')
        """)
    except Exception as exc:
        _log(f"Could not dump iframes: {exc}")
        return []

def _find_radio_in_frames(page):
    """
    Try to find an 'Ente Privado' radio button across the main frame and all
    child frames.  Returns (frame, element) or (None, None).
    """
    # Candidate selectors, ordered from most to least specific
    selectors = [
        "input[type=radio][value*='rivado']",   # value contains "rivado" (Privado)
        "input[type=radio][value*='privado']",
        "input[type=radio][value*='Privado']",
        "input[type=radio]",                    # any radio – fall back to index 0
    ]

    frames = [page] + list(page.frames)
    _log(f"Searching across {len(frames)} frame(s)")

    for frame in frames:
        frame_url = getattr(frame, "url", "main")
        _log(f"  Checking frame: {frame_url}")

        for sel in selectors:
            try:
                elements = frame.query_selector_all(sel)
                if elements:
                    _log(f"    Found {len(elements)} element(s) with selector '{sel}'")
                    return frame, elements[0]
            except Exception as exc:
                _log(f"    Selector '{sel}' raised: {exc}")

    return None, None

def _find_text_input_in_frames(page):
    """Find the CNPJ text input across all frames."""
    selectors = [
        "input[placeholder*='CNPJ']",
        "input[placeholder*='cnpj']",
        "input[name*='cnpj']",
        "input[name*='CNPJ']",
        "input[type='text']",
    ]

    frames = [page] + list(page.frames)
    for frame in frames:
        for sel in selectors:
            try:
                el = frame.query_selector(sel)
                if el:
                    _log(f"Found text input with selector '{sel}' in frame {getattr(frame, 'url', 'main')}")
                    return frame, el
            except Exception:
                pass
    return None, None

def _find_submit_button_in_frames(page):
    """Find the Consultar button across all frames."""
    selectors = [
        "button:has-text('Consultar')",
        "input[type=submit][value*='Consultar']",
        "button[type=submit]",
        "input[type=submit]",
    ]

    frames = [page] + list(page.frames)
    for frame in frames:
        for sel in selectors:
            try:
                el = frame.query_selector(sel)
                if el:
                    _log(f"Found submit button with selector '{sel}' in frame {getattr(frame, 'url', 'main')}")
                    return frame, el
            except Exception:
                pass
    return None, None

@app.post("/collect")
def collect(data: RequestData):
    cnpj = data.cnpj
    debug_info: dict = {}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page()

            # ----------------------------------------------------------------
            # 1. Navigate and wait for the page to fully load
            # ----------------------------------------------------------------
            _log(f"Navigating to certidoes.cgu.gov.br for CNPJ {cnpj}")
            page.goto("https://certidoes.cgu.gov.br/", timeout=90000)

            _log("Waiting for 'load' state…")
            page.wait_for_load_state("load", timeout=90000)

            _log("Extra wait for JS rendering (3 s)…")
            page.wait_for_timeout(3000)

            debug_info["screenshot_after_load"] = _screenshot_b64(page, "after_load")
            debug_info["page_title"] = page.title()
            debug_info["page_url"] = page.url
            debug_info["iframes"] = _dump_iframes(page)
            debug_info["inputs_main_frame"] = _dump_page_inputs(page)

            _log(f"Page title: {debug_info['page_title']}")
            _log(f"Iframes found: {debug_info['iframes']}")
            _log(f"Inputs on main frame: {debug_info['inputs_main_frame']}")

            # ----------------------------------------------------------------
            # 2. Try to find the radio button (Ente Privado)
            # ----------------------------------------------------------------
            _log("Attempting to locate radio button…")

            # Give dynamic content a second chance: wait up to 10 s for any radio
            try:
                page.wait_for_selector("input[type=radio]", timeout=10000)
                _log("Radio button appeared in main frame via wait_for_selector")
            except PlaywrightTimeoutError:
                _log("wait_for_selector timed out – will still try cross-frame search")

            radio_frame, radio_el = _find_radio_in_frames(page)

            if radio_el is None:
                # Capture a final screenshot before giving up
                debug_info["screenshot_no_radio"] = _screenshot_b64(page, "no_radio_found")
                debug_info["page_content_snippet"] = page.content()[:3000]
                browser.close()
                return {
                    "status": "error",
                    "message": "Radio button not found in any frame after extended wait",
                    "debug": debug_info,
                }

            _log("Clicking radio button (Ente Privado)…")
            radio_el.click()
            page.wait_for_timeout(1000)

            debug_info["screenshot_after_radio"] = _screenshot_b64(page, "after_radio_click")

            # ----------------------------------------------------------------
            # 3. Fill in the CNPJ
            # ----------------------------------------------------------------
            _log("Locating CNPJ text input…")
            text_frame, text_el = _find_text_input_in_frames(page)

            if text_el is None:
                debug_info["screenshot_no_input"] = _screenshot_b64(page, "no_text_input")
                browser.close()
                return {
                    "status": "error",
                    "message": "CNPJ text input not found in any frame",
                    "debug": debug_info,
                }

            _log(f"Filling CNPJ: {cnpj}")
            text_el.fill(cnpj)
            page.wait_for_timeout(500)

            # ----------------------------------------------------------------
            # 4. Click Consultar
            # ----------------------------------------------------------------
            _log("Locating Consultar button…")
            btn_frame, btn_el = _find_submit_button_in_frames(page)

            if btn_el is None:
                debug_info["screenshot_no_button"] = _screenshot_b64(page, "no_button")
                browser.close()
                return {
                    "status": "error",
                    "message": "Consultar button not found in any frame",
                    "debug": debug_info,
                }

            _log("Clicking Consultar…")
            btn_el.click()

            # ----------------------------------------------------------------
            # 5. Wait for results and capture screenshot
            # ----------------------------------------------------------------
            _log("Waiting for results (5 s)…")
            page.wait_for_timeout(5000)

            file_name = f"CEIS_{cnpj}.png"
            file_path = f"/tmp/{file_name}"

            _log(f"Saving final screenshot to {file_path}")
            page.screenshot(path=file_path, full_page=True)

            browser.close()

        return {
            "status": "success",
            "file": file_name,
            "debug": {
                "page_title": debug_info.get("page_title"),
                "page_url": debug_info.get("page_url"),
                "iframes": debug_info.get("iframes"),
                "inputs_found": debug_info.get("inputs_main_frame"),
            },
        }

    except Exception as e:
        _log(f"Unhandled exception: {e}")
        return {
            "status": "error",
            "message": str(e),
            "debug": debug_info,
        }
