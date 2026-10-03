"""
  @Author:LiNing
  @Time:2026/9/23
  @Desc:文档切分节点,负责将整个md文本切分成chunks方便检索
"""
import json
import os
import re
from pathlib import Path
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pandas._libs import index

from common.logging.logger import logger, node_log, step_log
from processor.import_processor.state import ImportGraphState
from utils.task_utils import add_done_task, add_running_task

# ====================== 全局配置（可根据模型调整）======================
# 文本切块最大长度：单个文本块最多包含 1000 字符（防止过长导致向量失真）
CHUNK_MAX_SIZE = 1000
# 文本切块基准长度：单个文本块理想大小为 600 字符（兼顾语义完整性 + 检索精度）
CHUNK_SIZE = 600
# 文本块重叠长度：相邻块之间重叠 20 字符，保证语义不被切断、上下文连贯
CHUNK_OVERLAP = 50
# 最小碎片阈值：低于这个长度判定为短碎片，需要尝试合并
CHUNK_MIN = 400


@step_log("step_1_validate_get_data")
def step_1_validate_get_data(state) -> tuple[str, str, str]:
    """
    从状态中获取 Markdown 内容、文件标题和文件路径，并统一换行符。

    :param state: 导入流程状态，提供 md_content、md_path 和 file_title。
    :return: (md_content, file_title, md_path)，依次为换行符统一后的文本、文件标题和原文件路径。

    流程：读取状态数据 -> 内容为空时从 Markdown 文件读取并写回状态
          -> 标题为空时从文件名推导并写回状态 -> 统一换行符 -> 返回所需数据。
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

    return md_content, file_title, md_path


@step_log("step_2_split_document_by_title")
def step_2_split_document_by_title(md_content, file_title) -> list[dict[str, Any]]:
    """
    按 Markdown 标题层级将文本切分为保留标题路径的内容块。

    :param md_content: 待切分的 Markdown 文本。
    :param file_title: 文件标题，写入每个内容块；全文无标题时作为块标题。
    :return: 内容块列表，每块包含 file_title、title 和 content；有标题时，title 为用下划线连接的标题路径。

    流程：逐行跳过空行并识别代码围栏 -> 在代码块外识别一至六级标题
          -> 按标题层级维护标题路径并收集正文 -> 将标题前内容并入首块
          -> 结算最后一块；全文无标题时按文件标题生成内容块。
    """
    # 1. 初始化结果
    chunks = []

    # 2. 初始化处理过程中需要记住的状态
    # 当前标题
    current_title: str | None = None
    # 当前标题下的正文
    current_content_lines: list[str] = []
    # 第一个标题之前的内容(孤儿内容)
    orphan_lines: list[str] = []
    # 是否已经处理过标题前的内容
    has_flushed_first_chunk: bool = False
    # 是否处于代码块中
    is_code: bool = False
    # 各级标题组成的路径(列表表示,类似栈实现)
    heading_stack: list[str | None] = []

    # 3. 准备标题识别规则：匹配 1～6 个 #、空白和标题文字
    title_rep = re.compile(r"^#{1,6}\s.+")

    # 4. 将 Markdown 按行拆开并逐行处理
    for line in md_content.splitlines():
        # 4.1 跳过空行；当前实现也会跳过代码块中的空行
        line_strip = line.strip()
        if not line_strip:
            continue
        # 4.2 遇到代码围栏就切换状态；当前不检查开闭围栏是否同一种
        if line_strip.startswith(("```", "~~~")):
            # 切换“是否在代码块中”的状态
            is_code = not is_code
            # 尚无标题时归入标题前内容，否则归入当前正文
            if current_title is None:
                orphan_lines.append(line_strip)
            else:
                current_content_lines.append(line_strip)
            continue

        # 4.3 代码块内的非空行按原文保存，不再识别标题
        if is_code:
            # 使用原始 line，保留代码缩进
            if current_title is None:
                orphan_lines.append(line)
            else:
                current_content_lines.append(line)
            continue

        # 4.4 识别标题；line_strip 已去除行首缩进
        if title_rep.match(line_strip):
            # ① 遇到新标题时，先结算上一个标题下收集的正文
            if current_title is not None and len(current_content_lines) > 0:
                # ② 首次结算时，将标题前的内容并入当前块，避免重复处理
                if not has_flushed_first_chunk and len(orphan_lines) > 0:
                    current_content_lines = orphan_lines + current_content_lines
                    orphan_lines = []
                    has_flushed_first_chunk = True

                # ③ 用旧标题和正文生成 chunk，保存后清空正文缓存
                full_content = current_title + "\n" + "\n".join(current_content_lines)
                chunks.append({
                    "file_title": file_title,
                    "title": current_title,
                    "content": full_content,
                })
                current_content_lines = []
            # ④ 根据行首 # 的数量计算新标题层级
            heading_level = len(line_strip) - len(line_strip.lstrip("#"))
            # ⑤ 如果标题跳级，用 None 补齐缺少的层级
            while len(heading_stack) < heading_level:
                heading_stack.append(None)

            # ⑥ 保留上级标题，替换同级旧标题，并移除旧的下级标题
            heading_stack = heading_stack[:heading_level]
            heading_stack[heading_level - 1] = line_strip
            # ⑦ 将标题路径拼成 current_title，供正文归属和结算时使用
            current_title = "_".join(h for h in heading_stack if h)
            continue

        # 4.5 其余非空行作为普通正文
        if current_title is None:
            # 没有当前标题 → 加入标题前内容
            orphan_lines.append(line)
        else:
            # 有当前标题 → 加入当前正文
            current_content_lines.append(line)

    # 5. 循环结束后结算最后一块；只有标题、没有正文时不生成 chunk
    if current_title is not None:
        if len(current_content_lines) > 0 or (not has_flushed_first_chunk and len(orphan_lines) > 0):
            if not has_flushed_first_chunk and len(orphan_lines) > 0:
                current_content_lines = orphan_lines + current_content_lines
                orphan_lines = []
                has_flushed_first_chunk = True

            # 用最后一个标题和正文生成 chunk，保存到结果列表
            full_content = current_title + "\n" + "\n".join(current_content_lines)
            chunks.append({
                "file_title": file_title,
                "title": current_title,
                "content": full_content,
            })
    elif len(orphan_lines) > 0:
        # 如果全文没有标题，则用文件名作为标题生成 chunk
        chunks.append({
            "file_title": file_title,
            "title": file_title,
            "content": "\n".join(orphan_lines),
        })

    logger.info(f"已经根据标题进行多级切块（极简稳健版），现有的块: {len(chunks)}")
    # 6. 返回结果
    return chunks


@step_log("_split_chunk_content")
def _split_chunk_content(chunk) -> list[dict[str, Any]]:
    """
    将过长的标题内容块递归切分为带有来源信息的子块。

    :param chunk: 待切分的内容块，需包含 file_title、title 和 content。
    :return: 子块列表，每块包含 file_title、parent_title、part、title 和 content。

    流程：从正文中去掉标题前缀 -> 按目标长度和重叠长度递归切分
          -> 为每个子块添加序号与父标题 -> 将标题前缀放回内容并返回。
    """
    # 定义返回列表
    sub_chunks: list[dict[str, Any]] = []

    # 获取chunk的内容
    chunk_content = chunk.get("content")
    # 获取chunk的前缀title
    prefix = chunk.get("title") + "\n"
    # 去除前缀
    chunk_content = chunk_content[len(prefix):]
    # 创建递归切分器
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE - len(prefix),
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " "]
    )
    # 对切分后的列表进行遍历,放入返回列表中
    for index, text in enumerate(splitter.split_text(chunk_content), start=1):
        sub_chunks.append({
            "file_title": chunk.get("file_title"),
            "parent_title": chunk.get("title"),
            "part": index,
            "title": f"{chunk.get("title")}_{index}",
            "content": prefix + text,
        })

    return sub_chunks


@step_log("_merge_chunk_content")
def _merge_chunk_content(refine_chunks) -> list[dict[str, Any]]:
    """
    尝试合并同一父标题下相邻的短内容块。

    :param refine_chunks: 精细切分后的内容块列表，每块包含 parent_title 和 content。
    :return: 按当前合并规则生成的内容块列表。

    流程：依次比较当前块与下一块 -> 当前块不超过最小长度时，检查父标题
          和合并后的最大长度 -> 满足条件则拼接内容，否则保存当前块并继续。
    """
    # 定义返回列表
    merge_chunks: list[dict[str, Any]] = []
    # 定义基类chunk
    base_chunk: dict[str, Any] = None
    # 对列表进行遍历
    for next_chunk in refine_chunks:
        # 第一个元素跳出
        if base_chunk is None:
            base_chunk = next_chunk
            continue
        # 判断当前的base_chunk是否超过了chunk_min
        if not len(base_chunk.get("content")) > CHUNK_MIN:
            # 判断是否在同一个parent_title下
            if base_chunk.get("parent_title") == next_chunk.get("parent_title"):
                # 判断两者合并是否大于CHUNK_MAX_SIZE
                base_content: str = base_chunk.get("content")
                next_content: str = next_chunk.get("content")
                if not (len(base_content) + len(next_content) > CHUNK_MAX_SIZE):
                    # 不大于,等待下一次
                    base_chunk["content"] = base_content + "\n" + next_content
                else:
                    merge_chunks.append(base_chunk)
                    base_chunk = next_chunk
            else:
                merge_chunks.append(base_chunk)
                base_chunk = next_chunk
        else:
            # 不进行合并
            merge_chunks.append(base_chunk)
            base_chunk = next_chunk

    if not base_chunk:
        merge_chunks.append(base_chunk)
    logger.info(f"完成小于400的chunk的合并,合并后的数量:{len(merge_chunks)}")

    return merge_chunks


@step_log("step_3_refine_split_and_merge_chunks")
def step_3_refine_split_and_merge_chunks(title_chunks):
    """
    对按标题切分的内容块进行长度细分，并尝试合并短块。

    :param title_chunks: 按标题切分的内容块列表，每块包含 file_title、title 和 content。
    :return: 带有父标题与分块序号的精细内容块列表。

    流程：遍历标题内容块 -> 超过目标长度时递归切分
          -> 其余内容块补充父标题和序号 -> 合并符合条件的短块并返回。
    """
    # 初始化返回列表
    refine_chunks: list[dict[str, Any]] = []

    # 对title_chunks列表进行遍历
    for chunk in title_chunks:
        if len(chunk.get("content")) > CHUNK_SIZE:
            # 超过规定的大小,进行细分
            refine_chunks.extend(_split_chunk_content(chunk))
        else:
            # 不需要切分
            temp_chunk = {
                "file_title": chunk.get("file_title"),
                "parent_title": chunk.get("title"),
                "part": 1,
                "title": chunk.get("title"),
                "content": chunk.get("content"),
            }
            refine_chunks.append(temp_chunk)
    logger.info(f"chunks经过超长以后向短切割处理! 切割后的数量:{len(refine_chunks)}")
    # 对递归切分后的列表进行合并
    # 条件:1.在同一个parent_title下
    #     2.待合并的chunk内容 < CHUNK_MIN(400)
    #     3.合并后的chunk内容 < CHUNK_MAX_SIZE(1000)
    refine_chunks = _merge_chunk_content(refine_chunks)

    return refine_chunks


@step_log("step_4_backup_chunks_json")
def step_4_backup_chunks_json(refine_chunks, md_path):
    """
    将精细切分后的内容块保存为与 Markdown 文件同名的 JSON 文件。

    :param refine_chunks: 需要持久化的内容块列表。
    :param md_path: 原 Markdown 文件路径，用于确定 JSON 文件的位置和名称。
    :return: 无返回值。

    流程：根据 Markdown 路径生成同目录的 .json 路径
          -> 将内容块序列化为格式化 JSON -> 以 UTF-8 写入文件并记录位置。
    """
    # 封装成path对象
    md_path_obj = Path(md_path)
    # 封装json的路径对象
    json_path_obj = md_path_obj.parent / f"{md_path_obj.stem}.json"
    # 写入文件
    json_path_obj.write_text(
        json.dumps(refine_chunks,ensure_ascii=False,indent=4),
        encoding="utf-8",
    )
    logger.info(f"完成chunks数据的备份,备份位置:{str(json_path_obj)}")


@node_log("node_document_split")
def node_document_split(state: ImportGraphState) -> ImportGraphState:
    """
    将 Markdown 文本按标题和长度切分，并保存分块结果。

    :param state: 导入流程状态，提供任务标识、Markdown 内容或路径及文件标题。
    :return: 写入 chunks 后的导入流程状态。

    流程：将节点加入运行列表 -> 获取并校验文本、标题和路径
          -> 按标题切分 -> 对长块细分并尝试合并短块
          -> 将分块写入 JSON 文件和状态 -> 将节点加入已完成列表。
    """
    # 1. 加载节点到运行时列表
    add_running_task(state.get("task_id"), "node_document_split")

    # 2. 从状态中获取状态并校验
    md_content, file_title, md_path = step_1_validate_get_data(state)

    # 3. 按照标题对文本进行初次切割 -- 保语义
    title_chunks = step_2_split_document_by_title(md_content, file_title)

    # 4. 精细化切分 -- 保大小,边界
    refine_chunks = step_3_refine_split_and_merge_chunks(title_chunks)
    # 5. 补充追溯信息(part,parent_title) -- 可追溯[上面已经修改,省略]
    # 6. 将chunk持久化
    step_4_backup_chunks_json(refine_chunks, md_path)
    # 7. 更新状态
    state["chunks"] = refine_chunks
    # 8. 将节点添加到已完成列表
    add_done_task(state.get("task_id"), "node_document_split")
    return state

if __name__ == "__main__":
    from utils.path_util import PROJECT_ROOT
    from processor.import_processor.nodes.node_md_img import node_md_img

    logger.info(f"本地测试 - 项目根目录：{PROJECT_ROOT}")

    # 测试MD文件路径（需手动将测试文件放入对应目录）
    test_md_name = os.path.join(r"output\hak180产品安全手册", "hak180产品安全手册_new.md")
    test_md_path = os.path.join(PROJECT_ROOT, test_md_name)

    # 校验测试文件是否存在
    if not os.path.exists(test_md_path):
        logger.error(f"本地测试 - 测试文件不存在：{test_md_path}")
        logger.info("请检查文件路径，或手动将测试MD文件放入项目根目录的output目录下")
    else:
        # 构造测试状态对象，模拟流程入参
        test_state = {
            "md_path": test_md_path,
            "task_id": "test_task_123456",
            "md_content": "",
            "file_title": "hak180产品安全手册",
            "local_dir": os.path.join(PROJECT_ROOT, "output"),
        }
        logger.info("开始本地测试 - MD图片处理全流程")
        # 执行核心处理流程
        result_state = node_md_img(test_state)
        logger.info(f"本地测试完成 - 处理结果状态：{result_state}")
        logger.info("\n=== 开始执行文档切分节点集成测试 ===")

        logger.info(">> 开始运行当前节点：node_document_split（文档切分）")
        final_state = node_document_split(result_state)
        final_chunks = final_state.get("chunks", [])
        logger.info(f"✅ 测试成功：最终生成{len(final_chunks)}个有效Chunk{final_chunks}")
