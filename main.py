from fastapi import FastAPI
from pydantic import BaseModel
from playwright.sync_api import sync_playwright
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

@app.post("/collect")
def collect(data: RequestData):
    cnpj = data.cnpj

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()

            page.goto("https://certidoes.cgu.gov.br/", timeout=60000)

            await page.wait_for_load_state("networkidle")

            # espera qualquer radio button aparecer
            await page.wait_for_selector("input[type=radio]")
            
            # clica no primeiro radio (Ente Privado)
            radios = await page.query_selector_all("input[type=radio]")
            await radios[0].click()

            # insere o CNPJ
            page.fill("input[type='text']", cnpj)
            page.click("button:has-text('Consultar')")

            page.wait_for_timeout(5000)

            file_name = f"CEIS_{cnpj}.png"
            file_path = f"/tmp/{file_name}"

            page.screenshot(path=file_path, full_page=True)

            browser.close()

        return {
            "status": "success",
            "file": file_name
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
    return {
        "status": "success",
        "file_url": f"/files/{file_name}"
    }
