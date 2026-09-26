"""
  @Author:LiNing
  @Time:2026/9/23
  @Desc:PDF转化节点,将pdf转化为md文件
"""
import os
import shutil
import sys
import time
from pathlib import Path

import requests

from common.config.mineru_config import mineru_config
from common.logging.logger import logger, node_log, step_log
from processor.import_processor.state import ImportGraphState, create_default_state
from utils.task_utils import add_running_task, add_done_task
from utils.path_util import PROJECT_ROOT


@step_log("step_1_getdata_validate")
def step_1_getdata_validate(state):
    """
    进行前期判断和校验工作
    :param state:状态
    :return: pdf_path_obj:  pdf文件存放路径对象[文件]
             local_dir_obj: pdf->md文件后存放位置[目录]
            逻辑: 1.通过状态获取pdf_path和local_dir
                 2.判断获取的是否为空[获取的信息]
                 3.将获取的信息转化为path对象并判断是否存在
    """
    # 1.获取相关路径状态信息
    pdf_path = state.get("pdf_path")
    local_dir = state.get("local_dir")

    # 2.判断是否为空
    if not pdf_path:
        logger.error(f"pdf_path的值为空,无法读取文件,直接抛出异常!")
        raise ValueError(f"pdf_path的值为空,无法读取文件!")
    if not local_dir:
        logger.warning(f"没有传入local_dir地址,给与默认值!")
        local_dir = PROJECT_ROOT / "output"
        # 状态更新
        state["local_dir"] = local_dir

    # 3.转化为path对象
    pdf_path_obj = Path(pdf_path)
    local_dir_obj = Path(local_dir)

    # 4.判断文件是否存在
    if not pdf_path_obj.is_file():
        logger.error(f"pdf_path:{pdf_path_obj},不存在或者不是一个文件!")
        raise ValueError(f"pdf_path的值为空,无法读取文件!")
    if not local_dir_obj.is_dir():
        logger.warning(f"local_dir:{local_dir_obj}不存在，或者不是文件夹,我们主动创建!")
        # parents=True  递归创建多层目录 | exist_ok=True 存在也不报错,没有会创建
        local_dir_obj.mkdir(parents=True, exist_ok=True)

    return pdf_path_obj, local_dir_obj


