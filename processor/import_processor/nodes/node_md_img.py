"""
  @Author:LiNing
  @Time:2026/9/23
  @Desc:图片处理,负责md文件当中的图片资源
"""
import re
import base64
import os
from mimetypes import guess_type
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import StrOutputParser
from minio.deleteobjects import DeleteObject

from common.config.lm_config import lm_config
from common.config.minio_config import minio_config
from common.logging.logger import logger, node_log, step_log
from processor.import_processor.state import ImportGraphState
from utils.clients.minio_utils import get_minio_client
from utils.lm.lm_utils import get_llm_client
from utils.load_prompt import load_prompt
from utils.rate_limit_utils import apply_api_rate_limit
from utils.task_utils import add_running_task, add_done_task

# MinIO支持的图片格式集合（小写后缀，统一匹配标准）
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


def is_supported_image(filename: str) -> bool:
    """
    根据文件扩展名判断是否为预设的图片格式，匹配时不区分大小写。

    :param filename: 待检查的文件名，包含扩展名。
    :return: 扩展名在 IMAGE_EXTENSIONS 中返回 True，否则返回 False。

    流程：提取文件扩展名并转换为小写 -> 检查是否属于预设的图片格式集合。
    """
    return os.path.splitext(filename)[1].lower() in IMAGE_EXTENSIONS


@step_log("step_1_validate_and_get_data")
def step_1_validate_and_get_data(state) -> tuple[Path, str, Path]:
    """
    从状态中读取 Markdown 文件，并确定对应的图片目录。

    :param state: 导入流程状态，需包含 md_path；读取的文本会写入 md_content。
    :return: (md_path_obj, md_content, images_dir_obj)，依次为 Markdown 文件路径对象、
            UTF-8 文本内容和同级 images 目录的路径对象。

    流程：读取并检查 md_path -> 确认文件存在 -> 读取文本并更新状态
          -> 拼接同级 images 目录路径 -> 返回文件路径、文本和图片目录路径。
    """
    # 状态中获取md_path
    md_path = state.get("md_path")
    # 判断是否找到md_path
    if not md_path:
        logger.error("md_path变量为空!")
        raise ValueError("md_path变量为空!")
    # 封装成Path对象 md_path -> md_path_obj
    md_path_obj = Path(md_path)
    # 判断对应路径下到文件是否存在
    if not md_path_obj.is_file():
        logger.error(f"{md_path_obj}不存在或者不是一个文件!")
        raise FileNotFoundError(f"{md_path_obj}不存在或者不是一个文件!")
    # 读取文件内容,md_content;[状态保存可选]
    md_content = md_path_obj.read_text(encoding="utf-8")
    state["md_content"] = md_content
    # 获取图片地址路径
    images_dir_obj = md_path_obj.parent / "images"

    return md_path_obj, md_content, images_dir_obj


@step_log("step_2_scan_images")
def step_2_scan_images(md_content, images_dir_obj) -> list[tuple[str, str, tuple[str, str]]]:
    """
    遍历图片目录，收集在 Markdown 中被引用的图片及其前后文。

    :param md_content: 用于查找图片引用和截取上下文的 Markdown 文本。
    :param images_dir_obj: 待遍历的图片目录路径对象。
    :return: 图片信息列表；每项为（图片文件名，图片路径字符串，
            （引用前最多 100 个字符，引用后最多 100 个字符））。

    流程：遍历目录并跳过不支持的格式 -> 在文本中查找图片的首个引用
          -> 跳过未被引用的图片 -> 截取引用前后的文本 -> 汇总并返回图片信息。
    """
    # 1. 初始化图片信息列表
    image_info_list = []
    # 2. 遍历 images_dir_obj 中的图片文件
    for image_file_obj in images_dir_obj.iterdir():
        # 获取图片名
        image_name = image_file_obj.name
        # 获取图片路径
        image_path = str(image_file_obj)
        # 过滤非图文格式
        if not is_supported_image(image_name):
            logger.warning(f"跳过非图片文件：{image_name}")
            continue

        # 3. 使用正则表达式在 md_content 中查找当前图片对应的引用
        rep = re.compile(r"\!\[.*?\]\(.*?" + re.escape(image_name) + r",*?\)")
        search_result = rep.search(md_content)
        if not search_result:
            # 没有匹配到
            logger.warning(f"{image_name}没有被md_content引用,跳过,直接下一次!!")
            continue

        # 4. 提取图片引用附近的前后文，整理并加入 image_info_list
        # 获取匹配内容的起始下标位置
        start = search_result.start()
        # 获取匹配内容的结束下标位置
        end = search_result.end()
        # 获取图片上文信息  起始位置往前100个字符
        pre_content = md_content[max(0, start - 100):start]
        # 获取图片下文信息  结束位置往后100个字符
        post_content = md_content[end:min(len(md_content), end + 100)]
        logger.debug(
            f"{image_name}在md_content被引用,引用的位置:{start}:{end},截取的上文:{pre_content} , 下文:{post_content}")
        # 添加到返回列表中
        image_info_list.append((image_name, image_path, (pre_content, post_content)))
    logger.info(f"所有图片的上下文信息已经识别完毕,数量为:{len(image_info_list)}")

    # 5. 返回图片信息列表
    return image_info_list


