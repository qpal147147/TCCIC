import os
import json
import uuid
import re
import time
import logging
from pathlib import Path
from typing import List
from tqdm import tqdm

from markdownify import markdownify as md
from dotenv import load_dotenv
from llama_index.core import Document, StorageContext
from llama_index.core import Settings
from llama_index.core import VectorStoreIndex
from llama_index.core.node_parser import MarkdownNodeParser, SimpleFileNodeParser, SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from llama_index.llms.ollama import Ollama
from llama_index.llms.gemini import Gemini

class RAG():
    def __init__(self, json_path: str, llm: str, temperature: float, embedding: str, logger: logging.Logger = None):
        load_dotenv()

        # Logger
        if logger is None:
            self.logger = logging.getLogger("null_logger")
            self.logger.handlers = [logging.NullHandler()]
        else:
            self.logger = logger

        # load json data
        self.json_data = self.load_json(json_path)
        self.bank_name = self.json_data['bank']
        self.card_name = self.json_data['card']
        self.last_update = self.json_data['date'] 

        # set data path
        self.md_dir = f"./data/{self.bank_name}/{self.card_name}/mdfiles"
        self.lancedb_path = f"./data/{self.bank_name}/{self.card_name}/lancedb"
        Path(self.md_dir).mkdir(parents=True, exist_ok=True)

        # set llm and embedding
        self.llm = llm
        self.embedding = embedding
        self.temperature = temperature
        self._prompt = """
        以下是整個文檔的內容:
        <document>
        {WHOLE_DOCUMENT}
        </document>

        以下是文檔中的一個chunk(段落):
        <chunk>
        {CHUNK_CONTENT}
        </chunk>

        請給出一個短而簡潔的上下文，說明這個chunk(段落)在整個文檔中的位置或意義。僅回答上下文摘要，無需其他內容。
        """
        
        Settings.llm = Gemini(api_key=os.getenv("GOOGLE_API_KEY"), model=self.llm, temperature=self.temperature)
        # Settings.llm = Ollama(model=self.llm, request_timeout=300.0)
        Settings.embed_model = HuggingFaceEmbedding(model_name=self.embedding, token=os.getenv("HF_TOKEN"))

    def load_json(self, json_path: str):
        try:
            self.logger.info(f"Loading JSON from {json_path}")

            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        except FileNotFoundError:
            raise Exception(f"The {json_path} file is not found")
    
    def embed_text(self):
        try:
            sentence_splitter = SentenceSplitter(
                chunk_size=512, 
                chunk_overlap=128, 
                paragraph_separator="\n\n",
                secondary_chunking_regex="[^,.;。？！]+[,.;。？！]?",
                separator=" "
            )
            pages = self.json_data['pages']

            # create md files and split into chunks
            self.logger.info(f"Find {len(pages)} pages and start to split into chunks...")

            docs = []
            for i, page in enumerate(pages, start=1):
                md_text = md(page['html_content'], strip=['a', 'img'])
                Path(f"{self.md_dir}/page_{i}.md").write_text(md_text)

                doc = Document(
                    text=md_text, 
                    extra_info={
                        'url': page['url'],
                        'whole_content': md_text,
                        'original_content': "",
                        'contextualized_content': ""
                    },
                    excluded_llm_metadata_keys=["url", "whole_content", "original_content", "contextualized_content"],
                    excluded_embed_metadata_keys = ["url", "whole_content", "original_content", "contextualized_content"],
                    id_=str(uuid.uuid4()),
                )
                docs.append(doc)

            nodes = sentence_splitter.get_nodes_from_documents(docs, show_progress=True)

            # create context for each chunk
            self.logger.info(f"Find {len(nodes)} chunks and start to create context for each chunk...")

            for node in tqdm(nodes, desc="Creating context for each chunk"):
                whole_document = node.metadata['whole_content']
                chunk_content = node.get_content()
                response = Settings.llm.complete(self._prompt.format(WHOLE_DOCUMENT=whole_document, CHUNK_CONTENT=chunk_content))
                
                # update node metadata
                node.metadata['original_content'] = chunk_content
                node.metadata['contextualized_content'] = response.text
                node.set_content(f"{response.text}\n\n{chunk_content}")

                time.sleep(1.1) # avoid rate limit. Gemini: 30RPM
            
            # create vector store and save index
            if nodes:
                self.logger.info(f"Start to create vector store...")

                vector_store = LanceDBVectorStore(uri=self.lancedb_path, table_name="vectors", mode="overwrite")
                storage_context = StorageContext.from_defaults(vector_store=vector_store)
                index = VectorStoreIndex(nodes, storage_context=storage_context, show_progress=True)
            else:
                raise Exception("No nodes found, so no vector store created.")

            self.logger.info(f"Vector store created successfully.")
            return True
        except Exception as e:
            self.logger.error(f"Error during embedding process. Error:\n{e}")
            return False
        

    def complete(self, query):
        # define return structure
        json_data = {
            "bank": self.bank_name,
            "card": self.card_name,
            "last_update": self.last_update,
            "source_data": [],
            "response": "",
        }

        # check if the vector file exists
        if not Path(self.lancedb_path).exists():
            self.logger.error(f"Path '{self.lancedb_path}' does not exist, so automatically embedding.")

            embedding_flag = self.embed_text()
            if not embedding_flag:
                json_data["response"] = "Error during embedding process."
                return json_data

        # check if table exists
        self.logger.info(f"Loading vector data from {self.lancedb_path}")

        vector_store = LanceDBVectorStore(uri=self.lancedb_path)
        if not vector_store._table_exists("vectors"):
            self.logger.error("Table 'vectors' does not exist.")

            json_data["response"] = "Table 'vectors' does not exist."
            return json_data
        
        # load data from vector store
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
        query_engine = index.as_query_engine(similarity_top_k=20)
        response = query_engine.query(query)

        # add source data to response
        json_data["source_data"] += [
            {
                "text": source_node.node.get_content(),
                "score": source_node.score,
                "url": source_node.metadata['url'],
            } 
            for source_node in response.source_nodes
        ]
        json_data["response"] = response.response

        return json_data