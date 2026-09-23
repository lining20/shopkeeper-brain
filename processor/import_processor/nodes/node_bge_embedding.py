"""
  @Author:LiNing
  @Time:2026/9/23
  @Desc:向量化节点,将切分好的chunks转化为向量
"""
import sys

from common.logging.logger import logger, node_log
from processor.import_processor.state import ImportGraphState

@node_log("node_bge_embedding")
def node_bge_embedding(state: ImportGraphState) -> ImportGraphState:
    """
    节点: 向量化 (node_bge_embedding)
    为什么叫这个名字: 使用 BGE-M3 模型将文本转换为向量 (Embedding)。
    未来要实现:
    1. 加载 BGE-M3 模型。
    2. 对每个 Chunk 的文本进行 Dense (稠密) 和 Sparse (稀疏) 向量化。
    3. 准备好写入 Milvus 的数据格式。
    """
    return state
