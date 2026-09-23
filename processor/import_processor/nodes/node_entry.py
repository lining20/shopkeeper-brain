"""
  @Author:LiNing
  @Time:2026/9/23
  @Desc:入口节点,负责接受外部输入
"""
import sys

from common.logging.logger import logger, node_log
from processor.import_processor.state import ImportGraphState

@node_log("node_entry")
def node_entry(state: ImportGraphState) -> ImportGraphState:
    """
    节点: 入口节点 (node_entry)
    为什么叫这个名字: 作为图的 Entry Point，负责接收外部输入并决定流程走向。
    未来要实现:
    1. 接收文件路径。
    2. 判断文件类型 (PDF/MD)。
    3. 设置 state 中的路由标记 (is_pdf_read_enabled / is_md_read_enabled)。
    """
    # 模拟简单的路由逻辑，防止报错 (仅 node_entry 需要)
    if "local_file_path" in state:
        path = state["local_file_path"]
        if path.endswith(".pdf"):
            state["is_pdf_read_enabled"] = True
        elif path.endswith(".md"):
            state["is_md_read_enabled"] = True

    return state
