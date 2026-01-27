python finetune.py --train_path "/Users/zjm/PycharmProjects/LLM_2026_demo/education_graph_chat/data/processed/course/train.txt"  --dev_path "/Users/zjm/PycharmProjects/LLM_2026_demo/education_graph_chat/data/processed/course/dev.txt"  --save_dir "/Users/zjm/PycharmProjects/LLM_2026_demo/education_graph_chat/finetuned/checkpoint"     --learning_rate 1e-5 --batch_size 16 --max_seq_len 512  --num_epochs 100  --model "/Users/zjm/LLM_path/pretrained/uie_pytorch/uie_base_pytorch" --logging_steps 10 --valid_steps 100 --device "cpu"

todo: Pip install transformers==4.54.0 colorlog

从4.57.6改成了4.54.0 才成功



### `src/` 总览（从“用户提问”到“查图数据库再回答”的链路）
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