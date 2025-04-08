import subprocess
import shutil
from pathlib import Path

from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse

from utils.config_utils import get_bank_config, get_llm_config, get_embedding_config
from utils.logger import setup_logger
from rag import RAG


# set up logging
logger_crawler = setup_logger("app.crawler", "crawler.log")
logger_analyzer = setup_logger("app.llm", "llm.log")

# set config path
CARD_CONFIG_PATH = './config/card.yaml'
MODEL_CONFIG_PATH = './config/model.yaml'

# get config
llm_cfg = get_llm_config(MODEL_CONFIG_PATH, "gemini")
embedding_cfg = get_embedding_config(MODEL_CONFIG_PATH, "huggingFace")

# crawl specify bank
async def start_spider(url: str, card_name: str, bank_code: str):
    if not url or not bank_code or not card_name:
        return False
    
    # Run the Scrapy spider
    try:
        result = subprocess.run(
            [
                'scrapy', 'crawl', 'tccic',
                '-a', f'url={url}', 
                '-a', f'card_name={card_name}', 
                '-a', f'bank_code={bank_code}', 
                '-a', f'config={CARD_CONFIG_PATH}'
            ],
            capture_output=True,
            text=True,
            check=True
        )
        logger_crawler.info(result.stderr)

        return True
    except subprocess.CalledProcessError as e:
        print(f"An error occurred: {e.stderr}")
        return False


app = FastAPI()

@app.get("/")
async def welcome():
    return {"Hello World"}


@app.post("/llm")
async def start_llm(url: str = Form(...), card_name: str = Form(...), bank_code: str = Form(...), query: str = Form(...)):
    # get bank and card name
    bank_name = get_bank_config(CARD_CONFIG_PATH, bank_code)['bank_name']
    if not bank_name:
        return JSONResponse(content={"status": "error", "msg": f"The {bank_code} not found."}, status_code=400)
    
    # check if json file exists
    json_path = f"./data/{bank_name}/{card_name}/data.json"
    if not Path(json_path).exists():
        spider_status = await start_spider(url, card_name, bank_code)
        if not spider_status:
            return JSONResponse(content={"status": "error", "msg": "An error occurred during the crawl."}, status_code=400)
    
    # do rag
    # rag = RAG(json_path, llm_cfg["model"], embedding_cfg["model"], llm_cfg["temperature"])
    # json_data = rag.complete(query)
    
    return JSONResponse(content={"status": "success", "msg": 'json_data'}, status_code=200)


@app.post("/recrawl")
async def recrawl(url: str = Form(...), card_name: str = Form(...), bank_code: str = Form(...)):
    spider_status = await start_spider(url, card_name, bank_code)
    if not spider_status:
        return JSONResponse(content={"status": "error", "msg": "An error occurred during the crawl."}, status_code=400)
    
    # do embedding
    # bank_name, card_name = get_bank_and_card_name(CARD_CONFIG_PATH, bank_code, url)
    # json_path = f"./data/{bank_name}/{card_name}/data.json"
    # RAG(json_path, llm_cfg["model"], embedding_cfg["model"], llm_cfg["temperature"]).embed_text()

    return JSONResponse(content={"status": "success", "msg": "Recrawl Successfully"}, status_code=200)


@app.post("/clean")
async def clean():
    data_folder = Path("./data")
    if data_folder.exists():
        shutil.rmtree(data_folder)
    data_folder.mkdir(parents=True, exist_ok=True)

    return JSONResponse(content={"status": "success", "msg": "Clean Successfully"}, status_code=200)



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=1122)