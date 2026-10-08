"""
  @Author:LiNing
  @Time:2026/9/23
  @Desc:主体识别节点,进行核心物品的描述
"""
import json
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import StrOutputParser
from pymilvus import MilvusClient, DataType

from common.config.lm_config import lm_config
from common.config.milvus_config import milvus_config
from common.logging.logger import logger, node_log, step_log
from processor.import_processor.state import ImportGraphState
from utils.clients.milvus_utils import get_milvus_client
from utils.escape_milvus_string_utils import escape_milvus_string
from utils.lm.embedding_utils import generate_embeddings
from utils.lm.lm_utils import get_llm_client
from utils.load_prompt import load_prompt
from utils.task_utils import add_running_task, add_done_task

# 主体识别上下文切片数：取前 K 个切片用于 LLM 识别
ITEM_NAME_CONTEXT_CHUNK_K = 5
# 主体识别上下文总字符数上限：防止上下文过长导致大模型输入超限
ITEM_NAME_CONTEXT_TOTAL_MAX_CHARS = 2000


@step_log("step_1_validate_and_get_data")
def step_1_validate_and_get_data(state) -> tuple[list[dict[str, Any]], str]:
    """
    获取文档切片和文件标题，缺少切片时尝试从 JSON 备份中恢复。

    :param state: 导入流程状态，提供 chunks、file_title 和 md_path。
    :return: (chunks, file_title)，依次为文档切片列表和文件标题。

    流程：读取状态并构造 Markdown 路径对象 -> 切片为空时检查原文件及同名 JSON
          -> 从备份恢复切片并写回状态，无法恢复时抛出异常
          -> 标题为空时从文件名推导并写回状态 -> 返回切片和标题。
    """
    # 获取chunks
    chunks = state.get("chunks")
    # 获取file_title
    file_title = state.get("file_title")
    # 获取md_path_obj
    md_path_obj = Path(state.get("md_path"))
    # 判断chunks内容是否存在
    if not chunks:
        # 如果状态中不存在,判断是否存放在对应的磁盘中
        if md_path_obj.is_file():
            json_path_obj = md_path_obj.parent / f"{md_path_obj.stem}.json"
            if json_path_obj.is_file():
                chunks = json.loads(json_path_obj.read_text(encoding="utf-8"))
                state["chunks"] = chunks
                logger.warning("从备份文件中读取chunks")
            else:
                logger.error(f"chunks没有值,同时也没有读取到对应json备份数据,抛出异常!")
                raise ValueError(f"chunks没有值,同时也没有读取到对应json备份数据,抛出异常!")
        else:
            logger.error(f"chunks没有值,同时也没有读取到对应md_path,抛出异常!")
            raise ValueError(f"chunks没有值,同时也没有读取到对应md_path,抛出异常!")
    # 判断file_title是否存在
    if not file_title:
        file_title = md_path_obj.stem or "default_title"
        state["file_title"] = file_title
        logger.warning(f"file_title不存在,给与默认值:{file_title}")

    return chunks, file_title


@step_log("step_2_call_llm_return_item_name")
def step_2_call_llm_return_item_name(chunks, file_title) -> str:
    """
    根据文件标题和前几个文档切片，调用语言模型识别核心物品名称。

    :param chunks: 文档切片列表，使用每个切片的 parent_title 和 content 构造上下文。
    :param file_title: 文件标题，用于构造提示词，并在模型结果为空时作为默认名称。
    :return: 模型识别的物品名称；模型结果为空时返回文件标题。

    流程：获取语言模型客户端 -> 提取前 K 个切片的标题和正文
          -> 按字符数上限截断上下文 -> 加载提示词并构造消息
          -> 调用模型并解析为文本 -> 结果为空时使用文件标题 -> 返回物品名称。
    """
    # 创建模型对象
    vl_model = get_llm_client(lm_config.llm_model)
    # 获取chunks文本内容
    context = ""
    for chunk in chunks[:ITEM_NAME_CONTEXT_CHUNK_K]:
        context += f"标题: {chunk.get('parent_title')} , 内容: {chunk.get('content')} \n"
    # 如果大于2000, 进行截断
    context = context[:ITEM_NAME_CONTEXT_TOTAL_MAX_CHARS]
    # 通过提示词工具类加载提示词
    prompt_text = load_prompt(name="item_name_recognition", file_title=file_title, context=context)
    # 封装成HumanMessage
    message = HumanMessage(
        content=prompt_text
    )
    # 创建调用链
    chains = vl_model | StrOutputParser()

    # 获取模型返回结果
    item_name = chains.invoke([message])
    # 判断是否获取结果
    if not item_name:
        item_name = file_title
        logger.warning(f"没有识别出item_name,使用file_title赋值:{item_name}")

    return item_name


