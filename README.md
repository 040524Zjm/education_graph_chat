# 教育知识图谱智能问答系统

## 项目信息

- **项目名称**：教育知识图谱智能问答系统（Education Graph Chat）
- **仓库地址**：``

---

## 项目核心目标与解决的问题

本项目旨在构建一个基于**知识图谱**和**大语言模型 Agent** 的智能教育问答系统，解决以下核心问题：

1. **教育知识结构化存储**：将分散的课程、章节、知识点、试卷等教育数据整合为结构化的知识图谱，支持复杂关系查询
2. **自然语言问答**：允许用户用自然语言提问（如"Java课程有哪些章节？"），系统自动理解意图并查询知识图谱返回答案
3. **实体对齐与同义词处理**：解决用户输入中的实体名称与知识图谱中标准实体不一致的问题（如"JAVA" vs "Java"）
4. **安全的 Cypher 查询生成**：通过 LLM Agent 自动生成并校验 Cypher 查询语句，避免语法错误和非法操作
5. **流式交互体验**：提供实时流式响应，提升用户体验

---

## 核心功能与业务流程

### 1. 离线数据构建流程（知识图谱初始化）

```
MySQL 原始数据 
  ↓
数据清洗与规范化
  ↓
UIE 模型抽取知识点实体
  ↓
实体对齐（同义词聚类 → 标准词映射）
  ↓
向量化索引构建（Chroma + Neo4j 向量索引）
  ↓
批量写入 Neo4j 图数据库
```

**详细步骤**：
- **数据导入**：从 `data/edu.sql` 初始化 MySQL 数据库，创建 `entity_mapping` 实体映射表
- **数据读取**：从 MySQL 读取课程信息、章节结构、试卷试题、用户行为等数据
- **文本清洗**：对课程介绍、章节内容等进行 HTML 转义、去重等处理
- **实体抽取**：使用微调后的 UIE 模型从文本中抽取"知识点"等教育领域实体
- **实体对齐**：
  - 使用 DBSCAN 聚类算法对知识点进行同义词归并
  - 选择高频词作为标准词，建立 synonym → std_name 映射
  - 将映射关系写入 MySQL `entity_mapping` 表
- **向量索引**：
  - 将分类、学科、课程、章节、视频、试卷、试题、知识点等实体写入 Chroma 向量库
  - 在 Neo4j 中创建全文索引和向量索引，支持混合检索
- **图数据库写入**：批量创建节点、关系，建立唯一性约束

### 2. 在线问答流程（用户提问 → 智能回答）

```
用户输入自然语言问题
  ↓
FastAPI 接收请求，生成/获取 session_id
  ↓
ChatService 调用 LangChain Agent
  ↓
Agent 工作流：
  1. 判断问题合法性（拒绝修改数据库操作）
  2. 提取问题中的实体（课程/学科/章节等）
  3. 调用实体对齐工具（entity_alignment）
     - 先查 MySQL entity_mapping 表
     - 未命中则使用向量检索（Chroma）兜底
     - 命中后回写 MySQL 映射表
  4. 结合 Neo4j schema 生成 Cypher 查询语句
  5. 调用 Cypher 校验工具（check_syntax_error）
     - 使用 LLM structured output 检查语法
     - 检查是否符合 Neo4j schema
     - 返回错误信息或修复建议
  6. 循环校验直到 Cypher 语句合法
  7. 调用 Neo4j 查询工具（neo4j_query）执行查询
  8. 结合查询结果，生成自然语言回答
  ↓
流式返回回答给前端（StreamingResponse）
  ↓
前端实时渲染 Markdown 格式的回答
```

**关键特性**：
- **会话记忆**：通过 `session_id` 维护对话历史，支持多轮对话上下文理解
- **流式输出**：支持实时流式返回，提升用户体验
- **安全校验**：严格校验 Cypher 语句，防止非法操作和语法错误

---

## 技术栈

### 主框架
- **FastAPI**：Web 框架，提供 RESTful API 和流式响应
- **LangChain / LangGraph**：LLM Agent 编排框架，支持工具调用和记忆管理
- **Uvicorn**：ASGI 服务器

### 大语言模型
- **DeepSeek API**（`deepseek-chat`）：用于对话生成、Cypher 生成与校验
- **UIE（Universal Information Extraction）**：实体抽取模型（基于 ERNIE，PyTorch 实现）

### 数据库
- **Neo4j**：图数据库，存储教育知识图谱（节点、关系、属性）
- **MySQL**：关系数据库，存储原始业务数据和实体映射表（`entity_mapping`）
- **Chroma**：向量数据库，存储实体向量用于相似度检索

### 中间件与工具库
- **LangChain Neo4j**：Neo4j 图数据库集成
- **LangChain HuggingFace**：HuggingFace Embeddings 集成
- **Neo4j Driver**：Neo4j 官方 Python 驱动
- **PyMySQL**：MySQL 连接库

