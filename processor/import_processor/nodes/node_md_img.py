"""
  @Author:LiNing
  @Time:2026/9/23
  @Desc:图片处理,负责md文件当中的图片资源
"""
import base64
import mimetypes
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

from langchain_core.messages import HumanMessage

from common.config.lm_config import lm_config
from common.config.minio_config import minio_config
from common.logging.logger import logger, node_log, step_log
from processor.import_processor.state import ImportGraphState
from utils.clients.minio_utils import get_minio_client
from utils.lm.lm_utils import get_llm_client
from utils.load_prompt import load_prompt
from utils.path_util import PROJECT_ROOT
from utils.task_utils import add_running_task, add_done_task


@step_log("step_1_getdata_validate")
def step_1_getdata_validate(state: ImportGraphState):
    """
    获取和校验Markdown文件参数，定位图片目录并读取原始内容
    :param state: 包含 md_path 的状态，路径支持字符串或Path对象
    :return: md_path_obj: Markdown文件路径对象[文件]
             image_path_obj: Markdown同级images目录的路径对象[目录]
             md_content: Markdown原始文本内容
        逻辑: 1.从状态中获取md_path并进行非空校验
              2.转化为Path对象并判断是否为文件
              3.定位并校验images目录，目录不存在时保留路径供后续判断
              4.以UTF-8读取文件，返回两个路径对象和原始内容
    """
    # 1. 获取Markdown文件路径并进行非空校验
    md_path = state.get("md_path")
    if not md_path:
        logger.error("md_path的值为空,无法读取Markdown文件!")
        raise ValueError("md_path的值为空,无法读取Markdown文件!")

    # 2. 转化为Path对象并校验文件是否存在
    md_path_obj = Path(md_path)
    if not md_path_obj.is_file():
        logger.error(f"md_path:{md_path_obj},不存在或者不是一个文件!")
        raise ValueError(f"md_path:{md_path_obj},不存在或者不是一个文件!")

    # 3. 获取图片目录路径；没有图片目录时，后续步骤返回空列表
    image_path_obj = md_path_obj.parent / "images"
    if image_path_obj.exists() and not image_path_obj.is_dir():
        logger.error(f"图片路径:{image_path_obj},不是一个文件夹!")
        raise ValueError(f"图片路径:{image_path_obj},不是一个文件夹!")

    # 4. 读取原始内容，读取或解码失败时由step_log记录异常并继续抛出
    md_content = md_path_obj.read_text(encoding="utf-8")

    return md_path_obj, image_path_obj, md_content


@step_log("step_2_get_image_info")
def step_2_get_image_info(
    md_path_obj: Path, image_path_obj: Path, md_content: str
) -> list[tuple[str, str, tuple[str, str]]]:
    """
    遍历images文件夹，在Markdown中对照图片并获取上下文
    :param md_path_obj: Markdown文件路径对象，images文件夹位于同级目录
    :param image_path_obj: 第一步返回的images目录路径对象
    :param md_content: Markdown原始文本内容
    :return: image_info_list: 按图片文件名排序的列表，每项为:
             (图片文件名, 图片本地绝对路径字符串, (图片前100字符, 图片后100字符))
        逻辑: 1.使用第一步返回的images目录路径对象
              2.遍历文件夹中的图片，与Markdown内联图片路径对照
              3.匹配成功后截取前后各100字符，不足时取实际内容
              4.未被引用的图片跳过并记录日志，无图片时返回空列表
        说明: 仅遍历images直属图片，不读取图片内容；同图多次引用保留各自上下文。
    """
    image_info_list = []
    md_dir_obj = md_path_obj.parent
    # 1. 使用第一步返回的图片目录；没有图片目录时无需处理
    if not image_path_obj.exists():
        logger.info(f"图片目录:{image_path_obj},不存在,无需处理图片!")
        return image_info_list

    # 2. 记录代码位置并准备Markdown匹配结果，仅用于与目录中的文件对照
    code_ranges = [
        (match.start(), match.end())
        for match in re.finditer(r"```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\r\n]*`", md_content)
    ]

    # 匹配 ![说明](路径)，兼容尖括号路径和可选的图片标题
    image_pattern = re.compile(
        r'!\[[^\]\r\n]*\]\(\s*'
        r'(?:<(?P<angle_path>[^<>\r\n]+)>|(?P<path>(?:[^\s()]|\([^()\r\n]*\))+))'
        r'''(?:[ \t]+(?:"[^"\r\n]*"|'[^'\r\n]*'|\([^()\r\n]*\)))?\s*\)'''
    )
    image_matches = list(image_pattern.finditer(md_content))
    image_suffixes = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg"}

    # 3. 以images目录内的实际图片为准，逐张到Markdown中对照
    for image_file_obj in sorted(image_path_obj.iterdir()):
        if not image_file_obj.is_file() or image_file_obj.suffix.lower() not in image_suffixes:
            continue
        image_file_path_obj = image_file_obj.resolve()
        matched = False
        for match in image_matches:
            if any(start <= match.start() < end for start, end in code_ranges):
                continue
            # 被反斜杠转义的图片标记不是实际图片
            prefix = md_content[:match.start()]
            if (len(prefix) - len(prefix.rstrip("\\"))) % 2:
                continue

            image_path = match.group("angle_path") or match.group("path")
            # 排除网络链接、data等URI；Windows盘符路径仍属于本地路径
            is_windows_path = re.match(r"^[A-Za-z]:[\\/]", image_path)
            if image_path.startswith("//") or (
                re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", image_path) and not is_windows_path
            ):
                continue

            # 对照完整路径，避免其他目录中的同名图片被错误匹配
            referenced_path_obj = Path(image_path)
            if not referenced_path_obj.is_absolute():
                referenced_path_obj = md_dir_obj / referenced_path_obj
            if referenced_path_obj.resolve() != image_file_path_obj:
                continue

            # 4. 从完整图片标记的两侧各取100个字符，保留空白和换行
            matched = True
            before_content = md_content[max(0, match.start() - 100):match.start()]
            after_content = md_content[match.end():match.end() + 100]
            image_info_list.append((
                image_file_obj.name,
                str(image_file_path_obj),
                (before_content, after_content),
            ))

        if not matched:
            logger.warning(f"图片:{image_file_obj.name},未在Markdown中找到引用,跳过处理!")

    return image_info_list


