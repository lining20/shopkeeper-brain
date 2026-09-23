"""
  @Author:LiNing
  @Time:2026/9/23
  @Desc:导入向量数据库节点,负责将向量存入向量数据库当中
"""
import sys

from common.logging.logger import logger, node_log
from processor.import_processor.state import ImportGraphState

@node_log("node_import_milvus")
def node_import_milvus(state: ImportGraphState) -> ImportGraphState:
    """
    节点: 导入向量库 (node_import_milvus)
    为什么叫这个名字: 将处理好的向量数据写入 Milvus 数据库。
    未来要实现:
    1. 连接 Milvus。
    2. 根据 item_name 删除旧数据 (幂等性)。
    3. 批量插入新的向量数据。
    """
    return state
