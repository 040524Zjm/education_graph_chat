## `datasync` 模块导读指南 🧭

本指南帮助新同学在 10–20 分钟内理清 `datasync` 目录的核心职责与代码流程，便于后续扩展和排查问题。

---

## 模块全景图：这块代码在做什么？🧱

`datasync` 目录主要负责**教育知识图谱与检索相关的数据准备与同步**，核心能力包括：

- **从 MySQL 读取业务数据**（课程、章节、试卷、用户行为等）并清洗规范化；
- 基于 **UIE 实体抽取模型** 抽取“知识点”等教育领域实体；
- 进行 **知识点实体对齐与聚合**（同义词归并成标准词）；
- 将课程结构、知识体系和用户行为 **批量写入 Neo4j 图数据库**；
- 构建 **向量数据库（Chroma）索引** 和 **Neo4j 向量索引 / 全文索引**，支撑后续检索与问答；
- 提供一个统一的 **数据处理流水线 `DataPipeline`**，串起上述步骤。

简单理解：`datasync` 模块就是把“原始教育业务数据”加工成“适合图谱与向量检索使用的结构化知识底座”。💡

---

## 在整体业务中的角色：它处于哪一层？🏗️

从业务视角看，这里处于“**离线 / 增量数据构建层**”，整体链路可以粗略拆成三层：

- **数据源层**：MySQL（`edu_graph_dm` 等库表）、已有的实体映射表 `entity_mapping`、finetune 后的 UIE 模型权重、Chroma 向量存储目录。
- **数据构建层（本模块）**：
  - `data_prepare.py`：数据读写 + 清洗 + Neo4j 写入 + 调用实体抽取 / 实体对齐 / 向量索引，是整个流程的中枢。
  - `entity_extractor_model_base.py`：对 UIE 模型做一层封装，统一实体抽取的调用方式。
  - `entity_alignment.py`：负责“知识点同义词聚类 + 标准词映射”以及“教育实体的向量检索与补充映射”。
  - `db_utils.py`：对 MySQL / Neo4j 的通用读写和索引操作做工具化封装。
- **上层应用层**：图数据库问答、推荐与检索服务（通过 Neo4j / 向量库 / MySQL 查询，上层 Agent 或 API 不直接接触原始数据表）。

因此，如果你在做“新字段同步到图谱”“增加新的实体类型”“调整实体对齐策略”等工作，基本都会落在 `datasync` 模块中完成。🔧

---

## 代码入口点：从哪里开始看？👀

**推荐阅读顺序：**

1. `data_prepare.py`：从 `if __name__ == "__main__":` 开始整体感知流水线；
2. 继续往上看 `DataPipeline` 类中的几个方法，理解每个阶段如何操作 `self.dataset`；
3. 切到 `entity_extractor_model_base.py`，理解实体抽取接口；
4. 再看 `entity_alignment.py` 的 `entity_alignment`、`vector_indexing` 和 `EntityAlignment` 类；
5. 最后如有需要，再看 `db_utils.py`，了解 Neo4j 写入 / 向量索引的通用做法。

下面是主流程入口的实际代码片段，配合注释一起看更直观：

```650:679:src/datasync/data_prepare.py
if __name__ == "__main__":
    # 导入数据到 MySQL
    import_data_to_mysql()
    # 清空 Neo4j
    clear_neo4j()

    # 加载实体抽取模型
    eemodel = EntityExtractorModelBase(
        config.ROOT_DIR / 'finetuned' / 'checkpoint' / 'model_best', config.DEVICE["device"], 16
    )

    # 课程资料与知识体系数据处理
    course_data_pipeline = DataPipeline()
    course_data_pipeline = (
        course_data_pipeline.query_course_data_from_mysql()  # 从 MySQL 获取课程资料数据
    )
    course_data_pipeline.data_cleaning()  # 数据清洗，保存部分数据用于标注和微调实体抽取模型
    course_data_pipeline = course_data_pipeline.entity_extract(
        eemodel, schema=["知识点"]
    )  # 抽取知识点实体

    DataPipeline.entity_alignment = entity_alignment
    DataPipeline.vector_indexing = vector_indexing
    course_data_pipeline = course_data_pipeline.entity_alignment().vector_indexing()

    course_data_pipeline.import_course_data_to_neo4j()  # 导入数据到 Neo4j

    # 用户行为数据处理
    user_log_pipeline = DataPipeline()
    user_log_pipeline.query_user_log_from_mysql().import_user_log_to_neo4j()
```