@step_log("step_2_upload_poll")
def step_2_upload_poll(pdf_path_obj):
    """
    通过minerU来将pdf解析并返回zip压缩包地址
    :param pdf_path_obj:
    :return:
            逻辑: 1. 对.env文件中minerU进行相关校验
                 2. 申请文件上传地址
                 3. 上传文件
                 4. 轮询获取结果
    """
    # 1.对.env进行校验
    if (not mineru_config.api_key) or (not mineru_config.base_url):
        logger.error(f"minerU配置错误,请检查minerU配置!")
        raise ValueError("minerU配置错误,请检查minerU配置!")

    # 2.申请上传地址
    token = mineru_config.api_key
    url = f"{mineru_config.base_url}/file-urls/batch"
    header = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    data = {
        "files": [
            {"name": pdf_path_obj.name, "data_id": pdf_path_obj.stem}
        ],
        "model_version": "vlm"
    }
    response = requests.post(url, headers=header, json=data)
    response_status_code = response.status_code
    if response_status_code != 200:
        logger.error(f"申请上传地址失败,返回状态码为:{response_status_code},请检查minerU配置!")
        raise RuntimeError(f"申请上传地址失败,返回状态码为:{response_status_code},请检查minerU配置!")
    # 2.1 获取响应数据
    result = response.json()
    # 2.2 获取响应状态码
    result_code = result.get("code")
    # 2.3 获取响应信息
    result_msg = result.get("msg")
    if result_code != 0:
        logger.error(f"申请地址网络状态成功!但是业务失败!错误码:{result_code},失败信息:{result_msg}")
        raise RuntimeError(
            f"申请地址网络状态成功!但是业务失败!错误码:{result_code},失败信息:{result_msg}")

    # 2.4 获取batch_id
    result_batch_id = result.get("data").get("batch_id")
    # 2.5 获取文件上传地址
    result_urls = result.get("data").get("file_urls")
    if not result_batch_id:
        logger.error(f"没有批量操作标识")
        raise RuntimeError(
            f"没有批量操作标识")
    if not result_urls:
        logger.error(f"没有申请到上传地址")
        raise RuntimeError(
            f"没有申请到上传地址")

    file_upload_url = result_urls[0]
    logger.info(f">>>申请地址成功{file_upload_url}>>>")

    # 3. 上传文件
    pdf_file_data = pdf_path_obj.read_bytes()
    with requests.session() as session:
        # 清空代理头
        session.trust_env = False
        upload_response = session.put(url=file_upload_url, data=pdf_file_data)
        if upload_response.status_code != 200:
            logger.error(f"上传文件失败,返回状态码为:{upload_response.status_code},请检查minerU配置!")
            raise RuntimeError(f"上传文件失败,返回状态码为:{upload_response.status_code},请检查minerU配置!")
    logger.info(f">>>向{file_upload_url}上传{pdf_path_obj}成功>>>")

    # 4. 轮询获取结果
    # 4.1 初始变量&内容定义
    timeout = 600
    interval_time = 3
    start_time = time.time()
    poll_url = f"{mineru_config.base_url}/extract-results/batch/{result_batch_id}/"
    # 4.2 轮询发送请求
    while True:
        """
            结束条件: 超时    获取到zip_url  解析失败
        """
        # 判断是否超时
        if time.time() - start_time > timeout:
            logger.error(f"轮询超时,请检查minerU配置!")
            raise TimeoutError(f"轮询超时,请检查minerU配置!")

        # 发送请求获取结果
        try:
            poll_response = session.get(poll_url, headers=header)
        except Exception as e:
            logger.warning(f"请求出现异常!可以稍后重试!!")
            time.sleep(interval_time)
            continue

        # 获取响应的状态码
        poll_response_status_code = poll_response.status_code
        if poll_response_status_code != 200:
            if 500 <= poll_response_status_code < 600:
                # 服务器报错, 重新尝试
                logger.warning(f"可有修复的网络异常,状态码为:{poll_response_status_code}")
                time.sleep(interval_time)
                continue
            else:
                logger.error(f"不可修复的网络状态异常,状态码为:{poll_response_status_code}")
                raise RuntimeError(f"不可修复的网络状态异常,状态码为:{poll_response_status_code}")

        # 获取响应结果
        poll_response_dict = poll_response.json()
        # 获取业务响应的状态码
        poll_response_dict_code = poll_response_dict.get("code")
        # 获取业务响应的状态信息
        poll_response_dict_msg = poll_response_dict.get("msg")
        if poll_response_dict_code != 0:
            logger.error(f"轮询业务异常,错误码:{poll_response_dict_code},失败信息:{poll_response_dict_msg}")
            raise RuntimeError(f"轮询业务异常,错误码:{poll_response_dict_code},失败信息:{poll_response_dict_msg}")

        extract_result = poll_response_dict.get("data").get("extract_result")[0]
        # 解析状态获取
        extract_result_state = extract_result.get("state")
        if extract_result_state == "done":
            extract_result_url = extract_result.get("full_zip_url")
            if not extract_result_url:
                logger.error(f"完成解析,但是zip地址为空!!")
                raise RuntimeError(f"完成解析,但是zip地址为空!!")
            logger.info(f">>>获取mineru服务器的解析结果：{extract_result_url}>>>")
            return extract_result_url
        elif extract_result_state == "failed":
            logger.error(f"完成解析,但是失败!!失败信息:{extract_result['err_msg']}")
            raise RuntimeError(f"完成解析,但是失败!!失败信息:{extract_result['err_msg']}")
        else:
            logger.warning(f"解析正在进行中,状态:{extract_result_state}!")
            time.sleep(interval_time)
            continue


