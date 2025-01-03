from typing import Union
from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse
import subprocess
from pydantic import BaseModel

app = FastAPI()

'''
define pydantic model for request body
'''
class UrlRequest(BaseModel):
    url: str

'''
define the route for the API
'''
@app.get("/")
async def welcome():
    return {"Hello World"}


@app.post("/start")
async def start_spider(url: str = Form(...)):
    if not url:
        return JSONResponse(content={"status": "error", "msg": "URL is required"}, status_code=400)
    
    subprocess.run(['scrapy', 'crawl', 'tccic', '-a', f'url={url}'])
    return JSONResponse(content={"status": "success"}, status_code=200) 

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=1122)