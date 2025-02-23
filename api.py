import subprocess
from typing import Union

from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse

from utils.config_utils import get_bank_and_card_name

config_path = './card.yaml'

# Crawl specify bank
async def start_spider(url: str, bank_code: str):
    if not url or not bank_code:
        return False
    
    # Run the Scrapy spider
    try:
        result = subprocess.run(
            ['scrapy', 'crawl', 'tccic', '-a', f'url={url}', '-a', f'bank_code={bank_code}'],
            capture_output=True,
            text=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"An error occurred: {e.stderr}")
        return False


app = FastAPI()

# Test connection
@app.get("/")
async def welcome():
    return {"Hello World"}


# Do RAG from crawled data
@app.post("/rag")
async def start_rag(url: str = Form(...), bank_code: str = Form(...)):
    spider_status = await start_spider(url, bank_code)
    if not spider_status:
        return JSONResponse(content={"status": "error", "msg": "An error occurred during the crawl."}, status_code=400)
    

    bank_name, card_name = get_bank_and_card_name(config_path, bank_code, url)
    if not bank_name or not card_name:
        return JSONResponse(content={"status": "error", "msg": "No bank or card found."}, status_code=400)
    
    return JSONResponse(content={"status": "success", "data": {"bank": bank_name, "card": card_name}}, status_code=200)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=1122)