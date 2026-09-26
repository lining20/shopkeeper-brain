"""
  @Author:LiNing
  @Time:2026/9/23
  @Desc:入口节点,负责接受外部输入
"""
import sys
from pathlib import Path

from common.logging.logger import logger, node_log
from processor.import_processor.state import ImportGraphState,create_default_state
from utils.task_utils import add_running_task, add_done_task


@node_log("node_entry")
def node_entry(state: ImportGraphState) -> ImportGraphState:
    """
    节点: 入口节点 (node_entry)
    :param state:
    :return: state
        逻辑: 节点进入运行列表 -> 获取本地文件路径 -> 进行非空判断 -
                -> 判断文件类型[根据类型更新状态] -> 文件标题状态更新 -
                -> 节点完成[加载到完成列表] -> 返回状态
    """
    # 1. 添加节点到运行列表中
    add_running_task(state.get("task_id"), "node_entry")

    # 2. 获取数据local_file_path : state
    local_file_path = state.get("local_file_path")

    # 3. 进行非空判断
    if not local_file_path:
        logger.warning("没有从状态中获取到 local_file_path ,导入流程终止")
        return state

    # 4. 判断文件类型,进行状态更新
    if local_file_path.endswith(".md"):
        # 判断为md文件: 更新 文件类型状态&文件地址
        state["is_md_read_enabled"] = True
        state["is_pdf_read_enabled"] = False

        state["md_path"] = local_file_path
        state["pdf_path"] = None
    elif local_file_path.endswith(".pdf"):
        # 判断为md文件: 更新 文件类型状态&文件地址
        state["is_pdf_read_enabled"] = True
        state["is_md_read_enabled"] = False

        state["pdf_path"] = local_file_path
        state["md_path"] = None
    else:
        # 其他文件格式
        logger.warning("文件类型不支持 ,导入流程终止")
        return state

    # 5. 文件标题更新
    state["file_title"] = Path(local_file_path).stem

    # . 将完成的节点加入到已完成列表
    add_done_task(state.get("task_id"), "node_entry")
    return state

# 测试
if __name__ == '__main__':

    # 单元测试：覆盖不支持类型、MD、PDF三种场景
    logger.info("===== 开始node_entry节点单元测试 =====")

    # 测试1: 不支持的TXT文件
    test_state1 = create_default_state(
        task_id="test_task_001",
        local_file_path="联想海豚用户手册.txt"
    )
    node_entry(test_state1)

    # 测试2: MD文件
    test_state2 = create_default_state(
        task_id="test_task_002",
        local_file_path="小米用户手册.md"
    )
    node_entry(test_state2)

    # 测试3: PDF文件
    test_state3 = create_default_state(
        task_id="test_task_003",
        local_file_path="测试文档3.pdf"
    )
    node_entry(test_state3)

    # 测试4: 没有文件路径
    test_state4 = create_default_state(
        task_id="test_task_004",
    )
    node_entry(test_state4)

    logger.info("===== 结束node_entry节点单元测试 =====")
