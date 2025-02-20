from typing import Union
from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse
import subprocess
from pydantic import BaseModel

HOST="127.0.0.1"
PORT=1122

app = FastAPI()

# Test connection
@app.get("/")
async def welcome():
    return {"Hello World"}


# Crawl specify bank
@app.post("/crawl")
async def start_spider(url: str = Form(...), bank: str = Form(...)):
    if not url or not bank:
        return JSONResponse(content={"status": "error", "msg": "URL and bank are required"}, status_code=400)
    
    subprocess.run(['scrapy', 'crawl', 'tccic', '-a', f'url={url}', '-a', f'bank={bank}'])
    return JSONResponse(content={"status": "success"}, status_code=200) 


# Do RAG from crawled data
@app.post("/rag")
async def start_spider(url: str = Form(...), bank: str = Form(...)):
    pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)