### 机器学习与 NLP
- **PyTorch**（>=1.10, <2.0）：UIE 模型运行环境
- **Transformers**（>=4.18, <5.0）：预训练模型加载
- **Sentence Transformers**：用于实体向量化（BGE-base-zh-v1.5）
- **HuggingFace Embeddings**：文本嵌入模型（BGE-base-zh-v1.5）
- **scikit-learn**：DBSCAN 聚类算法（实体对齐）

### 前端
- **原生 HTML/JavaScript**：简单聊天 UI
- **marked.js**：Markdown 渲染
- **DOMPurify**：XSS 防护

### 其他依赖
- **python-dotenv**：环境变量管理
- **Pydantic**：数据验证与序列化
- **tqdm**：进度条显示
- **numpy**（>=1.22）：数值计算

### 版本要求
- **Python**：建议 3.8+
- **PyTorch**：>=1.10, <2.0（CPU 版本）
- **Transformers**：>=4.18, <5.0
- **protobuf**：==3.19.0（UIE 模型要求）

---

## 核心难点与解决思路

### 1. 实体对齐问题

**难点**：用户输入中的实体名称与知识图谱中的标准实体不一致（如"JAVA"、"java"、"Java"都指向同一门课程）

**解决思路**：
- **离线阶段**：使用 DBSCAN 聚类算法对知识点进行同义词归并，选择高频词作为标准词，建立映射表
- **在线阶段**：
  - **两级检索策略**：先查 MySQL `entity_mapping` 表（快速精确匹配），未命中则使用向量检索（语义相似度匹配）
  - **向量检索兜底**：使用 BGE 嵌入模型计算语义相似度，支持模糊匹配
  - **缓存机制**：命中后回写 MySQL 映射表，提升后续查询效率

### 2. Cypher 查询语句生成与校验

**难点**：
- LLM 生成的 Cypher 可能存在语法错误
- 可能查询不存在的节点标签或属性
- 关系方向可能错误
- 可能包含非法操作（如修改数据库）

**解决思路**：
- **结构化输出校验**：使用 LLM 的 structured output 功能，专门调用一个校验工具检查 Cypher 语句
- **Schema 注入**：将 Neo4j schema 信息注入到系统提示词和校验提示词中，让 LLM 了解可用的节点类型、属性和关系
- **迭代修正**：校验工具返回详细的错误信息和修复建议，Agent 根据反馈循环修正，直到语句合法
- **权限控制**：在系统提示词中明确拒绝修改数据库的操作

### 3. 知识图谱构建的复杂性

**难点**：需要从非结构化的教育文本中抽取结构化知识，并建立复杂的实体关系网络

**解决思路**：
- **领域模型微调**：使用 UIE 模型在教育领域数据上进行微调，提升实体抽取准确率
- **流水线设计**：采用 `DataPipeline` 链式调用模式，将数据读取、清洗、抽取、对齐、索引、写入等步骤解耦，便于维护和扩展
- **批量处理优化**：使用批量写入和事务机制，提升 Neo4j 写入效率
- **索引策略**：在 Neo4j 中创建全文索引和向量索引，支持混合检索（hybrid search）

### 4. 流式响应与用户体验

**难点**：大模型生成速度较慢，需要实时返回部分结果以提升用户体验

**解决思路**：
- **LangChain 流式 API**：使用 `agent.stream()` 方法，按 token 或消息块流式返回
- **FastAPI StreamingResponse**：通过 `StreamingResponse` 将生成器转换为 HTTP 流式响应
- **前端流式渲染**：使用 `ReadableStream` API 实时读取并渲染 Markdown 内容

### 5. 多轮对话上下文管理

**难点**：需要维护用户会话历史，支持上下文相关的问答

**解决思路**：
- **Session 管理**：使用 FastAPI 的 `SessionMiddleware` 通过 Cookie 维护 `session_id`
- **LangGraph Checkpointer**：使用 `InMemorySaver` 作为检查点保存器，按 `thread_id`（即 `session_id`）存储对话历史
- **Agent 记忆注入**：LangChain Agent 自动将历史消息注入到每次对话中

---

## 项目结构

### `src/` 总览（从"用户提问"到"查图数据库再回答"的链路）
- **`backend/`**：对外提供 Web 服务（FastAPI），承接前端请求，把问题交给 `ChatService`，并把回答以**流式**方式返回给浏览器。
- **`agent/`**：大模型 Agent 的“编排层”（系统提示词 + 工具 + 结构化输出），负责把用户问题拆成：实体对齐 → 生成/校验 Cypher → 查询 Neo4j → 总结回答。
- **`configuration/`**：统一的配置与依赖（数据库连接、模型路径、是否流式、是否带记忆等），让各模块共享同一套环境参数。
- **`datasync/`**：离线/准备数据与知识图谱（MySQL→清洗→抽取知识点→对齐→向量库→写入 Neo4j），以及在线用到的“实体对齐”能力。

---

### `src/backend/`（Web 接口层）
- **`app.py`**：FastAPI 入口。
  - 挂载静态资源目录（`/static` 指向 `backend/templates`）
  - `/` 重定向到前端页面 `index.html`
  - `/chat` 接口：读取/生成 `session_id`（用 Cookie Session 标识用户会话），调用 `ChatService.chat(...)` 并用 `StreamingResponse` 流式返回
