import re
import json
import html

import pymysql
import subprocess
from tqdm import tqdm
from neo4j import GraphDatabase, Driver

from configuration import config
from entity_alignment import entity_alignment, vector_indexing
from entity_extractor_model_base import EntityExtractorModelBase

tag = {
    "error": "\033[1;31m[ERROR]\033[0m",
    "success": "\033[1;32m[SUCCESS]\033[0m",
    "processing": "\033[1;34m[PROCESSING]\033[0m",
}


# --------- MySQL 数据准备 ---------


def import_data_to_mysql() -> None:
    """导入数据到 MySQL"""

    # MySQL 命令前缀，包括 host、user、password
    mysql_cmd_prefix = [
        "mysql",
        "-h",
        "localhost",
        "-u",
        config.MYSQL_CONFIG["user"],
        f"-p{config.MYSQL_CONFIG['password']}",
        # f"--default-character-set={config.MYSQL_CONFIG['charset']}",
    ]

    # 创建数据库
    print(f"创建 {config.MYSQL_CONFIG['database']}")
    cmd = mysql_cmd_prefix + [
        "-e",
        f"DROP DATABASE IF EXISTS {config.MYSQL_CONFIG['database']}; CREATE DATABASE {config.MYSQL_CONFIG['database']};",
    ]

    result = subprocess.run(cmd, stderr=subprocess.PIPE, text=True) # subprocess可以捕获错误信息
    if result.returncode != 0:
        print(f"{result.stderr.splitlines()[1:][0]}")
        return
    print(f"{config.MYSQL_CONFIG['database']} 创建成功")

    # 创建entity_mapping表
    cmd = mysql_cmd_prefix + [
        "-e",
        f"""
        create table if not exists
                    {config.MYSQL_CONFIG['database']}.entity_mapping (
                        synonym varchar(255) not null collate utf8mb4_bin comment '同义词', /*同义词,区分大小写*/
                        std_name varchar(255) not null comment '标准词',
                        entity_schema varchar(255) not null comment '实体类型',
                        is_reviewed int default 0 not null comment '是否已审核',
                        create_time timestamp default current_timestamp comment '创建时间',
                        update_time timestamp default null on update current_timestamp comment '更新时间',
                        primary key (synonym, std_name)
                    ) comment '实体映射表';

""",
    ]

    result = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)

    # 导入数据
    print(f"导入数据")
    with open(config.ROOT_DIR / "data" / "edu.sql", "r") as sql_file:
        result = subprocess.run(
            mysql_cmd_prefix + [config.MYSQL_CONFIG["database"]],
            stdin=sql_file,
            stderr=subprocess.PIPE,
            text=True,
        )
    if result.returncode != 0:
        print(f"{result.stderr.splitlines()[1:][0]}")
        return
    print(f"数据导入成功")


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
                    "course_info.course_cover_url, "  # 课程详情图片
                    "course_info.actual_price as price, "  # 课程价格
                    "course_info.teacher as teacher_name, "  # 教师名称
                    "base_subject_info.id as subject_id, "  # 学科ID
                    "base_subject_info.subject_name, "  # 学科名称
                    "base_category_info.id as category_id, "  # 分类ID
                    "base_category_info.category_name "  # 分类名称
                    "from edu_graph_dm.course_info "
                    "left join edu_graph_dm.base_subject_info on course_info.subject_id = base_subject_info.id "
                    "left join edu_graph_dm.base_category_info on base_subject_info.category_id = base_category_info.id; "
                )
                self.dataset["course"] = cursor.fetchall()

                # 课程id<-章节<-视频
                cursor.execute(
                    "select "
                    "chapter_info.course_id, "  # 课程ID
                    "course_info.course_name, "  # 课程名称
                    "chapter_info.id as chapter_id, "  # 章节ID
                    "chapter_info.chapter_name, "  # 章节名称
                    "video_info.id as video_id, "  # 视频ID
                    "video_info.video_name "  # 视频名称
                    "from edu_graph_dm.chapter_info "
                    "left join edu_graph_dm.course_info on chapter_info.course_id = course_info.id "
                    "left join edu_graph_dm.video_info on chapter_info.id = video_info.chapter_id; "
                )
                self.dataset["course_chapter_video"] = cursor.fetchall()

                # 课程id<-试卷<-试题
                cursor.execute(
                    "select "
                    "test_paper.course_id, "  # 课程ID
                    "course_info.course_name, "  # 课程名称
                    "test_paper.id as paper_id, "  # 试卷ID
                    "test_paper.paper_title as paper_name, "  # 试卷名称
                    "test_question_info.id as question_id, "  # 试题ID
                    "test_question_info.question_txt as question_name "  # 试题名称
                    "from edu_graph_dm.test_paper "
                    "left join edu_graph_dm.course_info on test_paper.course_id = course_info.id "
                    "left join edu_graph_dm.test_paper_question on test_paper.id = test_paper_question.paper_id "
                    "left join edu_graph_dm.test_question_info on test_paper_question.question_id = test_question_info.id; "
                )
                self.dataset["course_paper_question"] = cursor.fetchall()

                # # 查询试题对应知识点信息
                # cursor.execute(
                #     "select "
                #     "knowledge_point.id as concept_id, "
                #     "knowledge_point.point_txt as concept, "
                #     "test_question_info.id as question_id "
                #     "from knowledge_point "
                #     "join test_point_question on knowledge_point.id = test_point_question.point_id "
                #     "join test_question_info on test_point_question.question_id = test_question_info.id; "
                # )
                # self.dataset["question_concept"] = cursor.fetchall()
        return self

    def query_user_log_from_mysql(self) -> "DataPipeline":
        """查询用户行为日志信息"""
        # 连接 MySQL
        with pymysql.connect(**config.MYSQL_CONFIG) as mysql_conn:
            # 创建 MySQL 游标
            with mysql_conn.cursor(pymysql.cursors.DictCursor) as cursor:
                # 用户基础信息
                cursor.execute(
                    "select id as user_id, birthday, gender from edu_graph_dm.user_info; "
                )
                self.dataset["user_info"] = cursor.fetchall()

                # 用户收藏课程
                cursor.execute(
                    "select user_id, course_id, create_time as favor_time from edu_graph_dm.favor_info; "
                )
                self.dataset["user_favor"] = cursor.fetchall()

                # 用户答题信息
                cursor.execute(
                    "select "
                    "user_id, "
                    "question_id, "
                    "is_correct "
                    "from edu_graph_dm.test_exam_question "
                    "join ( "
                    "    select max(id) as id " # 最新的id，答题记录主键自增。
                    "    from edu_graph_dm.test_exam_question "
                    "    group by user_id, question_id "
                    ") as latest_question "
                    "on test_exam_question.id = latest_question.id; "
                )
                self.dataset["user_answer"] = cursor.fetchall()

                # 用户章节进度
                cursor.execute(
                    "select "
                    "user_id, "
                    "chapter_id, "
                    "position_sec, "
                    "create_time as watch_time "
                    "from edu_graph_dm.user_chapter_progress "
                    "join( "
                    "    select "
                    "    max(id) as id "
                    "    from edu_graph_dm.user_chapter_progress "
                    "    group by user_id, chapter_id "
                    ") as latest_watch on user_chapter_progress.id = latest_watch.id; "
                )
                self.dataset["user_chapter_progress"] = cursor.fetchall()
        return self

    # --------- 数据清洗 ---------

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

    def data_cleaning(self):
        """对数据进行清洗"""
        # 课程名称、课程介绍
        for course in self.dataset.get("course", []):
            # 保留原始名称
            course["raw_course_name"] = course["course_name"]
            # 清洗后的名称
            course["course_name"] = self._standardize_text(course["course_name"])
            course["course_introduce"] = self._standardize_text(
                course["course_introduce"]
            )
        # 章节名称、视频名称
        for chapter in self.dataset.get("course_chapter_video", []):
            # 保留原始名称
            chapter["raw_chapter_name"] = chapter["chapter_name"]
            chapter["raw_video_name"] = chapter["video_name"]
            # 清洗后的名称
            chapter["chapter_name"] = self._standardize_text(chapter["chapter_name"])
            chapter["video_name"] = self._standardize_text(chapter["video_name"])
        # 试卷名称、试题名称
        for paper in self.dataset.get("course_paper_question", []):
            # 保留原始名称
            paper["raw_paper_name"] = paper["paper_name"]
            paper["raw_question_name"] = paper["question_name"]
            # 清洗后的名称
            paper["paper_name"] = self._standardize_text(paper["paper_name"])
            paper["question_name"] = self._standardize_text(paper["question_name"])

        # 试题中的知识点
        for question_concept in self.dataset.get("question_concept", []):
            question_concept["concept"] = self._standardize_text(
                question_concept["concept"]
            )
        return self

    # --------- 使用模型抽取知识点 ---------

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
        print(f"抽取出 {count} 个知识点")

        # 抽取章节名称中的知识点
        print("抽取章节名称中的知识点")
        count = 0
        chapter_datas = [
            (chapter["chapter_id"], chapter["chapter_name"])
            for chapter in self.dataset.get("course_chapter_video", [])
            if chapter.get("chapter_name")
        ]
        chapter_id_list, chapter_name_list = zip(*chapter_datas)
        ee_dict_list = eemodel(list(chapter_name_list), schema)
        for chapter_id, ee_dict in zip(chapter_id_list, ee_dict_list):
            concept_list = ee_dict.get(schema[0], [])
            if not concept_list:
                continue
            concept_list = list(set(concept_list))
            self.dataset.setdefault("chapter_concept", []).extend(
                [{"chapter_id": chapter_id, "concept": c} for c in concept_list]
            )
            count += len(concept_list)
        print(f"抽取出 {count} 个知识点")

        return self

    # --------- 数据导入 Neo4j ---------

    def _batch_insert(
            self,
            driver: Driver,
            query: str,
            params: list,
            batch_size=1000,
            desc="",
    ):
        with driver.session() as session:
            for item in tqdm(range(0, len(params), batch_size), desc=desc):
                batch = params[item: item + batch_size]
                session.run(query, {"batch": batch})

    def import_course_data_to_neo4j(self) -> "DataPipeline":
        """导入课程资料数据和知识体系数据到 Neo4j"""
        with GraphDatabase.driver(config.NEO4J_CONFIG['uri'], auth=config.NEO4J_CONFIG['auth']) as driver:
            # 课程资料信息
            #   (课程)-[:BELONG]->(学科)-[:BELONG]->(分类)
            #   (价格)<-[:HAVE]-(课程)-[:HAVE]->(教师)
            self._batch_insert(
                driver,
                query="""
                    UNWIND $batch AS row
                    MERGE (course:Course {course_id: row.course_id, name: row.course_name, raw_name: row.raw_course_name})
                    MERGE (subject:Subject {subject_id: row.subject_id, name: row.subject_name})
                    MERGE (category:Category {category_id: row.category_id, name: row.category_name})
                    MERGE (teacher:Teacher {name: row.teacher_name})
                    MERGE (course)-[:BELONG]->(subject)
                    MERGE (subject)-[:BELONG]->(category)
                    MERGE (course)-[:HAVE]->(teacher)
                    MERGE (course)-[:HAVE]->(price:Price {price: row.price})
                """,
                params=[
                    {
                        "course_id": course["course_id"],
                        "course_name": course["course_name"],
                        "raw_course_name": course["raw_course_name"],
                        "subject_id": course["subject_id"],
                        "subject_name": course["subject_name"],
                        "category_id": course["category_id"],
                        "category_name": course["category_name"],
                        "teacher_name": course["teacher_name"],
                        "price": float(course["price"]),
                    }
                    for course in self.dataset.get("course", [])
                ],
                desc="课程",
            )

            #   (课程)<-[:BELONG]-(章节)<-[:BELONG]-(视频)
            self._batch_insert(
                driver,
                query="""
                    UNWIND $batch as row
                    MERGE (course:Course {course_id: row.course_id})
                    MERGE (chapter:Chapter {chapter_id: row.chapter_id, name: row.chapter_name, raw_name: row.raw_chapter_name})
                    MERGE (video:Video {video_id: row.video_id, name: row.video_name, raw_name: row.raw_video_name})
                    MERGE (course)<-[:BELONG]-(chapter)
                    MERGE (chapter)<-[:BELONG]-(video)
                """,
                params=[
                    {
                        "course_id": course_chapter_video["course_id"],
                        "chapter_id": course_chapter_video["chapter_id"],
                        "chapter_name": course_chapter_video["chapter_name"],
                        "raw_chapter_name": course_chapter_video["raw_chapter_name"],
                        "video_id": course_chapter_video["video_id"],
                        "video_name": course_chapter_video["video_name"],
                        "raw_video_name": course_chapter_video["raw_video_name"],
                    }
                    for course_chapter_video in self.dataset.get(
                        "course_chapter_video", []
                    )
                ],
                desc="章节",
            )

            #   (课程)<-[:BELONG]-(试卷)<-[:BELONG]-(试题)
            self._batch_insert(
                driver,
                query="""
                    UNWIND $batch as row
                    MERGE (course:Course {course_id: row.course_id})
                    MERGE (paper:Paper {paper_id: row.paper_id, name: row.paper_name, raw_name: row.raw_paper_name})
                    MERGE (question:Question {question_id: row.question_id, name: row.question_name, raw_name: row.raw_question_name})
                    MERGE (course)<-[:BELONG]-(paper)
                    MERGE (paper)<-[:BELONG]-(question)
                """,
                params=[
                    {
                        "course_id": course_paper_question["course_id"],
                        "paper_id": course_paper_question["paper_id"],
                        "paper_name": course_paper_question["paper_name"],
                        "raw_paper_name": course_paper_question["raw_paper_name"],
                        "question_id": course_paper_question["question_id"],
                        "question_name": course_paper_question["question_name"],
                        "raw_question_name": course_paper_question["raw_question_name"],
                    }
                    for course_paper_question in self.dataset.get(
                        "course_paper_question", []
                    )
                ],
                desc="试卷",
            )

            # 知识概念体系
            #   课程中的知识点
            self._batch_insert(
                driver,
                query="""
                    UNWIND $batch as row
                    MERGE (course:Course {course_id: row.course_id})
                    MERGE (concept:Concept {name: row.concept_name})
                    MERGE (course)-[:HAVE]->(concept)
                """,
                params=[
                    {
                        "course_id": course_concept["course_id"],
                        "concept_name": course_concept["concept"],
                    }
                    for course_concept in self.dataset.get("course_concept", [])
                ],
                desc="课程中的知识点",
            )

            #   章节中的知识点
            self._batch_insert(
                driver,
                query="""
                    UNWIND $batch as row
                    MERGE (chapter:Chapter {chapter_id: row.chapter_id})
                    MERGE (concept:Concept {name: row.concept_name})
                    MERGE (chapter)-[:HAVE]->(concept)
                """,
                params=[
                    {
                        "chapter_id": chapter_concept["chapter_id"],
                        "concept_name": chapter_concept["concept"],
                    }
                    for chapter_concept in self.dataset.get("chapter_concept", [])
                ],
                desc="章节中的知识点",
            )

            #   试题中的知识点
            self._batch_insert(
                driver,
                query="""
                    UNWIND $batch as row
                    MATCH (question:Question {question_id: row.question_id})
                    MERGE (concept:Concept {name: row.concept_name})
                    MERGE (question)-[:HAVE]->(concept)
                """,
                params=[
                    {
                        "question_id": question_concept["question_id"],
                        "concept_name": question_concept["concept"],
                    }
                    for question_concept in self.dataset.get("question_concept", [])
                ],
                desc="试题中的知识点",
            )

            #   先修关系
            print("创建先修关系...")
            _, summary, _ = driver.execute_query(
                """
                MATCH (concept:Concept)<-[:HAVE]-(chapter:Chapter)-[:BELONG]->(course:Course)<-[:BELONG]-(pre_chapter:Chapter)-[:HAVE]->(pre_concept:Concept)
                WHERE chapter.chapter_id > pre_chapter.chapter_id AND concept <> pre_concept
                WITH DISTINCT concept, pre_concept
                MERGE (concept)-[:NEED]->(pre_concept)
                """
            )
            print(f"成功创建{summary.counters.relationships_created}条先修关系")

            #   包含关系
            print("创建包含关系...")
            _, summary, _ = driver.execute_query(
                """
                MATCH (concept:Concept)<-[:HAVE]-(chapter:Chapter)-[:BELONG]->(course:Course)-[:HAVE]->(bigger_concept:Concept)
                WHERE concept <> bigger_concept
                WITH DISTINCT concept, bigger_concept
                MERGE (concept)-[:BELONG]->(bigger_concept)
                """
            )
            print(f"成功创建{summary.counters.relationships_created}条包含关系")

            #   相关关系
            print("创建相关关系...")
            _, summary, _ = driver.execute_query(
                """
                MATCH (concept:Concept)<-[:HAVE]-(question:Question)-[:BELONG]->(paper:Paper)<-[:BELONG]-(rela_question:Question)-[:HAVE]->(rela_concept:Concept)
                WHERE concept <> rela_concept AND elementId(concept) < elementId(rela_concept)
                WITH DISTINCT concept, rela_concept
                MERGE (concept)-[:RELATED]->(rela_concept)
                """
            )
            print(f"成功创建{summary.counters.relationships_created}条相关关系")
        return self

    def import_user_log_to_neo4j(self) -> "DataPipeline":
        """导入用户行为数据到 Neo4j"""
        with GraphDatabase.driver(config.NEO4J_CONFIG['uri'], auth=config.NEO4J_CONFIG['auth']) as driver:
            # 用户基本信息
            self._batch_insert(
                driver,
                query="""
                    UNWIND $batch as row
                    MERGE (user:User {user_id: row.user_id, birthday: row.birthday, gender: row.gender})
                """,
                params=[
                    {
                        "user_id": user["user_id"],
                        "birthday": user["birthday"],
                        "gender": user["gender"] if user["gender"] else "unknown",
                    }
                    for user in self.dataset.get("user_info", [])
                ],
                desc="学生信息",
            )

            # 用户收藏课程
            self._batch_insert(
                driver,
                query="""
                    UNWIND $batch as row
                    MATCH (user:User {user_id: row.user_id}), (course:Course {course_id: row.course_id})
                    MERGE (user)-[:FAVOR {time: row.time}]->(course)
                """,
                params=[
                    {
                        "user_id": user_favor["user_id"],
                        "course_id": user_favor["course_id"],
                        "time": user_favor["favor_time"],
                    }
                    for user_favor in self.dataset.get("user_favor", [])
                ],
                desc="学生收藏行为",
            )

            # 用户答题情况
            self._batch_insert(
                driver,
                query="""
                    UNWIND $batch as row
                    MATCH (user:User {user_id: row.user_id}), (question:Question {question_id: row.question_id})
                    MERGE (user)-[:ANSWER {is_correct: row.is_correct}]->(question)
                """,
                params=[
                    {
                        "user_id": user_answer["user_id"],
                        "question_id": user_answer["question_id"],
                        "is_correct": user_answer["is_correct"],
                    }
                    for user_answer in self.dataset.get("user_answer", [])
                ],
                desc="学生答题情况",
            )

            # 用户章节进度
            self._batch_insert(
                driver,
                query="""
                    UNWIND $batch as row
                    MATCH (user:User {user_id: row.user_id}), (chapter:Chapter {chapter_id: row.chapter_id})
                    MERGE (user)-[:WATCH {position_sec: row.position_sec, watch_time: row.watch_time}]->(chapter)
                """,
                params=[
                    {
                        "user_id": user_chapter_progress["user_id"],
                        "chapter_id": user_chapter_progress["chapter_id"],
                        "position_sec": user_chapter_progress["position_sec"],
                        "watch_time": user_chapter_progress["watch_time"],
                    }
                    for user_chapter_progress in self.dataset.get(
                        "user_chapter_progress", []
                    )
                ],
                desc="学生章节进度",
            )
        return self


