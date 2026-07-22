from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

app = FastAPI(title="Catalog Service")


@app.get("/")
def root():
    return {"message": "Catalog Service API is ready."}


@app.get("/health")
def health():
    return {"status": "ok"}
