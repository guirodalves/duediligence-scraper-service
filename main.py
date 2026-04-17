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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()

        # 1. Acessa o portal
        page.goto("https://certidoes.cgu.gov.br/", timeout=60000)

        # 2. Seleciona "Ente Privado"
        page.click("text=Ente Privado")

        # 3. Preenche CNPJ
        page.fill("input[type='text']", cnpj)

        # 4. Clica em buscar
        page.click("button:has-text('Consultar')")

        # 5. Aguarda resultado
        page.wait_for_timeout(5000)

        # 6. Gera PNG da página
        file_name = f"CEIS_{cnpj}.png"
        file_path = f"/tmp/{file_name}"

        page.screenshot(path=file_path, full_page=True)

        browser.close()

    return {
        "status": "success",
        "file_url": f"/files/{file_name}"
    }
