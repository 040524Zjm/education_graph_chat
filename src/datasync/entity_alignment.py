from configuration import config
import pymysql
import chromadb
from tqdm import tqdm
from sklearn.cluster import DBSCAN
from collections import defaultdict
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


_embedding_model = None


def get_embedding_model():
    """获取嵌入模型"""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(
            str(config.EMBEDDING_MODEL_PATH)
        )
        print("加载嵌入模型")
    else:
        print("复用已加载的嵌入模型")
    return _embedding_model


def entity_alignment(self, embed_batch_size=128):
    """
    知识点实体对齐
    如果是初始化：
        知识点向量化
        聚类
        选取高频词作为标准词
        所有同义词映射为标准词
    如果是增量更新：
        新知识点向量化
        聚类
        选出新知识点中的高频词作为临时标准词
        计算临时标准词和旧标准词的相似度
        如果临时标准词和旧标准词相似，使用旧标准词
        如果临时标准词没有相似项，将其作为新标准词
        所有同义词映射为标准词
    """
    embedding_model = get_embedding_model()

    # 加载同义词到标准词的映射，计算标准词的向量表示
    # 如果不存在 MySQL 表则创建
    with pymysql.connect(**config.MYSQL_CONFIG) as mysql_conn:
        with mysql_conn.cursor(pymysql.cursors.DictCursor) as cursor:
            # collate utf8mb4_bin 设置字段大小写敏感

            cursor.execute(
                "select synonym, std_name from entity_mapping where entity_schema='concept'"
            )
            old_concept_clusters = cursor.fetchall()
    old_concepts = []
    if old_concept_clusters:
        print( f"读取 {len(old_concept_clusters)} 条已对齐的知识点")
        # 同义词到标准词的映射
        old_concept_clusters = {
            x["synonym"]: x["std_name"] for x in old_concept_clusters
        }
        # 旧的知识点列表
        old_concepts = list(set(old_concept_clusters.keys()))
        # 旧的标准词列表
        old_std_concepts = list(set(old_concept_clusters.values()))

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
        # 将知识点按簇编号分类
        cluster_dict = defaultdict(list)  # cluster_id -> concept_list
        for concept, cluster_id in zip(new_concepts, cluster_ids):
            if cluster_id >= 0:
                cluster_dict[cluster_id].append(concept)

        # 如果是初始化阶段，聚类，并选择高频词作为标准词
        if not old_concepts:
            # 选择每个簇中频率最高的概念作为标准词
            new_concept_clusters = dict()
            for cluster_id, concept_list in cluster_dict.items():
                std_concept = max(
                    concept_list, key=lambda c: new_concept_with_frequency[c]
                )
                for c in concept_list:
                    new_concept_clusters[c] = std_concept
        else:
            # 每个簇选择频率最高的词作为临时标准词
            temp_std_to_cluster = dict()  # 临时标准词 → 所有同义词
            for cluster_id, concept_list in cluster_dict.items():
                std_concept = max(
                    concept_list, key=lambda c: new_concept_with_frequency[c]
                )
                temp_std_to_cluster[std_concept] = concept_list

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

        # 存储到 MySQL
        with pymysql.connect(**config.MYSQL_CONFIG) as mysql_conn:
            with mysql_conn.cursor(pymysql.cursors.DictCursor) as cursor:
                for concept in new_concept_clusters:
                    cursor.execute(
                        "insert  into edu_graph_dm.entity_mapping (synonym, std_name, entity_schema) value(%s, %s, %s)",
                        (concept, new_concept_clusters[concept], "concept"),
                    )
                mysql_conn.commit()
                print(f"新增 {len(new_concept_clusters)} 条知识点到数据库")

    # 融合新旧标准词映射
    concept_clusters = new_concept_clusters
    if old_concept_clusters:
        concept_clusters.update(old_concept_clusters)

    # 替换原始数据
    def replace_concepts(concept_list):
        for i in concept_list:
            std_concept = concept_clusters.get(i["concept"], i["concept"])
            i["concept"] = std_concept

    replace_concepts(self.dataset.get("course_concept", []))
    replace_concepts(self.dataset.get("chapter_concept", []))
    replace_concepts(self.dataset.get("question_concept", []))
    return self





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