可以把这段理解为一条“流水线配置脚本”：前半段是环境初始化，后半段是基于 `DataPipeline` 的链式调用，把课程与用户行为数据依次推送到 Neo4j 和向量库中。

**最核心入口：**

- **文件入口**：`src/datasync/data_prepare.py`
- **主流程入口函数**：`if __name__ == "__main__":` 下面的脚本段落
  - 主要步骤：
    - `import_data_to_mysql()`
    - `clear_neo4j()`
    - 初始化 `EntityExtractorModelBase`
    - `course_data_pipeline = DataPipeline()`
    - 一系列链式调用：
      - `query_course_data_from_mysql()`
      - `data_cleaning()`
      - `entity_extract(...)`
      - `entity_alignment()`
      - `vector_indexing()`
      - `import_course_data_to_neo4j()`
    - 针对用户行为的：`user_log_pipeline.query_user_log_from_mysql().import_user_log_to_neo4j()`

---

## 关键流程分析：以“课程与知识点处理”为例 🔄

下面以**课程资料 + 知识点构建**这个主流程说明代码如何在各模块间流转。

### 1. 初始化与准备（`data_prepare.py`）

- 清空 / 准备数据库：
  - `import_data_to_mysql()`：初始化 MySQL 数据库，建表 `entity_mapping`，并通过执行 `edu.sql` 将样例数据导入。
  - `clear_neo4j()`：清空 Neo4j 中的约束与节点数据，并重建必要的唯一约束。
- 加载实体抽取模型：
  - `EntityExtractorModelBase` 从 `finetuned/checkpoint/model_best` 中加载 UIE finetune 模型。

### 2. 数据读取与清洗（`DataPipeline` in `data_prepare.py`）

- `query_course_data_from_mysql()`：
  - 通过 `pymysql` 连接 MySQL，读取：
    - 课程基本信息（`course_info` + `base_subject_info` + `base_category_info`）；
    - 课程-章节-视频结构；
    - 课程-试卷-试题结构；
  - 将结果分别放入 `self.dataset["course"]`、`self.dataset["course_chapter_video"]`、`self.dataset["course_paper_question"]`。

对应代码片段如下，可以直观看到如何操作 `self.dataset`：

```86:116:src/datasync/data_prepare.py
class DataPipeline:
    def __init__(self):
        self.dataset: dict[str, any] = {}

    # --------- 从 MySQL 获取数据 ---------

    def query_course_data_from_mysql(self) -> "DataPipeline":
        """查询课程资料相关信息"""
        # 连接 MySQL
        with pymysql.connect(**config.MYSQL_CONFIG) as mysql_conn:
            # 创建 MySQL 游标
            with mysql_conn.cursor(pymysql.cursors.DictCursor) as cursor:
                # 教师<-课程->学科->分类
                cursor.execute(
                    "select "
                    "course_info.id as course_id, "  # 课程ID
                    "course_info.course_name, "  # 课程名称
                    "course_info.course_introduce, "  # 课程介绍
                    ...
                )
                self.dataset["course"] = cursor.fetchall()
                ...
        return self
```

- `data_cleaning()`：
  - 使用 `_standardize_text()` 对课程名、介绍、章节名、视频名、试卷名、试题名做统一清洗：
    - 去 HTML 标签 + 反转义；
    - 全角转半角；
    - 合并多余空白并去首尾空格；
    - 统一小写。
  - 同时保留 `raw_*` 字段，便于后续展示与追溯。

其中文本规范化的实现如下：

```215:242:src/datasync/data_prepare.py
    def _standardize_text(self, text: str) -> str:
        """清洗一条文本"""
        if not (text and isinstance(text, str)):
            return text

        # 移除 HTML 标签
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)

        # 全角转半角
        res = ""
        for uchar in text:
            u_code = ord(uchar)
            # 全角空格
            if u_code == 12288:
                res += chr(32)
            # 其他全角字符 (除空格外)
            elif 65281 <= u_code <= 65374:
                res += chr(u_code - 65248)
            else:
                res += uchar

        # 去除首尾空格，并将内部多个空格合并为一个
        res = re.sub(r"\s+", " ", res).strip()

        # 统一转换为小写
        res = res.lower()
        return res
```

### 3. 模型抽取知识点（`EntityExtractorModelBase` + `DataPipeline.entity_extract`）

