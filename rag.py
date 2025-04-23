import os
import json
import uuid
import re
import time
import logging
from pathlib import Path
from typing import List
from tqdm import tqdm
from enum import Enum

import jieba
from markdownify import markdownify as md
from dotenv import load_dotenv
from llama_index.core import Document, StorageContext, VectorStoreIndex, Settings
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.postprocessor import SentenceTransformerRerank
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from llama_index.llms.ollama import Ollama
from llama_index.llms.gemini import Gemini
from llama_index.retrievers.bm25 import BM25Retriever


class SearchType(Enum):
    VECTOR = "vector"
    BM25 = "bm25"
    HYBRID = "hybrid"


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
        self.vectordb_path = f"./data/{self.bank_name}/{self.card_name}/lancedb"
        Path(self.md_dir).mkdir(parents=True, exist_ok=True)

        # set llm and embedding
        self.renaker = SentenceTransformerRerank(model="BAAI/bge-reranker-v2-m3")
        Settings.llm = Gemini(api_key=os.getenv("GOOGLE_API_KEY"), model=llm, temperature=temperature)
        # Settings.llm = Ollama(model=self.llm, request_timeout=300.0)
        Settings.embed_model = HuggingFaceEmbedding(model_name=embedding, token=os.getenv("HF_TOKEN"))

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
        

    def chinese_tokenizer(self, text: str) -> List[str]:
        return list(jieba.cut(text))
    
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

                time.sleep(1.5) # avoid rate limit. Gemini: 30RPM
            
            # create vector store and save index
            if nodes:
                self.logger.info(f"Start to create vector store...")

                vector_store = LanceDBVectorStore(uri=self.vectordb_path, table_name="vectors", mode="overwrite")
                storage_context = StorageContext.from_defaults(vector_store=vector_store)
                index = VectorStoreIndex(nodes, storage_context=storage_context, show_progress=True)
            else:
                raise Exception("No nodes found, so no vector store created.")

            self.logger.info(f"Vector store created successfully.")
            return True
        except Exception as e:
            self.logger.error(f"Error during embedding process. Error:\n{e}")
            return False
        

    def complete(self, query: str, topk: int = 20, search_type: SearchType = SearchType.VECTOR, reanker: bool = False):
        # define return structure
        json_data = {
            "bank": self.bank_name,
            "card": self.card_name,
            "last_update": self.last_update,
            "source_data": [],
            "response": "",
        }

        # check if the vector file exists
        if not Path(self.vectordb_path).exists():
            self.logger.error(f"Path '{self.vectordb_path}' does not exist, so automatically embedding.")

            embedding_flag = self.embed_text()
            if not embedding_flag:
                json_data["response"] = "Error during embedding process."
                return json_data

        # check if table exists
        self.logger.info(f"Loading vector data from {self.vectordb_path}")

        vector_store = LanceDBVectorStore(uri=self.vectordb_path)
        if not vector_store._table_exists("vectors"):
            self.logger.error("Table 'vectors' does not exist.")

            json_data["response"] = "Table 'vectors' does not exist."
            return json_data
        
        if reanker:
            self.logger.info(f"Reanker enabled.")
            self.renaker.top_n = topk
            topk = topk * 2

        index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
        if search_type == SearchType.VECTOR:
            self.logger.info(f"Search type: Vector search.")

            query_engine = index.as_query_engine(
                similarity_top_k=topk,
                node_postprocessors=[self.renaker] if reanker else None,
            )
        
        elif search_type == SearchType.BM25:
            self.logger.info(f"Search type: BM25 search.")

            # get all nodes from index
            retriever = index.as_retriever(similarity_top_k=10000)
            source_nodes = retriever.retrieve("dummy query")
            nodes = [x.node for x in source_nodes]

            # create bm25 retriever
            bm25_retriever = BM25Retriever.from_defaults(
                nodes=nodes,
                similarity_top_k=topk,
                tokenizer=self.chinese_tokenizer,
            )
            query_engine = RetrieverQueryEngine.from_args(
                bm25_retriever,
                node_postprocessors=[self.renaker] if reanker else None,
            )

        elif search_type == SearchType.HYBRID:
            self.logger.info(f"Search type: Hybrid search.")
            
            # get all nodes from index
            source_nodes = index.as_retriever(similarity_top_k=10000).retrieve("dummy query")
            nodes = [x.node for x in source_nodes]

            # create vector and bm25 retriever
            vector_retriever = index.as_retriever(similarity_top_k=topk)
            bm25_retriever = BM25Retriever.from_defaults(
                nodes=nodes,
                similarity_top_k=topk,
                tokenizer=self.chinese_tokenizer,
            )

            # combine retrievers
            hybrid_retriever = QueryFusionRetriever(
                [vector_retriever, bm25_retriever],
                retriever_weights=[0.6, 0.4],
                similarity_top_k=topk,
                num_queries=1, # set this to 1 to disable query generation
                mode="relative_score",
                use_async=False,
                verbose=True,
            )

            query_engine = RetrieverQueryEngine.from_args(
                hybrid_retriever,
                node_postprocessors=[self.renaker] if reanker else None,
            )
        
        else:
            json_data["response"] = "Invalid search type."
            return json_data

        # execute query
        response = query_engine.query(query)

        # add source data to response
        json_data["source_data"] += [
            {
                "text": source_node.node.get_content(),
                "score": float(source_node.score),  # np.float32 -> float
                "url": source_node.metadata['url'],
            } 
            for source_node in response.source_nodes
        ]
        json_data["response"] = response.response

        return json_data