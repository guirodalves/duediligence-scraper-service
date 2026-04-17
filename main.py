from fastapi import FastAPI
from pydantic import BaseModel
from playwright.sync_api import sync_playwright
import os
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

class RequestData(BaseModel):
    cnpj: str

@app.get("/")
def root():
    return {"message": "API OK"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/collect")
def collect(data: RequestData):
    cnpj = data.cnpj

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()

            logger.info("Navigating to https://certidoes.cgu.gov.br/")
            page.goto("https://certidoes.cgu.gov.br/", timeout=60000)

            logger.info("Waiting for networkidle load state")
            page.wait_for_load_state("networkidle")

            logger.info("Page loaded — capturing debug screenshot before radio search")
            page.screenshot(path="/tmp/debug_before_radio.png")

            # espera qualquer radio button aparecer (timeout aumentado para 60s)
            logger.info("Waiting for input[type=radio] to be visible (timeout=60000ms)")
            try:
                page.wait_for_selector("input[type=radio]", timeout=60000)
            except Exception as radio_err:
                logger.error("Timed out waiting for radio buttons: %s", radio_err)
                page.screenshot(path="/tmp/debug_radio_timeout.png")
                page_content = page.content()
                logger.error("Page HTML at timeout (first 2000 chars): %s", page_content[:2000])
                return {
                    "status": "error",
                    "message": f"Timed out waiting for radio buttons to appear: {radio_err}",
                    "debug_screenshot": "/tmp/debug_radio_timeout.png",
                    "page_url": page.url,
                }

            # clica no primeiro radio (Ente Privado)
            radios = page.query_selector_all("input[type=radio]")
            logger.info("Found %d radio button(s) — clicking the first one", len(radios))
            radios[0].click()

            # insere o CNPJ
            page.fill("input[type='text']", cnpj)
            page.click("button:has-text('Consultar')")

            page.wait_for_timeout(5000)

            file_name = f"CEIS_{cnpj}.png"
            file_path = f"/tmp/{file_name}"

            page.screenshot(path=file_path, full_page=True)
            logger.info("Screenshot saved to %s", file_path)

            browser.close()

        return {
            "status": "success",
            "file": file_name
        }

    except Exception as e:
        logger.exception("Unexpected error in /collect: %s", e)
        return {
            "status": "error",
            "message": str(e)
        }