- `EntityExtractorModelBase.__call__`：
  - 接收一个或多个文本 + `schema`（如 `["知识点"]`）；
  - 调用 UIE 模型，返回 `{实体类型: [去重后的实体文本列表]}`。

核心实现如下：

```9:32:src/datasync/entity_extractor_model_base.py
class EntityExtractorModelBase:
    """实体抽取-基于模型:使用 UIE 抽取实体"""

    def __init__(self, model_params_path, device="cpu", batch_size=8):
        # 初始化 UIE
        self.uie = UIEPredictor(
            model="uie-base",
            task_path=model_params_path,
            schema=[],
            engine="pytorch",
            device=device,
            batch_size=batch_size,
        )

    def __call__(self, text, schema):
        self.uie.set_schema(schema)
        res: list[dict] = []
        # 统一转换为列表
        input_texts = text if isinstance(text, list) else [text]
        res = self.uie(input_texts)
        for one_res in res:
            for k, values in one_res.items():
                one_res[k] = list({v["text"] for v in values})
        return res if isinstance(text, list) else res[0]
```

- `DataPipeline.entity_extract(eemodel, schema)`：
  - 对课程介绍、章节名称中的文本分别抽取知识点：
    - 结果存入 `self.dataset["course_concept"]`、`self.dataset["chapter_concept"]`；
  - 为每条数据保存 `course_id` / `chapter_id` 与抽取到的 `concept`。

在流水线中的实际调用方式是：

```281:301:src/datasync/data_prepare.py
    def entity_extract(self, eemodel, schema) -> "DataPipeline":
        """抽取知识点"""

        # 抽取课程介绍中的知识点
        print("抽取课程介绍中的知识点")
        count = 0
        course_datas = [
            (course["course_id"], course["course_introduce"])
            for course in self.dataset.get("course", [])
            if course.get("course_introduce")
        ]
        course_id_list, course_introduce_list = zip(*course_datas)
        ee_dict_list = eemodel(list(course_introduce_list), schema)
        for course_id, ee_dict in zip(course_id_list, ee_dict_list):
            concept_list = ee_dict.get(schema[0], [])
            if not concept_list:
                continue
            concept_list = list(set(concept_list))
            self.dataset.setdefault("course_concept", []).extend(
                [{"course_id": course_id, "concept": c} for c in concept_list]
            )
            count += len(concept_list)
```

### 4. 实体对齐（`entity_alignment.entity_alignment`）

- 在 `__main__` 中通过：
  - `DataPipeline.entity_alignment = entity_alignment`
  - `DataPipeline.vector_indexing = vector_indexing`
  - 将两个函数“挂”到 `DataPipeline` 类上，然后链式调用：
    - `course_data_pipeline = course_data_pipeline.entity_alignment().vector_indexing()`
- `entity_alignment(self, ...)` 内部逻辑：
  - 从 MySQL 读取历史 `entity_mapping` 表，构造 `old_concept_clusters`（旧同义词 → 标准词）。
  - 遍历 `course_concept` / `chapter_concept` / `question_concept`，统计每个知识点的新出现频率。
  - 计算“新知识点”集合（与旧概念补集），通过 **SentenceTransformer 向量化 + DBSCAN 聚类**：
    - 初始化场景：按频次选择每个簇的“标准词”，将簇内所有词映射到该标准词；
    - 增量场景：先选择临时标准词，再与旧标准词计算相似度（`cosine_similarity`），高于阈值则并入旧标准词，否则新建标准词。
  - 将新的映射写回 `entity_mapping` 表，然后统一替换 `self.dataset` 中所有 concept 为标准词。

下面两段代码分别展示了“收集新增知识点并聚类”和“与旧标准词对齐”的关键实现：

```68:81:src/datasync/entity_alignment.py
    # 收集所有新增知识点，并统计出现频率
    new_concept_with_frequency = dict()
    for concept_dict_name in ["course_concept", "chapter_concept", "question_concept"]:
        for i in self.dataset.get(concept_dict_name, []):
            frequency = new_concept_with_frequency.get(i["concept"], 0) + 1  # 频率+1
            new_concept_with_frequency[i["concept"]] = frequency  # 更新频率

    # 取补集，筛选出新出现的知识点
    new_concepts = list(set(new_concept_with_frequency) - set(old_concepts))

    # 如果有新增知识点
    new_concept_clusters = {}
    if new_concepts:
        print( f"检测到 {len(new_concepts)} 个新增知识点")
        # 初始化与增量更新通用流程：将新知识点聚类并根据频次选择标准词
        # 获取新知识点的向量
        new_embeddings = embedding_model.encode(
            new_concepts, batch_size=embed_batch_size, normalize_embeddings=True
        )
        # 使用 DBSCAN 算法聚类，相似的视为同一标准知识点
        algorithm = DBSCAN(eps=0.15, min_samples=1, metric="cosine")
        cluster_ids = algorithm.fit_predict(new_embeddings)
```

