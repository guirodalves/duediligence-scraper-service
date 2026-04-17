from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"message": "API OK"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/collect")
def collect():
    return {"status": "test ok"}
