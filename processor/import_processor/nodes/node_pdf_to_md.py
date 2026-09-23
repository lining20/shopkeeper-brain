"""
  @Author:LiNing
  @Time:2026/9/23
  @Desc:PDF转化节点,将pdf转化为md文件
"""
import sys

from common.logging.logger import logger, node_log
from processor.import_processor.state import ImportGraphState

@node_log("node_pdf_to_md")
def node_pdf_to_md(state: ImportGraphState) -> ImportGraphState:
    """
    节点: PDF转Markdown (node_pdf_to_md)
    为什么叫这个名字: 核心任务是将 PDF 非结构化数据转换为 Markdown 结构化数据。
    未来要实现:
    1. 调用 MinerU (magic-pdf) 工具。
    2. 将 PDF 转换成 Markdown 格式。
    3. 将结果保存到 state["md_content"]。
    """
    return state
