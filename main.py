from fastapi import FastAPI
from pydantic import BaseModel
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import base64
from datetime import datetime
import time

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
    try:
        data = page.screenshot(full_page=True)
        return base64.b64encode(data).decode()
    except Exception:
        return ""


def _find_radio(page):
    frames = [page] + list(page.frames)
    for frame in frames:
        try:
            radios = frame.query_selector_all("input[type=radio]")
            if radios:
                return frame, radios[0]
        except:
            pass
    return None, None


def _find_input(page):
    frames = [page] + list(page.frames)
    for frame in frames:
        try:
            el = frame.query_selector("input[type='text']")
            if el:
                return frame, el
        except:
            pass
    return None, None


def _find_button(page):
    frames = [page] + list(page.frames)
    for frame in frames:
        try:
            el = frame.query_selector("button")
            if el:
                return frame, el
        except:
            pass
    return None, None


def run_scraper(cnpj: str):

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        context = browser.new_context()
        page = context.new_page()

        _log(f"Acessando CGU para CNPJ {cnpj}")

        page.goto("https://certidoes.cgu.gov.br/", timeout=90000)
        page.wait_for_load_state("load")
        page.wait_for_timeout(3000)

        # RADIO
        frame, radio = _find_radio(page)
        if not radio:
            raise Exception("Radio não encontrado")

        frame.evaluate("""
            (el) => {
                el.checked = true;
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }
        """, radio)

        page.wait_for_timeout(1000)

        # INPUT
        frame, input_el = _find_input(page)
        if not input_el:
            raise Exception("Input não encontrado")

        input_el.fill(cnpj)

        # BUTTON
        frame, btn = _find_button(page)
        if not btn:
            raise Exception("Botão não encontrado")

        btn.click()

        page.wait_for_timeout(5000)

        content = page.content()

        if "Nenhum registro encontrado" in content:
            has_restrictions = False
        else:
            has_restrictions = True

        file_name = f"CEIS_{cnpj}.png"
        file_path = f"/tmp/{file_name}"

        page.screenshot(path=file_path, full_page=True)

        browser.close()

        return {
            "status": "success",
            "file": file_name,
            "has_restrictions": has_restrictions,
            "data": [
                ["CEIS", "-", "-", "CGU"]
            ]
        }


def run_with_retry(cnpj: str, retries=2):

    for attempt in range(retries):
        try:
            _log(f"Tentativa {attempt+1}")
            return run_scraper(cnpj)
        except Exception as e:
            _log(f"Erro: {e}")
            time.sleep(2)

    return {
        "status": "error",
        "message": "Falha após múltiplas tentativas"
    }


@app.post("/collect")
def collect(data: RequestData):

    cnpj = data.cnpj

    try:
        result = run_with_retry(cnpj)

        return result

    except Exception as e:
        _log(f"Erro final: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
