from typing import Dict
from pydantic import BaseModel, Field


# StructuredOutputSchema
class CypherCheckResponse(BaseModel):
    is_lagal: bool = Field(description="当前语句是否为合法语句，如果是，则返回True, 否则返回False")
    error_msg:str=Field(description="如果is_legal为False,返回具体错误信息，否则返回空字符串")
    solve_method:str=Field(description="如果is_legal为False,返回解决方法，否则返回空字符串")
    original_cypher:str=Field(description="原始输入的Cypher语句")

# ToolsSchema
class CheckSyntaxError(BaseModel):
    cypher: str = Field(description="需要检测是否合法的cypher语句")

class Neo4jQueryParams(BaseModel):
    cypher:str = Field(description="需要执行的Cypher查询语句")
    params:dict[str,str]=Field(
        default=None,
        description="cypher查询语句当中的参数，字典形式。没有参数，使用默认值{}")

class EntityAlignmentList(BaseModel):
    entitys_to_alignment:list[Dict[str,str]] = Field(description="当前所需要对齐的所有实体的列表，每个需要对齐的实体为一个字典，key包含entity和label，entity为需要对齐的实体，label为实体对应的在知识图谱当中的label名称")
