import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from routers.index import router as indexrouter
from routers.management import router as managementrouter

app = FastAPI()
app.title = "Index service"
app.version = "0.0.1"

app.include_router(indexrouter)
app.include_router(managementrouter)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Cache-Control", "Content-Type", "Connection"]
)

@app.get("/", tags=["home"])
def message():
    return HTMLResponse("<h1>Service: Index</h1>")

if __name__ == "__main__":
    uvicorn.run("main:app", host="localhost", port=8000)