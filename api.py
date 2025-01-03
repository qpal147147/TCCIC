from typing import Union
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import subprocess

app = FastAPI()

@app.get("/")
async def welcome():
    return {"Hello World"}

@app.get("/start")
async def start_spider():
    subprocess.run(['scrapy', 'crawl', 'tccic'])
    return JSONResponse(content="success", status_code=200) 

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=1122)