@step_log("step_3_summarize_images")
def step_3_summarize_images(
    image_info_list: list[tuple[str, str, tuple[str, str]]], root_folder: str
) -> dict[str, str]:
    """
    调用视觉模型，为每张图片生成中文总结
    :param image_info_list: 第二步返回的(图片名, 图片路径, (上文, 下文))列表
    :param root_folder: Markdown文件名，用于渲染图片总结提示词
    :return: image_summary_map: {图片名: 总结内容}
        逻辑: 1.校验视觉模型配置并获取现有模型客户端
              2.读取图片并转成带MIME类型的base64地址
              3.结合图片上下文渲染提示词并调用视觉模型
              4.校验模型响应，保存每张图片的总结
        说明: 同一图片名只调用一次模型，使用首次出现的上下文。
    """
    # 1. 校验视觉模型配置，避免工具函数回退到普通文本模型
    if not lm_config.vl_model:
        logger.error("未配置VL_MODEL,无法生成图片总结!")
        raise ValueError("未配置VL_MODEL,无法生成图片总结!")
    vl_client = get_llm_client(model=lm_config.vl_model)

    image_summary_map = {}
    for image_name, image_path, image_content in image_info_list:
        if image_name in image_summary_map:
            continue

        # 2. 读取本地图片，按MIME类型编码为base64数据
        image_mime_type, _ = mimetypes.guess_type(image_path)
        if not image_mime_type or not image_mime_type.startswith("image/"):
            continue
        image_data = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")

        # 3. 按LangChain官方图片内容块格式，连同上下文发送给视觉模型
        prompt = load_prompt(
            "image_summary", root_folder=root_folder, image_content=image_content
        )
        message = HumanMessage(content=[
            {"type": "text", "text": prompt},
            {"type": "image", "base64": image_data, "mime_type": image_mime_type},
        ])
        response = vl_client.invoke([message])

        # 4. 校验总结，返回图片名到总结内容的映射
        summary = response.content
        if not isinstance(summary, str) or not summary.strip():
            raise RuntimeError(f"图片:{image_name},视觉模型未返回有效的总结内容!")
        image_summary_map[image_name] = summary.strip()
        logger.info(f"图片:{image_name},视觉模型总结完成!")

    return image_summary_map