```115:142:src/datasync/entity_alignment.py
            # 获取所有临时标准词的向量
            temp_std_list = list(temp_std_to_cluster.keys())
            temp_embeddings = embedding_model.encode(
                temp_std_list, batch_size=embed_batch_size, normalize_embeddings=True
            )
            # 获取旧标准词的向量
            old_embeddings = embedding_model.encode(
                old_std_concepts, batch_size=embed_batch_size, normalize_embeddings=True
            )

            # 计算临时标准词与旧标准词的相似度
            similarity_matrix = cosine_similarity(temp_embeddings, old_embeddings)

            # 合并实体
            new_concept_clusters = dict()
            threshold = 0.85
            for i, temp_std in enumerate(temp_std_list):
                most_similar_idx = similarity_matrix[i].argmax()
                max_sim = similarity_matrix[i][most_similar_idx]
                # 如果临时标准词匹配到旧的标准词，使用旧标准词
                if max_sim >= threshold:
                    matched_old_std = old_std_concepts[most_similar_idx]
                    for c in temp_std_to_cluster[temp_std]:
                        new_concept_clusters[c] = matched_old_std
                # 如果临时标准词没有找到匹配，使用临时标准词作为新的标准词
                else:
                    for c in temp_std_to_cluster[temp_std]:
                        new_concept_clusters[c] = temp_std
```

### 5. 向量索引构建（`entity_alignment.vector_indexing`）

- `vector_indexing(self, ...)`：
  - 利用 `assemble_vector_items()` 为不同实体（分类 / 学科 / 课程 / 章节 / 视频 / 试卷 / 试题 / 知识点）拼装：
    - `id`（如 `"course_123"`）；
    - `metadata`（包含 `type` 和原始文本）；
    - `document`（适合向量化的组合文本：名称 + 描述等）。
  - 使用 `chromadb.PersistentClient` 获取 / 创建 `edu_graph_dm` collection：
    - 删除重复 ID；
    - 用 SentenceTransformer 批量生成 embedding；
    - 分批写入向量库。

构造向量条目的辅助函数：

```175:199:src/datasync/entity_alignment.py
def assemble_vector_items(datas: list, id_key, metadata, doc_template):
    """
    组装向量索引内容
    {
        'id': 类别+id,
        'metadata': {
            'type': 类别,
            'text': 内容,
        },
        'document': 名称+辅助信息
    }
    """
    seen = set()
    vector_items = [
        {
            "id": f"{metadata['type']}_{i[id_key]}",
            "metadata": {**metadata, "text": i[doc_template[0][1]]},
            "document": " ".join(
                [f"{name}:{i.get(value, '')}" for name, value in doc_template]
            ),
        }
        for i in datas
        if i.get(id_key) and not (i[id_key] in seen or seen.add(i[id_key]))  # 去重
    ]
    return vector_items
```

真正与 Chroma 交互的部分：

```317:355:src/datasync/entity_alignment.py
    # 创建或加载向量数据库
    client = chromadb.PersistentClient(path=config.VECTOR_STORE_DIR)
    collection = client.get_or_create_collection("edu_graph_dm")

    # 删数据库中与新增数据 ID 重复的数据，以及过滤新增数据中重复数据
    seen = set()
    old_ids = collection.get()["ids"]
    new_ids = set(ids) - set(old_ids)
    new_items = [
        (i["id"], i["metadata"], i["document"])
        for i in all_vector_items
        if i["id"] in new_ids and not (i["id"] in seen or seen.add(i["id"]))
    ]

    ...

    # 批量嵌入
    embedding_model = get_embedding_model()
    embeddings = embedding_model.encode(
        documents,
        batch_size=embed_batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    # 批量添加
    for i in tqdm(range(0, len(ids), add_batch_size), desc="writing into chroma"):
        collection.add(
            ids=ids[i : i + add_batch_size],
            documents=documents[i : i + add_batch_size],
            metadatas=metadatas[i : i + add_batch_size],
            embeddings=embeddings[i : i + add_batch_size],
        )
```

