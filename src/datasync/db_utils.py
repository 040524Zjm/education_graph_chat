import pymysql
from neo4j import GraphDatabase
from langchain_huggingface import HuggingFaceEmbeddings
from pymysql.cursors import Cursor, DictCursor
from configuration import config


class MySQLReader:

    def __init__(self):
        self.connection = pymysql.connect(**config.MYSQL_CONFIG)
        self.cursor = self.connection.cursor(DictCursor)

    def read_data(self, sql):
        self.cursor.execute(sql)
        return self.cursor.fetchall()

    def close(self):
        self.cursor.close()
        self.connection.close()

    def write_data(self, data, sql, batch_size=200):
        print(f"当前写入的数据为：{data}")
        for i in range(0, len(data), batch_size):
            data_batch = data[i:i + batch_size]
            self.cursor.executemany(sql, data_batch)
            self.connection.commit()


class Neo4jWriter:

    def __init__(self):
        self.neo4j_driver = GraphDatabase.driver(uri=config.NEO4J_CONFIG["uri"], auth=config.NEO4J_CONFIG["auth"])
        self.embedding = HuggingFaceEmbeddings(model_name=str(config.EMBEDDING_MODEL_PATH),
                                               model_kwargs={"device": config.DEVICE})  # 需要下载带cuda版本的torch
        self.embedding_dim = len(self.embedding.embed_query("Hello"))

    def write_nodes(self, label, batch_data, batch_size=20):
        if len(batch_data) == 0:
            return
        data_keys = batch_data[0].keys()
        property_stat = ", ".join([f"{key}:row.{key}" for key in data_keys])

        for i in range(0, len(batch_data), batch_size):
            batch = batch_data[i:i + batch_size]
            cypher_stat = (
                "UNWIND $batch as row "
                f"MERGE (n:{label} {{"
                f"{property_stat}"
                "})"
            )
            print("当前执行的cypher为：\n", cypher_stat)
            self.neo4j_driver.execute_query(cypher_stat, batch=batch)

    def write_relationship(self, start_node_label, end_node_label, relationships, batch_size=20):
        if len(relationships) == 0:
            return
        relationship_type = relationships[0]["relation_type"]
        for i in range(0, len(relationships), batch_size):
            batch = relationships[i:i + batch_size]
            cypher = f"""
            UNWIND $batch as row
            MATCH (start:{start_node_label} {{id:row.start_id}}),(end:{end_node_label} {{id:row.end_id}})
            MERGE (start) - [:{relationship_type}]->(end)
            """
            print("当前执行的cypher为：\n", cypher)
            self.neo4j_driver.execute_query(cypher, batch=batch)

    def write_full_text_index(self, label, label_property, index_name):
        cypher = f"""
        CREATE FULLTEXT INDEX $name 
        IF NOT EXISTS 
        FOR (n:{label}) 
        ON EACH [n.{label_property}]
        OPTIONS {{
        indexConfig: {{
            `fulltext.analyzer`:'cjk'
        }}
        }}

        """
        print("当前执行的cypher为：\n", cypher)
        self.neo4j_driver.execute_query(cypher, name=index_name)

    def write_vector_index(self, label, label_property, embedding_property, batch_size=20):
        query_data_cypher = f"""
        MATCH (n:{label})
        WHERE n.{label_property} is not null
        return n.id as id, n.{label_property} as text
        """
        result = self.neo4j_driver.execute_query(query_data_cypher)
        records = result.records
        print(f"查询到节点数：{len(records)}")
        for i in range(0, len(records), batch_size):
            nodes = records[i:i + batch_size]
            to_embed_text = [node["text"] for node in nodes]
            embedded_vectors = self.embedding.embed_documents(to_embed_text)
            for node, embed in zip(nodes, embedded_vectors):
                update_query = f"""
                MATCH(n:{label})
                where n.id = $id
                set n.{embedding_property} = $embedding
                """
                self.neo4j_driver.execute_query(update_query, parameters_={"id": node["id"], "embedding": embed})

        create_index_cypher = f"""
        CREATE VECTOR INDEX {label + "_" + label_property + "vector_index"}
        IF NOT EXISTS
        FOR (n:{label})
        on n.{embedding_property}
        OPTIONS {{
            indexConfig:{{
                `vector.dimensions`:{self.embedding_dim},
                `vector.similarity_function`:'cosine'
            }}
        }}
        """
        self.neo4j_driver.execute_query(create_index_cypher)


if __name__ == '__main__':
    writer = Neo4jWriter()
    # writer.write_full_text_index(label="BaseSubjectInfo",label_property='name',index_name="BaseSubjectInfo_name")
    writer.write_vector_index(label="BaseSubjectInfo", label_property="name", embedding_property="name_embed")
