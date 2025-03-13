import json
import uuid
from pathlib import Path

from markdownify import markdownify as md
from dotenv import load_dotenv
from llama_index.core import Document, StorageContext
from llama_index.core import Settings
from llama_index.core import VectorStoreIndex
from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from llama_index.llms.ollama import Ollama
from llama_index.llms.gemini import Gemini

class RAG():
    def __init__(self, json_path: str):
        self.json_data = self.load_json(json_path)
        self.bank_name = self.json_data['bank']
        self.card_name = self.json_data['card']
        self.last_update = self.json_data['data']
        self.lancedb_path = f"./data/{self.bank_name}/{self.card_name}/lancedb"

        load_dotenv()

        # create models
        Settings.llm = Gemini(model="models/gemini-2.0-flash-lite")
        # Settings.llm = Ollama(model="cwchang/llama3-taide-lx-8b-chat-alpha1:q4_k_s", request_timeout=300.0)
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
        try:
            md_parser = MarkdownNodeParser()
            pages = self.json_data['pages']

            docs = []
            for page in pages:
                md_text = md(page['html_content'], strip=['a', 'img'])
                doc = Document(
                    text=md_text, 
                    extra_info={'url': page['url']}, 
                    excluded_llm_metadata_keys=["url"],
                    excluded_embed_metadata_keys = ["url"],
                    id_=str(uuid.uuid4()),
                )
                docs.append(doc)
                
            nodes = md_parser.get_nodes_from_documents(docs, show_progress=True)
            
            # create vector store and save index
            vector_store = LanceDBVectorStore(uri=self.lancedb_path, mode="overwrite")
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            index = VectorStoreIndex(nodes, storage_context=storage_context, show_progress=True)

            return True
        except Exception as e:
            print(f"Error during embedding process. Error:\n{e}")
            return False
        

    def complete(self, query):
        # define return data
        json_data = {
            "bank": self.bank_name,
            "card": self.card_name,
            "last_update": self.last_update,
            "source_data": [],
            "response": "",
        }

        # check if json file exists
        if not Path(self.lancedb_path).exists():
            print(f"Path '{self.lancedb_path}' does not exist, so automatically embedding.")
            embedding_flag = self.embedding()
            if not embedding_flag:
                json_data["response"] = "Error during embedding process."
                return json_data

        # check if table exists
        vector_store = LanceDBVectorStore(uri=self.lancedb_path)
        if not vector_store._table_exists("vectors"):
            json_data["response"] = "Table 'vectors' does not exist."
            return json_data
        
        # load data from vector store
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
        query_engine = index.as_query_engine(similarity_top_k=2)
        response = query_engine.query(query)

        # format response
        json_data["source_data"] += [
            {
                # "text": source_node.node.text, 
                "score": source_node.score,
                "url": source_node.metadata['url'],
            } 
            for source_node in response.source_nodes
        ]
        json_data["response"] = response.response

        return json_data