### 6. 写入 Neo4j（`DataPipeline.import_course_data_to_neo4j` & `import_user_log_to_neo4j`）

- `import_course_data_to_neo4j()`：
  - 使用 `_batch_insert()` 封装的 `UNWIND $batch` 批量写入；
  - 写入并关联：
    - 课程 / 学科 / 分类 / 教师 / 价格；
    - 章节 / 视频；
    - 试卷 / 试题；
    - 课程 / 章节 / 试题对应的知识点；
  - 额外构建：
    - 知识点间的 **先修关系 `[:NEED]`**；
    - 包含关系 `[:BELONG]`；
    - 相关关系 `[:RELATED]`。
- `import_user_log_to_neo4j()`：
  - 对 `user_info`、`user_favor`、`user_answer`、`user_chapter_progress` 四类数据，批量写入：
    - `(:User)` 节点；
    - `[:FAVOR]`（收藏）、`[:ANSWER]`（答题）、`[:WATCH]`（学习进度）关系。

至此，一次完整的“课程资料 + 知识点 + 用户行为”构建流程完成。🚀

---

## 重要类 / 函数索引与职责 📚

### 1. `data_prepare.py`

- **`import_data_to_mysql()`**
  - 功能：初始化 MySQL 数据库，创建 `entity_mapping` 表并导入 `edu.sql` 中的数据。
  - 适用场景：本地 / 全量环境初始化。

- **`DataPipeline` 类**
  - **字段**
    - `dataset: dict[str, any]`：全流程共享的数据缓存容器。
  - **方法**
    - `query_course_data_from_mysql()`：
      - 读取课程、章节、视频、试卷、试题结构数据，填充到 `dataset`。
    - `query_user_log_from_mysql()`：
      - 读取用户基础信息、收藏、答题记录、章节进度，填充到 `dataset`。
    - `data_cleaning()`：
      - 文本清洗（HTML 去除、全角转半角、小写化），并保留原始字段。
    - `entity_extract(eemodel, schema)`：
      - 调用外部实体抽取模型，在课程介绍与章节名称中抽取知识点。
    - `_batch_insert(driver, query, params, ...)`：
      - 基于 Neo4j `UNWIND` 的通用批量写入工具方法。
    - `import_course_data_to_neo4j()`：
      - 将课程结构、知识点、以及知识点间关系批量写入 Neo4j。
    - `import_user_log_to_neo4j()`：
      - 将用户相关行为数据写入 Neo4j。
    - （运行时挂载）`entity_alignment(self, ...)` / `vector_indexing(self, ...)`：
      - 分别来自 `entity_alignment.py` 中的同名函数，在主流程中以链式调用的方式参与。

- **`clear_neo4j()`**
  - 功能：清空 Neo4j 中所有节点与约束，然后重建一批唯一性约束。
  - 注意：这一步是**破坏性操作**，只适用于离线构建或开发环境。

- **`__main__` 脚本段**
  - 一站式串联以上所有步骤，是本模块最重要的参考入口。

### 2. `entity_extractor_model_base.py`

- **`EntityExtractorModelBase` 类**
  - 作用：封装 UIE 实体抽取模型，提供统一的 `__call__` 接口。
  - 关键点：
    - 初始化时通过 `UIEPredictor` 加载 `finetuned/checkpoint/model_best` 模型；
    - `__call__(text, schema)`：
      - 支持单条或多条文本；
      - 输出为 `{实体类型: [去重后的实体文本]}` 的结构，便于后续流水线直接消费。

### 3. `entity_alignment.py`

- **`get_embedding_model()`**
  - 功能：懒加载 `SentenceTransformer` 模型并做全局缓存，避免重复加载。

- **`entity_alignment(self, embed_batch_size=128)`**
  - 挂载到 `DataPipeline` 之后，成为数据流水线的一环；
  - 完成长 / 增量知识点实体对齐，并更新 `self.dataset` 中的 concept 值。

- **`assemble_vector_items(datas, id_key, metadata, doc_template)`**
  - 将原始表中某类实体转换为“适合写入向量库”的统一结构。

- **`vector_indexing(self, embed_batch_size=128, add_batch_size=256)`**
  - 同样挂载到 `DataPipeline`；
  - 使用 SentenceTransformer + Chroma 构建多类型实体的向量索引。