@step_log("step_3_download_extract")
def step_3_download_extract(zip_url, local_dir_obj, stem):
    """
    解压文件,并重新命名
    :param zip_url: 压缩文件所在地址
    :param local_dir_obj:
    :param stem: pdf 文件名
    :return:
            逻辑: 发送请求,下载压缩文件
                 解压zip文件
                 找到md文件进行重命名
    """
    # 1.发送请求
    response = requests.get(zip_url, timeout=60)
    if response.status_code != 200:
        logger.error(f"从{zip_url}下载文件失败!")
        raise RuntimeError(f"从{zip_url}下载文件失败!")
    # 下载zip文件,保存到指定目录下
    zip_path_obj: Path = local_dir_obj / f"{stem}_result.zip"
    zip_path_obj.write_bytes(response.content)

    # 2.解压
    # 指定解压路径
    extract_dir_obj = local_dir_obj / stem
    # 判断目录是否存在,如果存在则删除
    if extract_dir_obj.is_dir():
        shutil.rmtree(extract_dir_obj)
    # 创建目录
    extract_dir_obj.mkdir(parents=True, exist_ok=True)
    # 进行解压: param1:压缩文件 param2:解压目标位置
    shutil.unpack_archive(zip_path_obj, extract_dir_obj)

    # 3.寻找md文件并重命名
    # 判断md文件是否存在
    md_file_list = list(extract_dir_obj.glob("*.md"))
    if not md_file_list:
        logger.error(f"文件解压失败,在:{extract_dir_obj}没有任何md文件!")
        raise RuntimeError(f"文件解压失败,在:{extract_dir_obj}没有任何md文件!")
    # 找到对应的解析结果: 1.和pdf同名   2.full.md   3.列表第一个
    # 查找和pdf同名
    for md_file_obj in md_file_list:
        if md_file_obj.stem == stem:
            logger.info(f"文件{md_file_obj}解压成功")
            return md_file_obj

    target_file_obj = None # 判断是否需要改名
    # 查找full.md
    for md_file_obj in md_file_list:
        if md_file_obj.name.lower() == "full.md":
            target_file_obj = md_file_obj
            logger.info(f"文件解压成功,但是名字是full.md,后续需要重命名")
            break
    # 以上两种情况都不满足
    if not target_file_obj:
        target_file_obj = md_file_list[0]
    # 修改名字
    final_md_file_obj = target_file_obj.rename(target_file_obj.with_name(f"{stem}.md"))

    logger.info(f"文件{zip_path_obj}解压成功")

    return final_md_file_obj

@node_log("node_pdf_to_md")
def node_pdf_to_md(state: ImportGraphState) -> ImportGraphState:
    """
    节点: PDF转Markdown (node_pdf_to_md)
    :param state:
    :return: state
        流程: 节点进入流程列表 -> 状态当中获取并校验 -> 上传文件并获取结果 -
                -> 下载zip文件并解压0 ->更新状态[ md_path ] -
                -> 节点完成[加载到完成列表] -> 返回状态
    """
    # 1. 节点加入到运行列表
    add_running_task(state.get("task_id"), "node_pdf_to_md")

    # 2. 获取状态数据并校验
    pdf_path_obj, local_dir_obj = step_1_getdata_validate(state)

    # 3. 上传文件&轮番获取结果
    zip_url = step_2_upload_poll(pdf_path_obj)

    # 4. 下载并解压
    md_path = step_3_download_extract(zip_url, local_dir_obj, pdf_path_obj.stem)

    # 5. 更新 md_path 路径状态
    state["md_path"] = md_path

    # 6. 节点加入已完成列表
    add_done_task(state.get("task_id"), "node_pdf_to_md")

    return state


# 测试
if __name__ == "__main__":
    # 单元测试：验证PDF转MD全流程
    logger.info("===== 开始node_pdf_to_md节点单元测试 =====")

    logger.info(f"测试获取根地址：{PROJECT_ROOT}")

    test_pdf_name = os.path.join("doc", "hak180产品安全手册.pdf")
    test_pdf_path = os.path.join(PROJECT_ROOT, test_pdf_name)

    # 构造测试状态
    test_state = create_default_state(
        task_id="test_pdf2md_task_001",
        pdf_path=test_pdf_path,
        local_dir=os.path.join(PROJECT_ROOT, "output")
    )

    node_pdf_to_md(test_state)

    logger.info("===== 结束node_pdf_to_md节点单元测试 =====")