def vector_indexing(self, embed_batch_size=128, add_batch_size=256):
    """创建向量索引"""

    # 分类
    category_vector_items = assemble_vector_items(
        datas=self.dataset.get("course", []),
        id_key="category_id",
        metadata={"type": "category"},
        doc_template=[("分类名称", "category_name")],
    )
    # 学科
    subject_vector_items = assemble_vector_items(
        datas=self.dataset.get("course", []),
        id_key="subject_id",
        metadata={"type": "subject"},
        doc_template=[("学科名称", "subject_name")],
    )
    # 课程
    course_vector_items = assemble_vector_items(
        datas=self.dataset.get("course", []),
        id_key="course_id",
        metadata={"type": "course"},
        doc_template=[
            ("课程名称", "course_name"),
            ("课程描述", "course_introduce"),
            ("所属学科", "subject_name"),
        ],
    )
    # 章节
    chapter_vector_items = assemble_vector_items(
        datas=self.dataset.get("course_chapter_video", []),
        id_key="chapter_id",
        metadata={"type": "chapter"},
        doc_template=[
            ("章节名称", "chapter_name"),
            ("所属课程", "course_name"),
        ],
    )
    # 视频
    video_vector_items = assemble_vector_items(
        datas=self.dataset.get("course_chapter_video", []),
        id_key="video_id",
        metadata={"type": "video"},
        doc_template=[
            ("视频名称", "video_name"),
            ("所属章节", "chapter_name"),
            ("所属课程", "course_name"),
        ],
    )
    # 试卷
    paper_vector_items = assemble_vector_items(
        datas=self.dataset.get("course_paper_question", []),
        id_key="paper_id",
        metadata={"type": "paper"},
        doc_template=[
            ("试卷名称", "paper_name"),
            ("所属课程", "course_name"),
        ],
    )
    # 试题
    question_vector_items = assemble_vector_items(
        datas=self.dataset.get("course_paper_question", []),
        id_key="question_id",
        metadata={"type": "question"},
        doc_template=[
            ("试题名称", "question_name"),
            ("所属试卷", "paper_name"),
            ("所属课程", "course_name"),
        ],
    )

    # 课程知识点
    course_concept_vector_items = assemble_vector_items(
        datas=self.dataset.get("course_concept", []),
        id_key="concept",
        metadata={"type": "concept"},
        doc_template=[
            ("知识点名称", "concept"),
        ],
    )
    # 章节知识点
    chapter_concept_vector_items = assemble_vector_items(
        datas=self.dataset.get("chapter_concept", []),
        id_key="concept",
        metadata={"type": "concept"},
        doc_template=[
            ("知识点名称", "concept"),
        ],
    )
    # 试题知识点
    question_concept_vector_items = assemble_vector_items(
        datas=self.dataset.get("question_concept", []),
        id_key="concept",
        metadata={"type": "concept"},
        doc_template=[
            ("知识点名称", "concept"),
        ],
    )

    # 合并结果
    all_vector_items = (
        category_vector_items
        + subject_vector_items
        + course_vector_items
        + chapter_vector_items
        + video_vector_items
        + paper_vector_items
        + question_vector_items
        + course_concept_vector_items
        + chapter_concept_vector_items
        + question_concept_vector_items
    )
    ids = [x["id"] for x in all_vector_items]

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

    duplicate_data_num = len(ids) - len(new_items)
    if duplicate_data_num:
        print(f"{duplicate_data_num} 条数据已存在于向量数据库中")
    if not new_items:
        return

    ids, metadatas, documents = zip(*new_items)
    ids = list(ids)
    documents = list(documents)
    metadatas = list(metadatas)
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
    print(f"添加 {len(ids)} 条数据到向量数据库")
    return self


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
                        # cursor.execute(
                        #     "select std_name from edu_graph_dm.entity_mapping where is_reviewed=1 and entity_schema=%s and synonym=%s",
                        #     (entity_schema, text),
                        # )
                        cursor.execute(
                            "insert  into edu_graph_dm.entity_mapping (synonym, std_name, entity_schema, is_reviewed) value(%s, %s, %s, 1)",
                            (text, res, entity_schema),
                        )
                    mysql_conn.commit()
        return res


if __name__ == "__main__":
    ea = EntityAlignment()
    print(type(ea("JAVA基础", "subject")))
