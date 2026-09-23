"""
  @Author:LiNing
  @Time:2026/9/23
  @Desc:图片处理,负责md文件当中的图片资源
"""
import sys

from common.logging.logger import logger, node_log
from processor.import_processor.state import ImportGraphState

@node_log("node_md_img")
def node_md_img(state: ImportGraphState) -> ImportGraphState:
    """
    节点: 图片处理 (node_md_img)
    为什么叫这个名字: 处理 Markdown 中的图片资源 (Image)。
    未来要实现:
    1. 扫描 Markdown 中的图片链接。
    2. 将图片上传到 MinIO 对象存储。
    3. (可选) 调用多模态模型生成图片描述。
    4. 替换 Markdown 中的图片链接为 MinIO URL。
    """
    return state