@step_log("step_3_padding_item_name_to_chunks")
def step_3_padding_item_name_to_chunks(chunks, item_name):
    """
    将识别出的物品名称原地写入每个文档切片。

    :param chunks: 待更新的切片列表，列表中的字典会被直接修改。
    :param item_name: 需要写入各切片的物品名称。
    :return: 无返回值。

    流程：遍历切片列表 -> 将每个切片的 item_name 字段设置为识别结果。
    """
    for chunk in chunks:
        chunk["item_name"] = item_name


@step_log("step_4_prepared_item_name_collection")
def step_4_prepared_item_name_collection():
    """
    确保 Milvus 中存在用于存储物品名称及其向量的集合。

    :return: 无返回值；集合已存在时直接结束。

    流程：获取 Milvus 客户端 -> 检查物品名称集合是否存在
          -> 不存在时定义自动主键、文件标题、物品名称及稠密和稀疏向量字段
          -> 配置稠密向量 HNSW 索引与稀疏向量倒排索引 -> 创建集合。
    """
    # 获取milvus数据库连接
    milvus_client = get_milvus_client()
    # 判断是否存在collection,如果存在则返回
    has_collection = milvus_client.has_collection(
        collection_name=milvus_config.item_name_collection
    )
    if has_collection:
        logger.info(f"{milvus_config.item_name_collection}已经存在,可以直接使用!")
        return
    logger.info(f"{milvus_config.item_name_collection}不存在,进行集合的创建!")

    # 创建schema
    schema = MilvusClient.create_schema(
        auto_id=True,
        enable_dynamic_field=True,
    )
    # 通过schema进行表字段的维护
    schema.add_field(field_name="pk", datatype=DataType.INT64, is_primary=True)
    schema.add_field(field_name="file_title", datatype=DataType.VARCHAR, max_length=512)
    schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=512)
    schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=1024)
    schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)

    # 创建索引参数
    index_params = milvus_client.prepare_index_params()
    # 添加索引--稠密向量
    index_params.add_index(
        field_name="dense_vector",
        index_type="HNSW",
        index_name="dense_vector_index",
        metric_type="COSINE",
        params={
            "M": 64,
            "efConstruction": 100
        }
    )
    # 添加索引--稀疏向量
    index_params.add_index(
        field_name="sparse_vector",
        index_type="SPARSE_INVERTED_INDEX",
        index_name="sparse_vector_index",
        metric_type="IP",
        params={"inverted_index_algo": "DAAT_MAXSCORE"},
    )

    # 创建collection
    milvus_client.create_collection(
        collection_name=milvus_config.item_name_collection,
        schema=schema,
        index_params=index_params
    )
    logger.success(f"集合{milvus_config.item_name_collection}创建成功")

