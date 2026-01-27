import neo4j
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
from configuration import config
from langchain_neo4j import Neo4jGraph
from langchain_huggingface import HuggingFaceEmbeddings
neo4j_driver = neo4j.GraphDatabase.driver(
    uri=config.NEO4J_CONFIG["uri"],
    auth=config.NEO4J_CONFIG["auth"]
)
neo4j_schema = Neo4jGraph(
    url=config.NEO4J_CONFIG['uri'],
    username=config.NEO4J_CONFIG['auth'][0],
    password=config.NEO4J_CONFIG['auth'][1],
    database='neo4j',
).get_schema

embedding_model = HuggingFaceEmbeddings(
    model_name=config.EMBEDDING_MODEL_PATH,
    model_kwargs={'device': config.DEVICE}
)