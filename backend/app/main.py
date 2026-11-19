from fastapi import FastAPI

app = FastAPI(title="ChronOS")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
