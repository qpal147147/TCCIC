import json
import uuid

from markdownify import markdownify as md
from llama_index.core import Document
from llama_index.core.node_parser import HTMLNodeParser, MarkdownNodeParser
from llama_index.core import Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.ollama import Ollama
from llama_index.core import VectorStoreIndex

class RAG():
    def __init__(self, json_path: str):
        self.json_data = self.load_json(json_path)
        self.bank_name = self.json_data['bank']
        self.card_name = self.json_data['card']
        self.last_update = self.json_data['data']

        Settings.llm = Ollama(model="cwchang/llama3-taide-lx-8b-chat-alpha1:q4_k_s", request_timeout=120.0)
        Settings.embed_model = HuggingFaceEmbedding(model_name="intfloat/multilingual-e5-large")

    def load_json(self, json_path: str):
        try:        
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        except FileNotFoundError:
            print(f"File not found: {self.json_path}")
            return None
    
    def embedding(self):
        parser = HTMLNodeParser()
        # parser = MarkdownNodeParser()
        pages = self.json_data['pages']

        docs = []
        for page in pages:
            # md_text = md(page['html_content'])
            html_doc = Document(text=page['html_content'], extra_info={'url': page['url']}, id_=str(uuid.uuid4()))
            docs.append(html_doc)

        nodes = parser.get_nodes_from_documents(docs, show_progress=True)
        index = VectorStoreIndex(nodes, show_progress=True)
        query_engine = index.as_query_engine()
        response = query_engine.query("信用卡片的名稱是甚麼?")
        print(response)

        breakpoint()


    def complete(self):
        pass