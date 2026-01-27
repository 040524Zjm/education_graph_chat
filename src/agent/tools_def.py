from langchain_core.prompts import PromptTemplate
from langchain_deepseek import ChatDeepSeek
from torch.distributed.elastic.events import record

from agent.prompts import cypher_checker_prompt
from agent.schema import CypherCheckResponse
from datasync.entity_alignment import EntityAlignment
from configuration.dependency import neo4j_driver, neo4j_schema, embedding_model

import logging
logger = logging.getLogger(__file__)

# 维护当前Neo4j当中实体所对应的index的列表，每个实体存在两个Index，以list形式存储，第一个为全文索引，第二个为向量索引
# hybrid_store_list = {
#     "CourseInfo": ["course_name_index","CourseInfo_namevector_index"],
#     "ChapterInfo": ["ChapterInfoNameIndex","ChapterInfoNameVectorIndex"],
# }
hybrid_store_list=['category','subject','category','chapter']

cypher_check_llm = ChatDeepSeek(
    model='deepseek-chat',
).with_structured_output(CypherCheckResponse)

ea = EntityAlignment()

def hybrid_search_query(
        query_text,
        full_text_index_name,
        vector_index_name,
        driver=neo4j_driver,
        top_k=1,
        alpha=0.5,
        threshold=0.5
    ):
    vector_list = embedding_model.embed_query(query_text)
    res = driver.execute_query(
        """
        CALL () {
        
        CALL db.index.vector.queryNodes(%vector_index_name, $top_k, $query_vector)
        YIELD node, score
        WITH node, score LIMIT $top_k
        return node, score*$alpha as score
        
        UNION
        
        CALL db.index.fulltext.queryNodes($full_text_name, $query_text, {limit: top_k})
        YIELD node, score
        WITH collect({node:node, score:score}) AS nodes, max(score) AS max_score
        UNWIND nodes as n
        RETURN n.node as node, n.score*(1 - $alpha) / max_score as score
        }
        WITH node, sum(score) AS score ORDER BY score DESC LIMIT $top_k
        RETURN node.`name` AS text, score, node {.*, `name`: Null, `name_embedding`: Null, id: Null } AS metadata
        """,

        parameters_={
            "vector_index_name": vector_index_name,
            "top_k": top_k,
            "query_vector": vector_list,
            "fulltext_index_name": full_text_index_name,
            "query_text": query_text,
            "alpha": alpha
        }
    ).records
    return [
        {"text":record["text"], "score":record["score"]}
            for record in res
            if record["score"] > threshold
    ]

def entity_alignment(entitys_to_alignment:list):
    """
    当需要将用户的查询问题当中的实体对齐到图数据库当中已有的实体时，可以使用当前工具
    :param entity_to_alignment_list:
    :return:
    """
    logger.info(f"开始调用工具：entity_alignment，对齐参数为：{entitys_to_alignment}")
    for node in entitys_to_alignment:
        if node['label'] in hybrid_store_list:
            res = ea(node['entity'], node['label'])

            # results = hybrid_search_query(node['entity'],full_text_index_name=hybrid_store_list[node['label']][0],vector_index_name=hybrid_store_list[node['label']][1])
            if res:
                node['entity'] = res
    return entitys_to_alignment

def check_syntax_error(cypher:str):
    """
    当需要检查cypher语句是否存在语句错误，或者是否不符合已有schema结构时使用
    当执行Cypher语句前，必须要使用该工具来进行检测Cypher语句的合法性
    """
    logger.info("开始调用工具：check_syntax_error")
    logger.info(f"当前需要校验的Cypher语句为:{cypher}")
    prompt = PromptTemplate.from_template(cypher_checker_prompt)
    chain = prompt | cypher_check_llm
    res = chain.invoke(
        {
            "neo4j_schema": neo4j_schema,
            "cypher": cypher
        }
    )
    logger.info(f"Cypher语句LLM校验结果为:{res}")
    return res


def neo4j_query(cypher,params=None):
    """
    当需要从neo4j数据库查询数据时使用
    :param cypher:
    :param driver:
    :param params:
    :return:
    """
    logger.info("开始调用工具：neo4j_query")
    logger.info(f"当前调用的cypher为:{cypher},当前调用的params为：{params}",)
    if not params:
        params={}

    driver = globals()['neo4j_driver']
    result = driver.execute_query(cypher,parameters_=params)
    logger.info(f"当前调用cypher结果为:{result.records}")
    return result.records

if __name__ == '__main__':
    pass