"""
  @Author:LiNing
  @Time:2026/9/23
  @Desc:文档切分节点,负责将整个md文本切分成chunks方便检索
"""
import sys
from pathlib import Path
from typing import Any

from common.logging.logger import logger, node_log, step_log
from processor.import_processor.state import ImportGraphState
from utils.task_utils import add_done_task, add_running_task

@step_log("step_1_validate_get_data")
def step_1_validate_get_data(state)->tuple[str, str, str]:
    """

    :param state:
    :return:
    """
    md_content = state.get("md_content")
    md_path = state.get("md_path")
    file_title = state.get("file_title")

    if not md_content:
        if (not md_path) or (not md_path.is_file()):
            logger.error(f"md_content内容为空,md_path也为空或者没有对应的文件,业务无法继续,提前终止!")
            raise ValueError(f"md_content内容为空,md_path也为空或者没有对应的文件,业务无法继续,提前终止!")
        # 从md_path中读取数据
        md_content = Path(md_path).read_text(encoding="utf-8")
        state["md_content"] = md_content

    if not file_title:
        file_title = Path(md_path).stem or "default"
        logger.warning(f"file_title为空,给与默认值:{file_title}")
        state['file_title'] = file_title

    # 统一不同系统的换行
    md_content = md_content.replace("\r\n", "\n").replace("\r", "\n")

    return md_content,file_title,md_path

@step_log("step_2_split_document_by_title")
def step_2_split_document_by_title(md_content, file_title)->list[dict[str,Any]]:
    pass


@node_log("node_document_split")
def node_document_split(state: ImportGraphState) -> ImportGraphState:
    """
    节点: 文档切分 (node_document_split)
    """
    # 1. 加载节点到运行时列表
    add_running_task(state.get("task_id"),"node_document_split")

    # 2. 从状态中获取状态并校验
    md_content,file_title,md_path = step_1_validate_get_data(state)

    # 3. 按照标题对文本进行初次切割 -- 保语义
    chunks = step_2_split_document_by_title(md_content,file_title)

    # 4. 精细化切分 -- 保大小,边界
    # 5. 补充追溯信息(part,parent_title) -- 可追溯
    # 6. 将chunk持久化
    # 7. 更新状态
    # 8. 将节点添加到已完成列表
    add_done_task(state.get("task_id"),"node_document_split")
    return state