@step_log("step_5_insert_item_name_data")
def step_5_insert_item_name_data(item_name, file_title):
    """
    用新的物品名称及其向量替换 Milvus 中同一文件标题对应的记录。

    :param item_name: 识别出的物品名称，用于生成稠密向量和稀疏向量。
    :param file_title: 文件标题，用于删除旧记录并关联新记录。
    :return: 无返回值。

    流程：获取 Milvus 客户端 -> 删除相同文件标题的已有记录
          -> 对物品名称生成稠密和稀疏向量 -> 插入标题、名称及向量数据。
    """
    # 获取milvus数据库连接
    milvus_client = get_milvus_client()

    # 删除已有的数据
    milvus_client.delete(
        collection_name=milvus_config.item_name_collection,
        filter=f"file_title=='{file_title}'"
    )

    # 对item_name进行向量化处理
    result = generate_embeddings([item_name])
    dense_vector = result.get("dense")[0]
    sparse_vector = result.get("sparse")[0]
    # 添加数据
    milvus_client.insert(
        collection_name=milvus_config.item_name_collection,
        data=[
            {
                "file_title": file_title,
                "item_name": item_name,
                "dense_vector": dense_vector,
                "sparse_vector": sparse_vector
            }
        ]
    )
    logger.success(f"向{milvus_config.item_name_collection}插入{item_name}成功")


@node_log("node_item_name_recognition")
def node_item_name_recognition(state: ImportGraphState) -> ImportGraphState:
    """
    识别文档描述的核心物品，将名称写入切片和状态，并存入 Milvus。

    :param state: 导入流程状态，提供任务标识、文档切片、文件标题和 Markdown 路径。
    :return: 已更新 item_name 及各切片 item_name 字段的导入流程状态。

    流程：将节点加入运行列表 -> 获取或恢复切片及文件标题
          -> 调用模型识别物品名称 -> 将名称写入所有切片
          -> 确保 Milvus 集合存在并写入名称及向量
          -> 更新状态 -> 将节点加入已完成列表 -> 返回状态。
    """
    # 1. 将节点加入运行时列表
    add_running_task(state.get("task_id"), "node_item_name_recognition")
    # 2. 获取状态数据并校验
    chunks, file_title = step_1_validate_and_get_data(state)
    # 3. 调取模型获取item_name
    item_name = step_2_call_llm_return_item_name(chunks, file_title)
    # 4. 向状态中的chunks中重新写入item_name
    step_3_padding_item_name_to_chunks(chunks, item_name)
    # 5. 创建milvus对应的collection
    step_4_prepared_item_name_collection()
    # 6. 存储数据
    step_5_insert_item_name_data(item_name,file_title)
    # 7. 更新状态
    state["item_name"] = item_name
    # 8. 将节点加入已完成列表
    add_done_task(state.get("task_id"), "node_item_name_recognition")

    return state

