import logging

import jieba
import lancedb
from pydantic import create_model
from lancedb.pydantic import LanceModel, Vector
from lancedb.rerankers import RRFReranker

logger = logging.getLogger(__name__)


def create_vector_schema(embedding_dim: int):
    return create_model(
        "CardInfoVectorSchema",
        __base__=LanceModel,
        text=(str, ...),
        tokenized_text=(str, ...),
        vector=(Vector(embedding_dim), ...),
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
        self.client = lancedb.connect(url)
        self.table_schema = create_vector_schema(embedding_dim)
        self.fts_index_exist = False

        try:
            self._table = self.client.open_table(table_name)
        except ValueError as e:
            logger.warning(f"Table {table_name} does not exist. Automatically create table.")
            self._table = self.client.create_table(table_name, schema=self.table_schema)
        except Exception:
            raise

    def insert(
        self, 
        texts: list[str], 
        vectors: list[list[float]], 
        card_ids: str,
        bank_codes: str,
        card_name: str,
        mode: str = "append"
    ) -> None:
        """Insert data into the lancedb table.
        Args:
            texts: The texts to be inserted.
            vectors: The vectors to be inserted.
            card_ids: The card ids to be inserted.
            bank_codes: The bank codes to be inserted.
            card_name: The card names to be inserted.
            mode: The mode of the insert operation. This mode can be `append` or `overwrite`, default is `append`.
        """
        if len({len(texts), len(vectors)}) != 1:
            raise ValueError("The length of parameters must be the same.")
        
        data = [
            self.table_schema(
                text=text,
                tokenized_text=" ".join(jieba.cut_for_search(text)),
                vector=vector,
                card_id=card_ids,
                card_name=card_name,
                bank_code=bank_codes,
            )
            for text, vector in zip(texts, vectors)
        ]

        self._table.add(data, mode=mode)
        
        if not self.fts_index_exist:
            self._table.create_fts_index("tokenized_text", use_tantivy=False)
            self._table.wait_for_index(["tokenized_text_idx"])
        else:
            self.fts_index_exist = any(
                "tokenized_text" in index.columns
                for index in self._table.list_indices() 
            )
        

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

    def hybird_search(
        self, 
        query: str, 
        vector:list[float], 
        reranker: bool = False,
        top_k: int = 20, 
    ) -> list[tuple[str, str, str, str]]:
        """Search for similar rows in the lancedb table.
        
        Args:
            query: The text used to search for relevant answers.
            vector: The vector representation of the query, used for searching relevant answers. This vector should be computed from the query.
            reranker: Indicates whether to use a reranking system to improve accuracy.
            top_k: The number of results to return.

        Returns:
            The search results are returned in order of relevance, from highest to lowest.
            The returned result includes `text`, `card_id`, `card_name`, and `bank_code`.
        """
        
        tokenized_query = " ".join(jieba.cut_for_search(query))
        queryBuilder = self._table.search(query_type="hybrid", vector_column_name="vector", fts_columns="tokenized_text").vector(vector).text(tokenized_query)

        if reranker:
            reranker = RRFReranker(top_k*2)
            queryBuilder = queryBuilder.rerank(reranker)
        
        results = queryBuilder.limit(top_k).to_pydantic(self.table_schema)

        return [
            (res.text, res.card_id, res.card_name, res.bank_code)
            for res in results
        ]