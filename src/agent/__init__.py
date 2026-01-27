from langchain.agents import create_agent
from langchain_deepseek import ChatDeepSeek
# from langchain_openai import ChatOpenAI
# from langchain_ollama import ChatOllama
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from agent.schema import CheckSyntaxError, EntityAlignmentList,Neo4jQueryParams
from agent.tools_def import check_syntax_error,neo4j_query,entity_alignment
from agent.prompts import major_agent_system_prompt_template
from configuration import config

def get_agent(neo4j_schema):
    """
    创建agent
    :return:
    """
    # 构造llm
    llm = ChatDeepSeek(
        model='deepseek-chat',

    )
    # 构造tools
    neo4j_query_tool = tool(neo4j_query, args_schema=Neo4jQueryParams)
    check_syntax_tool = tool(check_syntax_error, args_schema=CheckSyntaxError)
    entity_alignment_tool = tool(entity_alignment, args_schema=EntityAlignmentList)

    # memory
    memory_saver = InMemorySaver() if config.AGENT_WITH_MEMORY else None

    # 构建Agent
    agent = create_agent(
        model=llm,
        tools=[neo4j_query_tool, check_syntax_tool, entity_alignment_tool],
        checkpointer=memory_saver,
        system_prompt=major_agent_system_prompt_template.format(neo4j_schema=neo4j_schema)
    )
    return agent