# ===================== 文档切分与商品名称识别联动测试 =====================
def test_node_item_name_recognition(
        md_path: str | Path | None = None,
        file_title: str | None = None,
) -> ImportGraphState:
    """
    联动验证文档切分与物品名称识别，并检查备份、状态和数据库结果。

    :param md_path: 待测试的 Markdown 路径；相对路径以项目根目录为基准，不传时使用已完成图片处理的 HAK 180 手册。
    :param file_title: 可选的文件标题；未提供时使用默认手册标题或输入文件名。
    :return: 通过切片、名称回填和 Milvus 记录检查后的导入流程状态；失败时向外抛出异常。

    流程：确定测试文件并创建状态 -> 检查 Milvus 连接和集合配置
          -> 执行文档切分并核对切片与 JSON 备份 -> 执行物品名称识别
          -> 核对名称和切片回填结果 -> 查询 Milvus 并验证对应记录 -> 返回状态。

    执行时会生成 JSON 备份，调用语言模型和 BGE-M3，并写入 Milvus 物品名称集合。
    """
    from uuid import uuid4

    from processor.import_processor.nodes.node_document_split import node_document_split
    from processor.import_processor.state import create_default_state
    from utils.path_util import PROJECT_ROOT

    logger.info("=== 开始文档切分 → 商品名称识别联动测试 ===")
    try:
        # 1. 使用现有 Markdown，切片由上一个节点实际生成。
        if md_path is None:
            test_md_path = (
                PROJECT_ROOT / "output" / "hak180产品安全手册"
                / "hak180产品安全手册_new.md"
            )
            if file_title is None:
                file_title = "hak180产品安全手册"
        else:
            test_md_path = Path(md_path)
            if not test_md_path.is_absolute():
                test_md_path = PROJECT_ROOT / test_md_path
        test_md_path = test_md_path.resolve()
        if not test_md_path.is_file():
            raise FileNotFoundError(f"联动测试 Markdown 文件不存在：{test_md_path}")

        test_state = create_default_state(
            task_id=f"test_item_name_{uuid4().hex}",
            local_file_path=str(test_md_path),
            local_dir=str(test_md_path.parent),
            md_path=str(test_md_path),
            is_md_read_enabled=True,
            file_title=file_title or test_md_path.stem,
        )
        logger.info(f"测试任务ID：{test_state['task_id']}")
        logger.info(f"测试 Markdown：{test_md_path}")

        # 2. 检查连接；已有集合也需加载，确保后续可以按条件删除旧记录。
        collection_name = milvus_config.item_name_collection
        if not collection_name:
            raise ValueError("联动测试缺少 ITEM_NAME_COLLECTION 配置")
        milvus_client = get_milvus_client()
        if milvus_client is None:
            raise ConnectionError("联动测试无法连接 Milvus，请检查连接日志和 MILVUS_URL")
        if milvus_client.has_collection(collection_name=collection_name):
            milvus_client.load_collection(collection_name=collection_name)

        # 3. 上一个节点：读取 Markdown、切分正文，并生成 JSON 备份。
        logger.info(">> 运行上一个节点：node_document_split")
        split_state = node_document_split(test_state)
        split_chunks = split_state.get("chunks")
        assert isinstance(split_chunks, list) and split_chunks, "文档切分未生成有效切片"
        assert all(
            isinstance(chunk, dict)
            and isinstance(chunk.get("content"), str)
            and chunk["content"].strip()
            for chunk in split_chunks
        ), "文档切分结果包含无效或空白切片"
        split_chunk_count = len(split_chunks)
        backup_path = test_md_path.with_suffix(".json")
        assert backup_path.is_file(), f"文档切分未生成 JSON 备份：{backup_path}"
        assert json.loads(backup_path.read_text(encoding="utf-8")) == split_chunks, \
            "JSON 备份与上一个节点输出的切片不一致"
        logger.info(f"上一个节点生成 {split_chunk_count} 个切片，备份：{backup_path}")

        # 4. 当前节点直接接收上一个节点返回的状态。
        logger.info(">> 运行当前节点：node_item_name_recognition")
        result_state = node_item_name_recognition(split_state)
        item_name = result_state.get("item_name")
        assert isinstance(item_name, str) and item_name.strip(), "识别结果为空或只有空白"
        result_chunks = result_state.get("chunks")
        assert isinstance(result_chunks, list) and len(result_chunks) == split_chunk_count, \
            "识别前后的切片数量不一致"
        assert all(chunk.get("item_name") == item_name for chunk in result_chunks), \
            "部分切片未正确回填商品名称"

        # 5. 按本次文件标题查询，验证该文件写入的商品名称。
        milvus_client.load_collection(collection_name=collection_name)
        safe_title = escape_milvus_string(result_state["file_title"])
        rows = milvus_client.query(
            collection_name=collection_name,
            filter=f'file_title == "{safe_title}"',
            output_fields=["pk", "file_title", "item_name"],
            consistency_level="Strong",
        )
        assert len(rows) == 1, f"预期该文件对应 1 条商品记录，实际查询结果：{rows}"
        assert rows[0].get("item_name") == item_name, \
            f"数据库商品名称与节点状态不一致：{rows}"

        logger.info(f"最终识别商品名称：{item_name!r}")
        logger.info(f"切片数量：{len(result_chunks)}，首个切片名称：{result_chunks[0]['item_name']!r}")
        logger.info(f"Milvus中检索到的数据：{rows}")
        logger.success("=== 文档切分 → 商品名称识别联动测试通过 ===")
        return result_state
    except Exception:
        logger.exception("文档切分 → 商品名称识别联动测试失败")
        raise


# 测试方法运行入口：直接执行该文件即可触发测试
if __name__ == "__main__":
    # 执行本地测试
    test_node_item_name_recognition()
