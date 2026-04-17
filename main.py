from fastapi import FastAPI
from playwright.sync_api import sync_playwright

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/collect")
def collect(data: dict):
    cnpj = data.get("cnpj")

    resultados = []
    has_restrictions = False

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = browser.new_page()

        page.goto("https://certidoes.cgu.gov.br/")
        page.wait_for_timeout(3000)

        # clicar Ente Privado
        page.locator("text=Ente Privado").first.click()
        page.wait_for_timeout(1000)

        # preencher CNPJ
        page.fill('input[type="text"]', cnpj)
        page.keyboard.press("Enter")

        page.wait_for_timeout(6000)

        rows = page.query_selector_all("table tbody tr")

        if rows:
            has_restrictions = True
            for row in rows:
                cols = row.query_selector_all("td")
                if len(cols) >= 4:
                    resultados.append([
                        cols[0].inner_text(),
                        cols[1].inner_text(),
                        cols[2].inner_text(),
                        cols[3].inner_text()
                    ])

        browser.close()

    return {
        "status": "completed",
        "data": resultados,
        "has_restrictions": has_restrictions
    }
