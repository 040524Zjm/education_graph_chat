import pymysql
from pymysql.cursors import DictCursor

from src.configuration.config import *


class MySQLReader:
    def __init__(self):
        self.connection = pymysql.connect(**MYSQL_CONFIG)
        self.cursor = self.connection.cursor(DictCursor)

    def read_data(self, sql):
        self.cursor.execute(sql)
        return self.cursor.fetchall()

    def close(self):
        self.cursor.close()
        self.connection.close()

    def write_data(self, data, sql, bach_size):




class Neo4jWriter():
    def __init__(self):
        pass

    def write_node(self, ):
        pass

    def write_relationship(self):
        pass

    def write_full_text_index(self):
        pass

    def write_vector_text_index(self):
        pass



if __name__ == '__main__':
    pass