# --------- 清空 Neo4j ---------


def clear_neo4j():
    """清空 Neo4j 中的约束和数据，并创建属性唯一性约束"""

    # 连接 Neo4j
    with GraphDatabase.driver(config.NEO4J_CONFIG['uri'], auth=config.NEO4J_CONFIG['auth']) as driver:
        # 删除所有约束
        records, _, _ = driver.execute_query("SHOW CONSTRAINTS")
        constraints = [record["name"] for record in records]
        for constraint in constraints:
            driver.execute_query(f"DROP CONSTRAINT {constraint} IF EXISTS")
        print("清空约束")

        # 清空数据
        driver.execute_query("MATCH (n) DETACH DELETE n")
        print("清空数据")

        # 创建属性唯一性约束
        for constraint in [
            "CREATE CONSTRAINT category_category_id IF NOT EXISTS FOR (category:Category) REQUIRE category.category_id IS UNIQUE",
            "CREATE CONSTRAINT subject_subject_id IF NOT EXISTS FOR (subject:Subject) REQUIRE subject.subject_id IS UNIQUE",
            "CREATE CONSTRAINT course_course_id IF NOT EXISTS FOR (course:Course) REQUIRE course.course_id IS UNIQUE",
            "CREATE CONSTRAINT teacher_name IF NOT EXISTS FOR (teacher:Teacher) REQUIRE teacher.name IS UNIQUE",
            "CREATE CONSTRAINT price_name IF NOT EXISTS FOR (price:Process) REQUIRE price.name IS UNIQUE",
            "CREATE CONSTRAINT chapter_chapter_id IF NOT EXISTS FOR (chapter:Chapter) REQUIRE chapter.chapter_id IS UNIQUE",
            "CREATE CONSTRAINT video_video_id IF NOT EXISTS FOR (video:Video) REQUIRE video.video_id IS UNIQUE",
            "CREATE CONSTRAINT paper_paper_id IF NOT EXISTS FOR (paper:Paper) REQUIRE paper.paper_id IS UNIQUE",
            "CREATE CONSTRAINT question_question_id IF NOT EXISTS FOR (question:Question) REQUIRE question.question_id IS UNIQUE",
            "CREATE CONSTRAINT user_user_id IF NOT EXISTS FOR (user:User) REQUIRE user.user_id IS UNIQUE",
            "CREATE CONSTRAINT concept_concept_name IF NOT EXISTS FOR (concept:Concept) REQUIRE concept.concept_name IS UNIQUE",
        ]:
            driver.execute_query(constraint)
        print("属性唯一性约束创建成功")


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

