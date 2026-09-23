"""
  @Author:LiNing
  @Time:2026/9/23
  @Desc:流程:
        文档输入->pdf(转化为md)|md文件->图片处理->文档切分-
            ->主题识别->向量转化->数据库存入
"""
import json

from langgraph.constants import START,END
from langgraph.graph import StateGraph

from processor.import_processor.nodes.node_bge_embedding import node_bge_embedding
from processor.import_processor.nodes.node_document_split import node_document_split
from processor.import_processor.nodes.node_entry import node_entry
from processor.import_processor.nodes.node_import_milvus import node_import_milvus
from processor.import_processor.nodes.node_item_name_recognition import node_item_name_recognition
from processor.import_processor.nodes.node_md_img import node_md_img
from processor.import_processor.nodes.node_pdf_to_md import node_pdf_to_md
from processor.import_processor.state import ImportGraphState, create_default_state
from common.logging.logger import logger


# 创建StateGraph图对象
workflow = StateGraph(ImportGraphState)

# 节点的注册
workflow.add_node("node_entry",node_entry)
workflow.add_node("node_pdf_to_md",node_pdf_to_md)
workflow.add_node("node_md_img",node_md_img)
workflow.add_node("node_document_split",node_document_split)
workflow.add_node("node_item_name_recognition",node_item_name_recognition)
workflow.add_node("node_bge_embedding",node_bge_embedding)
workflow.add_node("node_import_milvus",node_import_milvus)

# 边的添加: 按照文本输入流程进行
# 初始边
workflow.add_edge(START,"node_entry")

# 路由函数
def after_node_entry(state:ImportGraphState):
    """
    :param state:
    :return:
        PDF: 文件为pdf类型,返回 node_pdf_to_md 节点
        markdown: 文件为md类型,返回 node_md_img 节点
        其他: 返回 END 节点
    """
    if state.get("is_pdf_read_enabled"):
        return "node_pdf_to_md"
    elif state.get("is_md_read_enabled"):
        return "node_md_img"
    else:
        return END

# 条件边
workflow.add_conditional_edges(
    "node_entry", # 判断节点
    after_node_entry, # 路由函数
    # path_map: # 1.映射路由函数,通过函数返回值和节点进行匹配(如果一致可以省略)
                # 2.打印图结构,必须加path_map
    path_map={
        "node_pdf_to_md" : "node_pdf_to_md",
        "node_md_img": "node_md_img",
        END: END
    }
)

workflow.add_edge("node_pdf_to_md","node_md_img")
workflow.add_edge("node_md_img","node_document_split")
workflow.add_edge("node_document_split","node_item_name_recognition")
workflow.add_edge("node_item_name_recognition","node_bge_embedding")
workflow.add_edge("node_bge_embedding","node_import_milvus")
workflow.add_edge("node_import_milvus",END)

# 编译
kb_import_app = workflow.compile()

# 测试
if __name__ == "__main__":
    logger.info("===== 开始测试 =====")

    initial_state = create_default_state(local_file_path="万用表RS-12的使用.pdf")
    final_state = None

    # 只输出更最终的状态值（字典形式），不包含节点名称、执行日志、元数据等额外信息
    # for event in kb_import_app.stream(initial_state):
    #     for key, value in event.items():
    #         logger.info(f"节点: {key}")
    #         final_state = value

    kb_import_app.invoke(initial_state)
    # 格式化输出最终状态
    logger.info(f"最终状态: {json.dumps(final_state, indent=4, ensure_ascii=False)}")

    logger.info("图结构:")
    # uv add grandalf
    kb_import_app.get_graph().print_ascii()

    logger.info("===== 测试结束 =====")

