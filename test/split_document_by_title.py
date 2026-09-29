"""
  @Author:LiNing
  @Time:2026/9/29
  @Desc:测试md文档按照标题进行粗切割
"""
import re


def split_document_by_title(md_content: str, file_title: str) -> list[dict]:
    """
    按 Markdown 标题层级将文档切分为内容块。

    :param md_content: 待切分的 Markdown 文本。
    :param file_title: 文件标题；写入每个内容块，全文无标题时也用作块标题。
    :return: 内容块列表。每块包含 file_title、title 和 content；有标题时，
             title 是完整标题路径，content 以该路径开头并附上正文。
    """
    # 1. 初始化结果
    chunks = []

    # 2. 初始化处理过程中需要记住的状态
    """
    变量	                    后面用来做什么	                    为什么需要
    current_title	        记录正文目前属于哪个标题	            遇到新标题时，知道该结算哪一块；None 表示还没遇到标题
    current_content_lines	暂存当前标题下的正文	            等遇到下一个标题，再一次性拼成 chunk
    orphan_lines	        暂存第一个标题之前的内容	            避免这部分内容丢失
    has_flushed_first_chunk	记录标题前的内容是否已并入 chunk	    防止重复并入
    is_code	                记录当前是否在代码块中	            避免把代码里的 # 误判为标题
    heading_stack	        记录各级标题，例如“安装 → Windows”	生成包含上级标题的完整标题路径
    """
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
        if line_strip.startswith(("```","~~~")):
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
            if current_title is not None and len(current_content_lines)>0:
                # ② 首次结算时，将标题前的内容并入当前块，避免重复处理
                if not has_flushed_first_chunk and len(orphan_lines)>0:
                    current_content_lines =  orphan_lines + current_content_lines
                    orphan_lines = []
                    has_flushed_first_chunk = True

                # ③ 用旧标题和正文生成 chunk，保存后清空正文缓存
                full_content = current_title+"\n"+"\n".join(current_content_lines)
                chunks.append({
                    "file_title": file_title,
                    "title": current_title,
                    "content": full_content,
                })
                current_content_lines = []
            # ④ 根据行首 # 的数量计算新标题层级
            heading_level = len(line_strip)-len(line_strip.lstrip("#"))
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
        if len(current_content_lines)>0 or (not has_flushed_first_chunk and len(orphan_lines)>0):
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
    elif len(orphan_lines)>0:
        # 如果全文没有标题，则用文件名作为标题生成 chunk
        chunks.append({
            "file_title": file_title,
            "title": file_title,
            "content": "\n".join(orphan_lines),
        })

    # 6. 返回结果
    return chunks