- **`chat_service.py`**：聊天服务核心“胶水层”。
  - 初始化 embedding（`HuggingFaceEmbeddings`）、Neo4j 连接（`Neo4jGraph`）
  - 调用 `agent.get_agent(...)` 构建 Agent
  - `chat(user_query, session_id)`：按配置决定流式 `agent.stream(...)` 或非流式 `agent.invoke(...)`，并把模型输出逐段 `yield` 给 `backend/app.py`
- **`schemas.py`**：接口入参/出参的数据结构（Pydantic 模型），如 `Question(message)`、`Answer(message)`（目前主要用到 `Question`）
- **`templates/`**：前端静态页面与依赖库
  - **`index.html`**：一个简单聊天 UI，`fetch('/chat')` 发请求并用 `ReadableStream` 读流式返回；用 `marked + DOMPurify` 安全渲染 Markdown
  - **`marked.min.js`**：Markdown 渲染库
  - **`purify.min.js`**：XSS 过滤/HTML 清洗库
- **`__init__.py`**：空文件，用于把目录标记为 Python 包

---

### `src/agent/`（LLM Agent 编排层）
- **`__init__.py`**：提供 `get_agent(neo4j_schema)`，用于创建 Agent：
  - 选择 LLM（这里用 `ChatDeepSeek(deepseek-chat)`）
  - 把 `tools_def.py` 的函数包装成可调用工具（neo4j 查询 / Cypher 校验 / 实体对齐）
  - 按 `config.AGENT_WITH_MEMORY` 决定是否启用记忆（`InMemorySaver`），并把 `neo4j_schema` 注入系统提示词
- **`prompts.py`**：提示词模板
  - `major_agent_system_prompt`：规定 Agent 工作流（拒绝修改库操作、先对齐实体、生成并校验 Cypher、查询、再总结回答）
  - `cypher_checker_prompt`：专门用于检查 Cypher 是否符合语法与 Neo4j schema
- **`schema.py`**：Pydantic 结构化数据定义
  - `CypherCheckerResponse`：Cypher 校验结果（是否合法/错误/修复方法/原语句）
  - `CheckSyntaxError`、`Neo4jQueryParams`、`EntityAlignmentList`：三类工具的入参 schema
- **`tools_def.py`**：Agent 可调用的“工具实现”
  - `entity_alignment(...)`：把用户问题里的实体（课程/学科/章节等）对齐到标准实体（依赖 `datasync.entity_alignment.EntityAlignment`）
  - `check_syntax_error(cypher)`：调用 LLM 按 schema 校验 Cypher（structured output）
  - `neo4j_query(cypher, params)`：真正执行 Neo4j 查询并返回记录

---

### `src/configuration/`（配置与依赖注入）
- **`config.py`**：全局配置常量
  - MySQL/Neo4j 连接信息
  - 路径（项目根、静态目录、embedding 模型路径、向量库目录）
  - 功能开关：`AGENT_WITH_MEMORY`、`AGENT_STREAM_OUTPUT`
- **`dependency.py`**：把“重依赖”做成可复用的单例对象
  - `neo4j_driver`：Neo4j driver
  - `neo4j_schema`：通过 `Neo4jGraph(...).get_schema` 取到的 schema
  - `embedding_model`：embedding 模型实例（供工具/检索使用）
- **`__init__.py`**：空文件（标记为包）

---

### `src/datasync/`（数据准备/同步/对齐/向量化）
- **`data_prepare.py`**：数据管道（离线构建知识图谱的主脚本）
  - `import_data_to_mysql()`：用 `data/edu.sql` 初始化 MySQL（并创建 `entity_mapping` 表）
  - `DataPipeline`：从 MySQL 拉取课程/章节/试卷/用户行为 → 清洗文本 → 用 UIE 模型抽取“知识点” →（可选）实体对齐与向量索引 → 写入 Neo4j（节点、关系、约束）
  - `clear_neo4j()`：清空 Neo4j 数据与约束，并重建唯一性约束
- **`entity_extractor_model_base.py`**：实体抽取模型封装（UIE）
  - `EntityExtractorModelBase`：加载微调后的 UIE checkpoint，按 schema 抽取实体（比如“知识点”）
- **`entity_alignment.py`**：实体对齐 + 向量库（Chroma）索引构建
  - `entity_alignment(self, ...)`：对“知识点”做聚类同义归并，并把 synonym→std_name 写入 MySQL `entity_mapping`
  - `vector_indexing(self, ...)`：把分类/学科/课程/章节/视频/试卷/试题/知识点写入 Chroma 向量库，用于后续检索对齐
  - `EntityAlignment` 类：在线对齐用（先查 MySQL 映射，再向量检索兜底，命中后回写 MySQL）
- **`db_utils.py`**：数据库读写小工具
  - `MySQLReader`：读写 MySQL
  - `Neo4jWriter`：批量写 Neo4j 节点/关系、创建全文索引/向量索引（偏工具脚本用途）
- **`__init__.py`**：空文件（标记为包）

---