from fastapi import FastAPI
from pydantic import BaseModel
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import base64
from datetime import datetime
import time

app = FastAPI()
ta

class RequestData(BaseModel):
    cnpj: str


@app.get("/")
def root():
    return {"message": "API OK"}


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(msg: str):
    print(f"[{datetime.utcnow().isoformat()}] {msg}", flush=True)


def _screenshot_b64(page) -> str:
    """Return a base64-encoded PNG screenshot, or empty string on failure."""
    try:
        data = page.screenshot(full_page=True)
        return base64.b64encode(data).decode()
    except Exception as exc:
        _log(f"Screenshot falhou: {exc}")
        return ""


def _all_frames(page):
    """Return the main page followed by every child frame."""
    return [page] + list(page.frames)


# ---------------------------------------------------------------------------
# Cross-frame element finders
# ---------------------------------------------------------------------------

# Selectors tried in order for each element type.
_RADIO_SELECTORS = [
    "input[type='radio'][value='1']",   # CNPJ option (value=1)
    "input#__BVID__22",                 # known Bootstrap-Vue id for CNPJ
    "input[type='radio']",              # any radio as last resort
]

_INPUT_SELECTORS = [
    "input#cnpj",
    "input[placeholder*='CNPJ' i]",
    "input[name*='cnpj' i]",
    "input[type='text']",
    "input[type='search']",
]

_BUTTON_SELECTORS = [
    "button[type='submit']",
    "button.btn-primary",
    "button",
]


def _find_element(page, selectors: list[str], label: str):
    """
    Search every frame for the first selector that returns an element.
    Returns (frame, element) or (None, None).
    Logs what was found for debugging.
    """
    frames = _all_frames(page)
    _log(f"Buscando '{label}' em {len(frames)} frame(s) com {len(selectors)} seletor(es)")

    for frame in frames:
        try:
            frame_name = getattr(frame, "name", "main") or "main"
            frame_url  = getattr(frame, "url", "?") or "?"

            # Diagnostic: count all inputs in this frame
            try:
                all_inputs = frame.query_selector_all("input")
                _log(f"  Frame '{frame_name}' ({frame_url}): {len(all_inputs)} input(s) total")
            except Exception:
                pass

            for sel in selectors:
                try:
                    el = frame.query_selector(sel)
                    if el:
                        _log(f"  ✓ Encontrado '{label}' com seletor '{sel}' no frame '{frame_name}'")
                        return frame, el
                except Exception as exc:
                    _log(f"  Seletor '{sel}' falhou no frame '{frame_name}': {exc}")
        except Exception as exc:
            _log(f"  Erro ao inspecionar frame: {exc}")

    _log(f"  ✗ '{label}' não encontrado em nenhum frame")
    return None, None


def _find_radio(page):
    return _find_element(page, _RADIO_SELECTORS, "radio CNPJ")


def _find_input(page):
    return _find_element(page, _INPUT_SELECTORS, "input CNPJ")


def _find_button(page):
    return _find_element(page, _BUTTON_SELECTORS, "botão consultar")


# ---------------------------------------------------------------------------
# Radio interaction — JS-first, click fallback
# ---------------------------------------------------------------------------

def _click_radio(frame, radio, page) -> bool:
    """
    Select a radio button using JavaScript (avoids label-overlay interception).
    Falls back to a force=True Playwright click if JS dispatch fails.
    Returns True on success.
    """
    # Strategy 1: JS — set checked + dispatch change & input events
    try:
        frame.evaluate(
            """
            (el) => {
                el.checked = true;
                el.dispatchEvent(new Event('input',  { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }
            """,
            radio,
        )
        _log("Radio selecionado via JavaScript (checked + events)")
        page.wait_for_timeout(500)
        return True
    except Exception as exc:
        _log(f"JS radio falhou: {exc}")

    # Strategy 2: force click (bypasses pointer-events / overlay)
    try:
        radio.click(force=True)
        _log("Radio clicado via force=True")
        page.wait_for_timeout(500)
        return True
    except Exception as exc:
        _log(f"Force click no radio falhou: {exc}")

    return False


# ---------------------------------------------------------------------------
# Core scraper
# ---------------------------------------------------------------------------

