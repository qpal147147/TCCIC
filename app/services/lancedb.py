from typing import Optional

import jieba
import lancedb
import pandas as pd
from pydantic import create_model
from lancedb.pydantic import LanceModel, Vector
from lancedb.rerankers import RRFReranker

from app.services.schema import VectorDatabaseData

jieba.setLogLevel(20)

def create_vector_schema(embedding_dim: int):
    return create_model(
        "CardInfoVectorSchema",
        __base__=LanceModel,
        text=(str, ...),
        tokenized_text=(str, ...),
        vector=(Vector(embedding_dim), ...),
        url=(str, ...),
        card_id=(str, ...),
        card_name=(str, ...),
        bank_code=(str, ...),
    )


class lanceDBManager:
    def __init__(
        self, 
        url: str, 
        table_name: str, 
        embedding_dim: int
    ) -> None:
        """Initialize the lancedb client.
        Args:
            url: The url of the lancedb server or local path.
            table_name: The name of the table.
            embedding_dim: The dimension of the embedding.
        """
        self._client = lancedb.connect(url)
        self._table_schema = create_vector_schema(embedding_dim)

        try:
            self._table = self._client.open_table(table_name)
        except ValueError as e:
            self._table = self._client.create_table(table_name, schema=self._table_schema)
        except Exception:
            raise

        self._fts_index_exist = self._check_index_exists(self._table, "tokenized_text")


    def _check_index_exists(self, table: lancedb.table.Table, column_name: str) -> bool:
        for index in table.list_indices():
            if column_name in index.columns:
                return True
        return False


    def _get_filter(
        self, 
        card_id: Optional[str] = None,
        bank_code: Optional[str] = None
    ) -> Optional[str]:
        filters = []

        if card_id and card_id.strip():
            filters.append(f"card_id = '{card_id.strip()}'")
        if bank_code and bank_code.strip():
            filters.append(f"bank_code = '{bank_code.strip()}'")
        return " AND ".join(filters) if filters else None


    def insert(
        self, 
        items: list[VectorDatabaseData],
        mode: str = "append"
    ) -> None:
        """Insert data into the lancedb table.
        Args:
            data: The data to be inserted must be a list of VectorDatabaseData.
            mode: The mode of the insert operation. This mode can be `append` or `overwrite`, default is `append`.
        """
        data = [
            self._table_schema(
                text=item.text,
                tokenized_text=" ".join(jieba.cut_for_search(item.text)),
                vector=item.vector,
                url=item.url,
                card_id=item.card_id,
                card_name=item.card_name,
                bank_code=item.bank_code,
            )
            for item in items
        ]

        self._table.add(data, mode=mode)
        
        if not self._fts_index_exist:
            self._table.create_fts_index("tokenized_text", use_tantivy=False)
            self._table.wait_for_index(["tokenized_text_idx"])
            self._fts_index_exist = True


    def delete_rows(
        self, 
        key: str, 
        value: str
    ) -> None:
        """Delete rows from the lancedb table.
        Args:
            key: The key of the row to be deleted.
            value: The value of the row to be deleted.
        """
        self._table.delete(f'{key} = "{value}"')
        if self._table.count_rows() == 0:
            self._fts_index_exist = False


    def hybrid_search(
        self, 
        query: str, 
        vector:list[float], 
        card_id: Optional[str] = None,
        bank_code: Optional[str] = None,
        reranker: bool = False,
        top_k: int = 20, 
    ) -> pd.DataFrame:
        """Search for similar rows in the lancedb table.
        
        Args:
            query: The text used to search for relevant answers.
            vector: The vector representation of the query, used for searching relevant answers. This vector should be computed from the query.
            reranker: Indicates whether to use a reranking system to improve accuracy.
            top_k: The number of results to return.

        Returns:
            The search results are returned in order of relevance, from highest to lowest.
            The returned result includes `text`, `url`, `card_id`, `card_name`, and `bank_code`.
        """
        if not self._fts_index_exist:
            return pd.DataFrame(
                data=[],
                columns=["text", "url", "card_id", "card_name", "bank_code"]
            )
        

        tokenized_query = " ".join(jieba.cut_for_search(query))
        query_builder = self._table.search(query_type="hybrid", vector_column_name="vector", fts_columns="tokenized_text")
        
        if filter_str := self._get_filter(card_id, bank_code):
            query_builder = query_builder.where(filter_str)
            
        query_builder = query_builder.vector(vector).text(tokenized_query)

        if reranker:
            reranker = RRFReranker(top_k*2)
            query_builder = query_builder.rerank(reranker)
        
        results = query_builder.limit(top_k).to_pydantic(self._table_schema)

        return pd.DataFrame(
            data=[
                (res.text, res.url, res.card_id, res.card_name, res.bank_code)
                for res in results
            ],
            columns=["text", "url", "card_id", "card_name", "bank_code"]
        )