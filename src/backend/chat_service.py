from langchain_core.messages import ToolMessage
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_neo4j import Neo4jGraph, Neo4jVector
from neo4j_graphrag.types import SearchType

from agent import get_agent
from configuration import config

import logging
Logger = logging.getLogger(__file__) # 精准定位日志是哪个文件产生的

class ChatService:
    def __init__(self):
        self.embeddings = HuggingFaceEmbeddings(
            model_name=config.EMBEDDING_MODEL_PATH,
            model_kwargs=config.DEVICE,
        )
        self.neo4j_store = Neo4jGraph(
            url=config.NEO4J_CONFIG['uri'],
            username=config.NEO4J_CONFIG['auth'][0],
            password=config.NEO4J_CONFIG["auth"][1],
            database="neo4j",
        )
        self.agent = get_agent(self.neo4j_store.schema)
        # 针对于每一个实体，维护一个Neo4jVector的实例，后面利用该实例来完成搜索

        # 仅用于演示，后面不使用neo4j所提供的索引进行检索
        # self.vector_stores = {
        #     "CourseInfo": Neo4jVector.from_existing_index(
        #         url=config.NEO4J_CONFIG["uri"],
        #         username = config.NEO4J_CONFIG['auth'][0],
        #         password = config.NEO4J_CONFIG['auth'][1],
        #         embedding=self.embeddings,
        #         index_name="CourseInfo_namevector_index",
        #         keyword_index_name="course_name_index",
        #         search_type=SearchType.HYBRID
        #     )
        # }

    def chat(self,user_query,session_id):
        """
        聊天入口，根据配置决定是否流式输出
        :param user_query:
        :param session_id:
        :return:
        """
        agent_config = {"configurable":{"thread_id":session_id}}
        # 流式输出
        if config.AGENT_STREAM_OUTPUT:
            for content_tuple in  self.agent.stream({"messages":[("user",user_query)]},config=agent_config,stream_mode="messages"):
                if isinstance(content_tuple[0],ToolMessage) or content_tuple[0].content == "":
                    continue
                yield content_tuple[0].content
        # 非流式输出
        else:
            result = self.agent.invoke({"messages":[("user",user_query)]},config=agent_config)
            yield result["messages"][-1].content


if __name__ == '__main__':
    pass

