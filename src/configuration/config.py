from pathlib import Path
ROOT_DIR = Path(__file__).parent.parent.parent
import os
from dotenv import load_dotenv
load_dotenv()
mysql_password = os.getenv('MYSQL_PASSWORD')
neo4j_password = os.getenv('NEO4J_PASSWORD')


# 目录
DATA_DIR = ROOT_DIR / 'data'




# 数据库
MYSQL_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': mysql_password,
    'database': 'edu_graph_dm'
}

NEO4J_CONFIG = {
    'uri': 'neo4j://localhost',
}