"""
  @Author:LiNing
  @Time:2026/9/23
  @Desc: 图状态定义
"""
from typing import TypedDict
import copy
from common.logging.logger import logger

class ImportGraphState(TypedDict):
    """
    图的状态定义，包含所有节点产生和消费的数据字段。
    TypedDict 让我们在代码中能有自动补全和类型检查。
    使用字典式访问（如 state["task_id"]、state.get("chunks")）。
    """
    task_id: str

    # --- 流程控制标记 ---
    is_md_read_enabled: bool    # 判断是否为md文件
    is_pdf_read_enabled: bool   # 判断是否为pdf文件

    # --- 路径相关 ---
    local_dir: str  # 文件夹地址  (pdf -> md  -> 输出的文件夹地址)
    local_file_path: str  # 传入文件地址 不确定md pdf
    file_title: str # 文件名
    pdf_path: str  # pdf地址 文件 <- local_file_path
    md_path: str   # md地址 文件 <- local_file_path

    # --- 内容数据 ---
    md_content: str # 文件的内容
    chunks: list # 切割后的数据内容
    item_name: str # 文件对应的主题

    # --- 数据库相关 ---
    embeddings_content: list # 向量化后的数据内容


graph_default_state: ImportGraphState = {
    "task_id": "",
    "is_pdf_read_enabled": False,
    "is_md_read_enabled": False,
    "local_dir": "",
    "local_file_path": "",
    "pdf_path": "",
    "md_path": "",
    "file_title": "",
    "md_content": "",
    "chunks": [],
    "item_name": "",
    "embeddings_content": [],
}


def create_default_state(**overrides) -> ImportGraphState:
    """
    创建默认状态，支持覆盖。
    """
    state = copy.deepcopy(graph_default_state)
    state.update(overrides)
    return state


def get_default_state() -> ImportGraphState:
    """
    返回一个新的状态实例，避免全局变量污染。
    """
    return copy.deepcopy(graph_default_state)

if __name__ == "__main__":
    """
    测试
    """
    # 创建默认状态
    state = create_default_state(local_file_path="万用表RS-12的使用.pdf")
    logger.info(state)