def run_scraper(cnpj: str) -> dict:
    debug: dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        # Browser context with realistic headers and viewport
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
                ),
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://www.google.com/",
            },
        )

        # Hide navigator.webdriver to avoid bot-detection
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page = context.new_page()

        try:
            _log(f"Acessando CGU para CNPJ {cnpj}")
            page.goto("https://certidoes.cgu.gov.br/", timeout=90000)
            page.wait_for_load_state("networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            # --- Diagnostic snapshot ---
            debug["title"] = page.title()
            debug["url"]   = page.url
            frames = _all_frames(page)
            debug["frames"] = [
                {"name": getattr(f, "name", ""), "url": getattr(f, "url", "")}
                for f in frames
            ]
            _log(f"Página carregada: title='{debug['title']}' url='{debug['url']}'")
            _log(f"Frames detectados: {len(frames)}")

            # Count all inputs on the page for debugging
            try:
                all_inputs = page.query_selector_all("input")
                debug["inputs_found"] = len(all_inputs)
                _log(f"Inputs no frame principal: {len(all_inputs)}")
                for inp in all_inputs:
                    try:
                        itype = inp.get_attribute("type") or "text"
                        iid   = inp.get_attribute("id") or ""
                        iname = inp.get_attribute("name") or ""
                        ival  = inp.get_attribute("value") or ""
                        _log(f"  input type={itype} id={iid} name={iname} value={ival}")
                    except Exception:
                        pass
            except Exception as exc:
                _log(f"Erro ao listar inputs: {exc}")

            debug["screenshot_initial"] = _screenshot_b64(page)

            # ----------------------------------------------------------------
            # Step 1 — Select the CNPJ radio button
            # ----------------------------------------------------------------
            frame_r, radio = _find_radio(page)
            if not radio:
                debug["screenshot_no_radio"] = _screenshot_b64(page)
                raise Exception(
                    f"Radio não encontrado. "
                    f"title='{debug.get('title')}' "
                    f"frames={debug.get('frames')} "
                    f"inputs={debug.get('inputs_found', 0)}"
                )

            if not _click_radio(frame_r, radio, page):
                raise Exception("Falha ao selecionar o radio CNPJ")

            debug["screenshot_after_radio"] = _screenshot_b64(page)

            # ----------------------------------------------------------------
            # Step 2 — Fill the CNPJ text input
            # ----------------------------------------------------------------
            frame_i, input_el = _find_input(page)
            if not input_el:
                debug["screenshot_no_input"] = _screenshot_b64(page)
                raise Exception("Input de CNPJ não encontrado após selecionar radio")

            input_el.fill(cnpj)
            _log(f"CNPJ '{cnpj}' preenchido no input")
            page.wait_for_timeout(500)

            # ----------------------------------------------------------------
            # Step 3 — Click the search button
            # ----------------------------------------------------------------
            frame_b, btn = _find_button(page)
            if not btn:
                debug["screenshot_no_button"] = _screenshot_b64(page)
                raise Exception("Botão de consulta não encontrado")

            btn.click()
            _log("Botão clicado, aguardando resultado...")
            page.wait_for_timeout(5000)

            debug["screenshot_result"] = _screenshot_b64(page)

        # ----------------------------------------------------------------
        # Step 4 — Parse result (CORRIGIDO)
        # ----------------------------------------------------------------
        rows = []
        
        try:
            tables = page.query_selector_all("table")
        
            for table in tables:
                text = table.inner_text()
        
                if "Órgão" in text or "Sanção" in text:
        
                    table_rows = table.query_selector_all("tbody tr")
        
                    for row in table_rows:
                        cols = row.query_selector_all("td")
                        values = [c.inner_text().strip() for c in cols]
        
                        if len(values) >= 3:
                            rows.append(values)
        
                    break
        
        except Exception as e:
            _log(f"Erro ao extrair tabela: {e}")
        
        # fallback
        if not rows:
            rows = [["Nenhuma restrição encontrada", "-", "-", "-"]]
        
        has_restrictions = not ("Nenhuma restrição encontrada" in rows[0][0])
        
        file_name = f"CEIS_{cnpj}.png"
        file_path = f"/tmp/{file_name}"
        
        page.screenshot(path=file_path, full_page=True)
        
        _log(f"Screenshot salvo em {file_path}")
        
        return {
            "status": "success",
            "file": file_name,
            "has_restrictions": has_restrictions,
            "data": rows,
        }

        except Exception as exc:
            _log(f"Erro no scraper: {exc}")
            debug["error"] = str(exc)
            raise
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------

def run_with_retry(cnpj: str, retries: int = 3) -> dict:
    last_error = "Falha desconhecida"
    for attempt in range(1, retries + 1):
        _log(f"Tentativa {attempt}/{retries}")
        try:
            return run_scraper(cnpj)
        except Exception as exc:
            last_error = str(exc)
            _log(f"Tentativa {attempt} falhou: {exc}")
            if attempt < retries:
                time.sleep(3)

    return {
        "status": "error",
        "message": f"Falha após {retries} tentativas: {last_error}",
    }


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------

@app.post("/collect")
def collect(data: RequestData):
    cnpj = data.cnpj
    _log(f"POST /collect cnpj={cnpj}")
    try:
        return run_with_retry(cnpj)
    except Exception as exc:
        _log(f"Erro final não tratado: {exc}")
        return {"status": "error", "message": str(exc)}