@step_log("step_4_upload_images")
def step_4_upload_images(
    image_info_list: list[tuple[str, str, tuple[str, str]]]
) -> dict[str, str]:
    """
    将本地图片上传到MinIO并返回图片网络地址
    :param image_info_list: 第二步返回的(图片名, 图片路径, (上文, 下文))列表
    :return: image_url_map: {图片名: 网络地址}
        逻辑: 1.校验MinIO配置并获取现有客户端
              2.遍历图片，为支持的图片类型确定MIME和对象名
              3.上传本地文件，拼接并返回可访问的图片地址
        说明: 同一图片名只上传一次；不支持的文件类型直接跳过。
    """
    # 1. 校验对象存储配置，避免上传后无法生成地址
    image_dir = (minio_config.minio_img_dir or "").strip("/")
    if not all((
        minio_config.endpoint,
        minio_config.access_key,
        minio_config.secret_key,
        minio_config.bucket_name,
        image_dir,
    )):
        logger.error("MinIO配置不完整,无法上传图片!")
        raise ValueError("MinIO配置不完整,无法上传图片!")
    client = get_minio_client()
    image_url_map = {}
    scheme = "https" if minio_config.minio_secure else "http"

    # 2. 按图片名上传，同图多次引用时只上传一次
    for image_name, image_path, _ in image_info_list:
        if image_name in image_url_map:
            continue
        image_mime_type, _ = mimetypes.guess_type(image_path)
        if not image_mime_type or not image_mime_type.startswith("image/"):
            continue
        object_name = f"{image_dir}/{image_name}"

        # 3. 上传成功后生成网络地址，失败时由step_log记录并抛出异常
        client.fput_object(
            minio_config.bucket_name,
            object_name,
            image_path,
            content_type=image_mime_type,
        )
        image_url_map[image_name] = (
            f"{scheme}://{minio_config.endpoint}/"
            f"{quote(minio_config.bucket_name, safe='')}/{quote(object_name, safe='/')}"
        )
        logger.info(f"图片:{image_name},上传MinIO成功!")

    return image_url_map


@step_log("step_5_replace_images")
def step_5_replace_images(
    md_path_obj: Path,
    md_content: str,
    image_info_list: list[tuple[str, str, tuple[str, str]]],
    image_summary_map: dict[str, str],
    image_url_map: dict[str, str],
) -> str:
    """
    将Markdown中已处理的本地图片替换为带总结的MinIO图片链接
    :param md_path_obj: Markdown文件路径对象，用于解析原图片的相对路径
    :param md_content: 原始Markdown内容
    :param image_info_list: 第二步返回的图片信息列表
    :param image_summary_map: 第三步返回的{图片名: 总结内容}
    :param image_url_map: 第四步返回的{图片名: 网络地址}
    :return: md_content_new: 替换后的Markdown内容
        逻辑: 1.根据图片信息建立本地路径与图片名的对应关系
              2.扫描Markdown图片标记，排除代码示例和网络图片
              3.匹配本地路径且总结和URL齐全时，替换为![总结](MinIO地址)
              4.保留其余原文，返回新的Markdown内容
    """
    # 1. 只允许替换第二步确认过的本地图片
    image_names_by_path = {
        Path(image_path).resolve(): image_name
        for image_name, image_path, _ in image_info_list
    }

    # 2. 使用与第二步一致的图片语法，跳过代码中的图片示例
    code_ranges = [
        (match.start(), match.end())
        for match in re.finditer(r"```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\r\n]*`", md_content)
    ]
    image_pattern = re.compile(
        r'!\[[^\]\r\n]*\]\(\s*'
        r'(?:<(?P<angle_path>[^<>\r\n]+)>|(?P<path>(?:[^\s()]|\([^()\r\n]*\))+))'
        r'''(?:[ \t]+(?:"[^"\r\n]*"|'[^'\r\n]*'|\([^()\r\n]*\)))?\s*\)'''
    )

    md_parts = []
    last_pos = 0
    replace_count = 0
    for match in image_pattern.finditer(md_content):
        if any(start <= match.start() < end for start, end in code_ranges):
            continue
        prefix = md_content[:match.start()]
        if (len(prefix) - len(prefix.rstrip("\\"))) % 2:
            continue

        image_path = match.group("angle_path") or match.group("path")
        is_windows_path = re.match(r"^[A-Za-z]:[\\/]", image_path)
        if image_path.startswith("//") or (
            re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", image_path) and not is_windows_path
        ):
            continue

        # 3. 用完整路径对照图片；映射不完整时保留原图片标记
        referenced_path_obj = Path(image_path)
        if not referenced_path_obj.is_absolute():
            referenced_path_obj = md_path_obj.parent / referenced_path_obj
        image_name = image_names_by_path.get(referenced_path_obj.resolve())
        summary = image_summary_map.get(image_name) if image_name else None
        image_url = image_url_map.get(image_name) if image_name else None
        if not summary or not image_url:
            continue

        # 转义Markdown说明文字中的特殊字符，避免破坏图片语法
        alt_text = summary.replace("\r", " ").replace("\n", " ")
        alt_text = alt_text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
        md_parts.append(md_content[last_pos:match.start()])
        md_parts.append(f"![{alt_text}]({image_url})")
        last_pos = match.end()
        replace_count += 1

    # 4. 拼接未修改的部分，第六步负责将新内容保存到独立文件
    md_parts.append(md_content[last_pos:])
    md_content_new = "".join(md_parts)
    logger.info(f"Markdown图片替换完成,共替换:{replace_count}处!")
    return md_content_new