@step_log("step_3_image_summary")
def step_3_image_summary(image_info_list, root_folder) -> dict[str, str]:
    """
    结合图片、前后文及文档名称，调用视觉模型生成中文摘要。

    :param image_info_list: step_2_scan_images 的结果，
                每项为（图片文件名，图片路径，（上文，下文））。
    :param root_folder: Markdown 文件名（不含扩展名），作为提示词中的文档名称。
    :return: 以图片文件名为键、模型生成的摘要为值的字典。

    流程：获取视觉模型客户端 -> 遍历图片信息并加载摘要提示词
          -> 读取图片并编码为 Base64，构造图文消息 -> 执行调用限速
          -> 请求模型生成摘要 -> 按图片文件名汇总并返回结果。
    """
    # 1. 初始化图片摘要字典
    image_summary_dict = {}
    # 获取模型客户端对象
    vl_model = get_llm_client(lm_config.vl_model)

    # 2. 遍历 image_info_list，获取每张图片的名称、路径和前后文
    for image_name, image_path, image_context in image_info_list:
        # 3. 读取图片，结合 root_folder 和前后文构造提示词
        # 通过提示词工具类加载提示词
        prompt_text = load_prompt(name="image_summary", root_folder=root_folder, image_content=image_context)
        # 封装成HumanMessage
        image_path_obj = Path(image_path)
        image_data = base64.b64encode(image_path_obj.read_bytes()).decode("utf-8")
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt_text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{guess_type(image_name)[0]};base64,{image_data}"},
                },
            ]
        )
        # 封装调用链
        chains = vl_model | StrOutputParser()
        # 添加范围内限制
        apply_api_rate_limit()
        # 调用获取的结果
        image_summary = chains.invoke([message])
        # 将图片名和摘要放到字典中
        image_summary_dict[image_name] = image_summary
        logger.debug(f"完成:{image_name}的视觉识别,对应的含义:{image_summary}")

    # 5. 以图片名为键保存摘要，并返回摘要字典
    return image_summary_dict


@step_log("step_4_upload_images_get_url")
def step_4_upload_images_get_url(image_info_list, stem) -> dict[str, str]:
    """
    清理当前文档在 MinIO 中的旧图片，上传本地图片并收集访问地址。

    :param image_info_list: 图片信息列表，每项包含图片文件名、本地路径和前后文。
    :param stem: Markdown 文件名（不含扩展名），用于组成 MinIO 中的图片目录。
    :return: 以成功上传的图片文件名为键、HTTP 访问地址为值的字典；上传失败的图片不包含在结果中。

    流程：获取 MinIO 客户端 -> 列出并删除当前文档目录下的旧图片
          -> 遍历图片信息并上传文件 -> 生成访问地址
          -> 跳过上传失败的图片 -> 返回图片地址字典。
    """
    # 获取minio客户端
    minio_client = get_minio_client()
    # 查看对应目录下的图片对象
    objects = minio_client.list_objects(
        bucket_name=minio_config.bucket_name,
        prefix=minio_config.minio_img_dir[1:] + "/" + stem,
        recursive=True,
    )
    delete_object_list = [DeleteObject(obj.object_name) for obj in objects]
    # 删除对应目录下所有图片对象
    errors = minio_client.remove_objects(
        bucket_name=minio_config.bucket_name,
        delete_object_list=delete_object_list
    )
    for error in errors:
        logger.warning(f"删除图片出现问题:{error}")

    # 设置返回结果
    image_url_dict = {}
    # 进行图片遍历,重新上传图片
    for image_name, image_path, _ in image_info_list:
        try:
            minio_client.fput_object(
                bucket_name=minio_config.bucket_name,
                object_name=minio_config.minio_img_dir + "/" + stem + "/" + image_name,
                file_path=image_path,
                content_type=guess_type(image_name)[0],
            )
            image_url = (f"http://{minio_config.endpoint}/{minio_config.bucket_name}"
                         f"{minio_config.minio_img_dir}/{stem}/{image_name}")
            image_url_dict[image_name] = image_url
            logger.debug(f"{image_name}已经完成上传,对应的地址为:{image_url}")
        except Exception as a:
            logger.warning(f"{image_name}上传失败,跳过,继续下一张图片传递!!")

    return image_url_dict

