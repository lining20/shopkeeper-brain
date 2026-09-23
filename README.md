# shopkeeper-brain

面向店铺商品资料的知识库处理服务。项目将 PDF 或 Markdown 文档处理为可检索的向量数据，并计划通过 API 为问答与商品信息查询提供支持。

## 文档导入流程

```text
文件输入 → PDF 转 Markdown / Markdown 读取 → 图片处理 → 文档切分
→ 商品主题识别 → BGE-M3 向量化 → Milvus 入库
```

## 目录说明

```text
api/                         API 接口层
common/
  config/                    大模型、Embedding、Milvus、MinIO 等配置
  logging/                   日志工具
  prompt/                    提示词模板
processor/
  import_processor/          文档导入 LangGraph 流程及各处理节点
  query_processor/           检索与问答处理流程
utils/
  clients/                   Milvus、MinIO、MongoDB 客户端
  download_model/            本地模型下载脚本
  lm/                        大模型、Embedding、Reranker 调用工具
doc/                         示例文档
test/                        测试脚本
pyproject.toml               项目依赖与 uv 配置
uv.lock                      锁定后的依赖版本
```

## 环境准备

项目使用 Python 3.12 或 3.13，并由 uv 管理依赖：

```powershell
uv sync --frozen
```

项目已配置 PyTorch CUDA 12.6。可检查 GPU 是否可用：

```powershell
uv run --frozen python test/test_torch_cuda.py
```