@step_log("step_6_backup_markdown")
def step_6_backup_markdown(md_path_obj: Path, md_content_new: str) -> Path:
    """
    将替换后的Markdown内容保存到同目录的新文件，保留原文件用于对比

    :param md_path_obj: 原始Markdown文件路径对象
    :param md_content_new: 第五步返回的替换后内容
    :return: backup_path_obj: 新Markdown文件路径对象，供后续节点重新读取

        逻辑: 1.按原文件名生成带_img后缀的备份路径

              2.路径已存在时递增编号，避免覆盖已有文件

              3.以UTF-8写入新内容并返回实际保存路径
    """
    index = 1
    while True:
        suffix = "_img" if index == 1 else f"_img_{index}"
        backup_path_obj = md_path_obj.with_name(f"{md_path_obj.stem}{suffix}{md_path_obj.suffix}")
        try:
            # 独占创建：即使检查后出现同名文件，也不会覆盖已有内容
            with backup_path_obj.open("x", encoding="utf-8", newline="") as backup_file:
                backup_file.write(md_content_new)
            break
        except FileExistsError:
            index += 1

    logger.info(f"Markdown新内容已保存:{backup_path_obj}!")
    return backup_path_obj


@node_log("node_md_img")
def node_md_img(state: ImportGraphState) -> ImportGraphState:
    """
    节点: 图片处理 (node_md_img)
    :param state: 包含 task_id、md_path 的状态
    :return: 更新 md_path 和 md_content 后的 state
        流程: 节点进入运行列表 -> 获取和校验参数 -> 获取图片信息和上下文 -
                -> 无需处理图片时保留原文并返回 -
                -> 调用视觉模型生成总结 -> 上传图片到MinIO -> 替换图片内容 -
                -> 将新内容保存到磁盘备份 -> 更新状态[ md_path、md_content ] -
                -> 节点完成[加载到完成列表] -> 返回状态
        说明: 原始Markdown保留，md_path指向新文件以便后续重新读取。
    """
    # 节点加入到运行列表
    add_running_task(state.get("task_id"), "node_md_img")

    # 1. 获取和校验参数，返回Markdown路径对象、图片目录路径对象和原始内容
    md_path_obj, image_path_obj, md_content = step_1_getdata_validate(state)

    # 2. 获取图片信息和上下文，返回(图片名, 图片地址字符串, (上文, 下文))列表
    image_info_list = step_2_get_image_info(md_path_obj, image_path_obj, md_content)

    # 没有需要处理的图片时，保留原文供后续节点使用，跳过图片处理流程
    if not image_info_list:
        logger.info(f"Markdown文件:{md_path_obj},没有匹配到需处理的图片,跳过后续图片处理步骤!")
        state["md_content"] = md_content
        add_done_task(state.get("task_id"), "node_md_img")
        return state

    # 3. 调用视觉模型，返回 {图片名: 总结内容}
    image_summary_map = step_3_summarize_images(image_info_list, md_path_obj.stem)

    # 4. 将图片上传到MinIO，返回 {图片名: 网络地址}
    image_url_map = step_4_upload_images(image_info_list)

    # 5. 根据图片信息、总结和网络地址替换原文中的图片，返回新的Markdown内容
    md_content_new = step_5_replace_images(
        md_path_obj, md_content, image_info_list, image_summary_map, image_url_map
    )

    # 6. 将新内容保存到磁盘备份，用于新旧对比和后续内容丢失时重新读取
    backup_path_obj = step_6_backup_markdown(md_path_obj, md_content_new)

    # 更新Markdown路径和内容状态
    state["md_path"] = str(backup_path_obj)
    state["md_content"] = md_content_new

    # 节点加入已完成列表
    add_done_task(state.get("task_id"), "node_md_img")

    return state

if __name__ == "__main__":
    """本地测试入口：单独运行该文件时，执行MD图片处理全流程测试"""
    logger.info(f"本地测试 - 项目根目录：{PROJECT_ROOT}")

    # 测试MD文件路径（需手动将测试文件放入对应目录）
    test_md_name = os.path.join(r"output\hak180产品安全手册", "hak180产品安全手册.md")
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
            "md_content": ""
        }
        logger.info("开始本地测试 - MD图片处理全流程")
        # 执行核心处理流程
        result_state = node_md_img(test_state)
        logger.info(f"本地测试完成 - 处理结果状态：{result_state}")