@step_log("step_5_md_content_replace_image")
def step_5_md_content_replace_image(md_content, image_summary_dict, image_url_dict)->str:
    """
    将 Markdown 图片引用中的描述和地址替换为图片摘要与上传后的地址。

    :param md_content: 待替换图片引用的 Markdown 文本。
    :param image_summary_dict: 以图片文件名为键、生成的摘要为值的字典。
    :param image_url_dict: 以图片文件名为键、上传后的访问地址为值的字典。
    :return: 图片描述和地址替换后的 Markdown 文本。

    流程：遍历图片摘要 -> 按图片名查找访问地址
          -> 匹配对应的 Markdown 图片引用并替换描述与地址
          -> 返回更新后的文本。
    """
    # 对字典图片遍历
    for image_name, image_summary in image_summary_dict.items():
        # 获取图片的网络地址
        image_url = image_url_dict.get(image_name)
        # 使用正则表达式替换
        reg = re.compile(r"\!\[.*?\]\(.*?"+re.escape(image_name)+r".*?\)")
        md_content = reg.sub(lambda _: f"![{image_summary}]({image_url})", md_content)
        logger.debug(f"已经完成:{image_name}图片的替换,替换入的描述:{image_summary},替换的地址:{image_url}")
    return md_content

@step_log("step_6_backup_new_md_content")
def step_6_backup_new_md_content(md_content_new, md_path_obj)->Path:
    """
    将更新后的 Markdown 内容保存为原文件同目录下的新文件。

    :param md_content_new: 替换图片信息后的 Markdown 文本。
    :param md_path_obj: 原 Markdown 文件的路径对象。
    :return: 新文件的路径对象，文件名为“原文件名_new.md”。

    流程：根据原文件路径生成带 _new 后缀的文件路径
          -> 将新内容写入该文件 -> 记录保存位置并返回新文件路径。
    """
    # 拼接新的md文档地址
    md_path_new_obj = md_path_obj.with_name(f"{md_path_obj.stem}_new.md")
    # 将md文件写入
    md_path_new_obj.write_text(data=md_content_new,encoding="utf-8")
    logger.info(f"已经将新的md_content内容备份到:{str(md_path_new_obj)}")
    return md_path_new_obj

@node_log("node_md_img")
def node_md_img(state: ImportGraphState) -> ImportGraphState:
    """
    读取 Markdown 文件，并为其中引用的本地图片生成摘要。

    :param state: 导入流程状态，需包含 task_id 和 md_path。
    :return: 写入 md_content 后的导入流程状态；图片摘要目前未写入状态。

    流程：将节点加入运行列表 -> 读取 Markdown 并确定图片目录
          -> 目录为空时直接返回 -> 扫描图片引用及前后文
          -> 调用视觉模型生成摘要 -> 返回状态。
    """
    # 1.将节点添加到运行列表中
    add_running_task(state.get("task_id"), "node_md_img")

    # 2.从状态中获取数据并校验
    md_path_obj, md_content, images_dir_obj = step_1_validate_and_get_data(state)
    if (not images_dir_obj.is_dir()) or len(list(images_dir_obj.iterdir())) == 0:
        logger.info(f"{md_path_obj}对应的md,没有图片内容,无需后续处理,直接跳出!!")
        add_done_task(state.get("task_id"), "node_md_img")
        return state

    # 3.获取图片及上下文信息
    image_info_list = step_2_scan_images(md_content, images_dir_obj)

    # 4.调用视觉模型生成摘要
    image_summary_dict = step_3_image_summary(image_info_list, md_path_obj.stem)

    # 5.将图片上传到minio服务器
    image_url_dict = step_4_upload_images_get_url(image_info_list, md_path_obj.stem)

    # 6.对md文件中图片信息进行替换
    md_content_new = step_5_md_content_replace_image(md_content,image_summary_dict, image_url_dict)

    # 7.对新的md文件进行磁盘持久化保存
    md_path_new_obj = step_6_backup_new_md_content(md_content_new, md_path_obj)

    # 8.更新状态
    state["md_content"] = md_content_new
    state["md_path"]=str(md_path_new_obj)

    # 9.将节点加入已完成列表
    add_done_task(state.get("task_id"), "node_md_img")

    return state


if __name__ == "__main__":
    """本地测试入口：单独运行该文件时，执行MD图片处理全流程测试"""
    from utils.path_util import PROJECT_ROOT

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