"""
/Users/zjm/miniconda3/envs/graph/bin/python /Users/zjm/PycharmProjects/LLM_2026_demo/education_graph_chat/src/datasync/data_prepare.py 
创建 edu_graph_dm
edu_graph_dm 创建成功
导入数据
数据导入成功
清空约束
清空数据
属性唯一性约束创建成功
[2026-01-30 15:44:29,939] [    INFO] - >>> [PyTorchInferBackend] Creating Engine ...
[2026-01-30 15:44:30,000] [    INFO] - >>> [PyTorchInferBackend] Use CPU to inference ...
[2026-01-30 15:44:30,000] [    INFO] - >>> [PyTorchInferBackend] Engine Created ...
抽取课程介绍中的知识点
/Users/zjm/miniconda3/envs/graph/lib/python3.12/site-packages/transformers/modeling_utils.py:1735: FutureWarning: The `device` argument is deprecated and will be removed in v5 of Transformers.
  warnings.warn(
抽取出 289 个知识点
抽取章节名称中的知识点
抽取出 9300 个知识点
加载嵌入模型
检测到 1297 个新增知识点
huggingface/tokenizers: The current process just got forked, after parallelism has already been used. Disabling parallelism to avoid deadlocks...
To disable this warning, you can either:
	- Avoid using `tokenizers` before the fork if possible
	- Explicitly set the environment variable TOKENIZERS_PARALLELISM=(true | false)
/Users/zjm/miniconda3/envs/graph/lib/python3.12/site-packages/torch/nn/modules/module.py:1786: FutureWarning: `encoder_attention_mask` is deprecated and will be removed in version 4.55.0 for `BertSdpaSelfAttention.forward`.
  return forward_call(*args, **kwargs)
新增 1297 条知识点到数据库
102 条数据已存在于向量数据库中
复用已加载的嵌入模型
Batches:   0%|          | 0/102 [00:00<?, ?it/s]/Users/zjm/miniconda3/envs/graph/lib/python3.12/site-packages/torch/nn/modules/module.py:1786: FutureWarning: `encoder_attention_mask` is deprecated and will be removed in version 4.55.0 for `BertSdpaSelfAttention.forward`.
  return forward_call(*args, **kwargs)
Batches: 100%|██████████| 102/102 [01:12<00:00,  1.40it/s]
writing into chroma: 100%|██████████| 51/51 [00:04<00:00, 11.34it/s]
添加 12964 条数据到向量数据库
课程: 100%|██████████| 1/1 [00:01<00:00,  1.13s/it]
章节: 100%|██████████| 6/6 [00:02<00:00,  2.39it/s]
试卷: 100%|██████████| 1/1 [00:00<00:00,  4.40it/s]
课程中的知识点: 100%|██████████| 1/1 [00:00<00:00,  7.99it/s]
章节中的知识点: 100%|██████████| 10/10 [00:03<00:00,  3.00it/s]
试题中的知识点: 0it [00:00, ?it/s]
创建先修关系...
成功创建57600条先修关系
创建包含关系...
成功创建5531条包含关系
创建相关关系...
成功创建0条相关关系
学生信息: 100%|██████████| 1/1 [00:00<00:00,  9.17it/s]
学生收藏行为: 100%|██████████| 1/1 [00:00<00:00, 10.90it/s]
学生答题情况: 100%|██████████| 2/2 [00:00<00:00, 16.21it/s]
学生章节进度: 100%|██████████| 2/2 [00:00<00:00,  8.40it/s]

进程已结束，退出代码为 0

"""