- **`EntityAlignment` 类**
  - 用于**在线/交互式的实体标准化**：
    - `entity_mapping(text, entity_schema)`：
      - 直接从 `entity_mapping` 表查找是否已有标准词映射。
    - `vector_retrieve(text, where=None, n_results=1, threshold=1.0)`：
      - 利用向量检索从 Chroma 中找最相似的实体。
    - `__call__(text, entity_schema)`：
      - 组合上述两步：先查表，查不到则走向量检索，并将新映射写回 MySQL。
  - 典型用途：运行时对用户输入的实体文本进行规范化映射。

完整代码如下，便于在在线服务中直接对接：

```360:413:src/datasync/entity_alignment.py
class EntityAlignment:
    """实体对齐"""

    def __init__(self):
        self.embedding_model = get_embedding_model()
        self.chroma_client = chromadb.PersistentClient(path=config.VECTOR_STORE_DIR)

    def entity_mapping(self, text, entity_schema):
        """标准词映射"""
        with pymysql.connect(**config.MYSQL_CONFIG) as mysql_conn:
            with mysql_conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    "select std_name from entity_mapping where is_reviewed=1 and entity_schema=%s and synonym=%s",
                    (entity_schema, text),
                )
                res = cursor.fetchone()
                if res:
                    res = res["std_name"]
        return res

    def vector_retrieve(self, text, where=None, n_results=1, threshold=1.0):
        """向量检索"""
        embedding = self.embedding_model.encode(text, normalize_embeddings=True)
        collection = self.chroma_client.get_or_create_collection("edu_graph_dm")
        res = collection.query(embedding, n_results=n_results, where=where)
        # 按阈值过滤，返回 metadata
        res = [
            res["metadatas"][0][i]
            for i in range(len(res["ids"][0]))
            if res["distances"][0][i] < threshold
        ]
        res = res[0]["text"] if res else None
        return res

    def __call__(self, text, entity_schema):
        # 先从同义词-标准词中匹配
        res = self.entity_mapping(text, entity_schema)
        # 如果没有匹配成功，嵌入并检索
        if not res:
            res = self.vector_retrieve(text, where={"type": entity_schema})
            if res:
                # 将文本和检索出来的标准词写入 MySQL
                with pymysql.connect(**config.MYSQL_CONFIG) as mysql_conn:
                    with mysql_conn.cursor(pymysql.cursors.DictCursor) as cursor:
                        cursor.execute(
                            "insert  into edu_graph_dm.entity_mapping (synonym, std_name, entity_schema, is_reviewed) value(%s, %s, %s, 1)",
                            (text, res, entity_schema),
                        )
                    mysql_conn.commit()
        return res
```

### 4. `db_utils.py`

- **`MySQLReader`**
  - 封装 MySQL 的连接、`read_data`、`write_data` 三个基本操作；
  - 适合在其他脚本中做小批量数据互动或快速查询。

- **`Neo4jWriter`**
  - `write_nodes(label, batch_data, batch_size=20)`：
    - 根据传入的 `batch_data` 动态生成 `MERGE` 语句，批量写入某类标签的节点。
  - `write_relationship(start_node_label, end_node_label, relationships, batch_size=20)`：
    - 通过节点 `id` 建立关系，使用 `UNWIND` + `MERGE` 批量写入。
  - `write_full_text_index(label, label_property, index_name)`：
    - 创建 Neo4j 全文索引（cjk 分词器），支撑中文搜索。
  - `write_vector_index(label, label_property, embedding_property, batch_size=20)`：
    - 对 Neo4j 中已有节点文本进行向量化，并在 Neo4j 中创建向量索引。

以 `Neo4jWriter.write_nodes` 为例，它展示了如何将任意 dict 列表批量写入某类节点：

```30:54:src/datasync/db_utils.py
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
```

---

## 给新同学的一点建议 ✍️

- **先跑起来再深挖**：建议先在本地跑一遍 `data_prepare.py`，观察 MySQL / Neo4j / Chroma 中数据的变化，对整体有直观感受。
- **从数据结构入手**：弄清楚 `self.dataset` 中每个 key 的含义和来源，再看写 Neo4j / 向量库会轻松很多。
- **改造前先画图**：在调整知识点对齐或图结构关系前，先在纸上画一张“节点-关系”草图，会极大降低踩坑概率。🙂

