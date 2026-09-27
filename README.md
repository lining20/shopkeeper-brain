# shopkeeper-brain

面向店铺商品资料的知识库处理项目，目标是将 PDF、Markdown 文档处理为可检索的向量数据，并通过 API 支持商品信息查询与问答。

> 项目处于开发阶段。当前已搭建文档导入流程骨架，实现文件类型判断和通过 MinerU 将 PDF 转为 Markdown；图片处理、文档切分、商品识别、向量化及入库节点尚未实现业务逻辑。暂不具备完整的知识库导入与问答能力。

## 当前开发状态

以下状态依据仓库代码整理。“已实现”表示存在具体代码，不代表已经完成实际环境验证或正式发布。

### 已实现功能

| 功能 | 当前实现范围 |
| --- | --- |
| 导入流程编排 | 使用 LangGraph 定义状态、注册节点，并按 PDF / Markdown 类型分流 |
| 文件入口判断 | 检查输入路径是否为空，识别 `.pdf`、`.md` 后缀，提取文件标题 |
| PDF 转 Markdown | 调用 MinerU API 申请上传地址、上传文件、轮询解析结果、下载并解压 ZIP、定位和重命名 Markdown 文件 |
| 日志 | 使用 Loguru 输出控制台与文件日志，记录节点和步骤的耗时及异常 |
| 任务追踪工具 | 在进程内存中记录任务状态、运行节点、完成节点和结果 |
| SSE 工具 | 提供会话队列、事件封装和异步生成器，尚未接入 HTTP 路由 |
| 模型调用工具 | 封装 ChatOpenAI 客户端、BGE-M3 稠密及稀疏向量生成、Reranker 模型加载与 token 计数 |
| 存储访问工具 | 提供 Milvus 连接与混合检索、MinIO 客户端和存储桶初始化、MongoDB 对话历史读写工具 |

模型与存储工具尚未接入完整的导入、检索或问答业务流程。

### 开发中功能

文档导入流程正在搭建。以下节点已注册到 LangGraph，但函数体目前仅返回原状态；具体目标来自节点中的“未来要实现”说明。

| 节点 | 待实现内容 |
| --- | --- |
| `node_md_img` | 扫描图片链接、上传 MinIO、替换链接，可选生成图片描述 |
| `node_document_split` | 按 Markdown 标题层级切分，对长段落二次切分，并保留标题路径等元数据 |
| `node_item_name_recognition` | 调用 LLM 识别商品名称，并写入 `item_name` |
| `node_bge_embedding` | 为切片生成 Dense / Sparse 向量，整理入库数据 |
| `node_import_milvus` | 连接 Milvus、按商品名称清理旧数据、批量插入新数据 |

Markdown 输入目前只完成路径识别与分流，尚未实现正文读取。

### 计划功能

原 README 提出了通过 API 提供问答和商品信息查询的目标。目前：

- `api/` 只有空的 `__init__.py`，尚无应用实例或路由。
- `processor/query_processor/` 只有空的 `__init__.py`，尚无查询流程。
- 已有回答生成、问题改写、商品识别、HyDE 等提示词模板，但未形成可调用的完整问答功能。

具体开发优先级、里程碑和交付时间：**待补充**。

## 文档导入流程

以下为代码中已连接的流程；“待实现”节点目前不会处理数据。

```text
文件输入
  └─ 入口判断（已实现）
       ├─ PDF → MinerU 转 Markdown（已实现）
       ├─ Markdown → 设置文件路径（尚未读取正文）
       └─ 空路径或不支持的类型 → 结束

PDF / Markdown 分支
  → 图片处理（待实现）
  → 文档切分（待实现）
  → 商品名称识别（待实现）
  → BGE-M3 向量化（待实现）
  → Milvus 入库（待实现）
```

流程执行结束不等于已经完成向量入库。

## 技术栈

依赖声明见 `pyproject.toml`，锁定版本见 `uv.lock`。

| 类别 | 技术与用途 |
| --- | --- |
| 语言与依赖管理 | Python `>=3.12,<3.14`、uv |
| 工作流 | LangGraph |
| 大模型调用 | LangChain、langchain-openai；示例配置使用阿里云 DashScope 兼容接口 |
| PDF 解析 | 当前节点使用 Requests 调用 MinerU 远程 API |
| 向量模型 | BGE-M3、pymilvus.model |
| 重排序模型工具 | FlagEmbedding、BGE Reranker |
| 模型下载 | ModelScope |
| 向量数据库 | Milvus / PyMilvus |
| 对象存储 | MinIO |
| 对话历史存储 | MongoDB / PyMongo |
| Web 相关依赖 | FastAPI、Uvicorn；尚无服务启动入口 |
| 配置与日志 | python-dotenv、Loguru |
| 深度学习运行时 | PyTorch `2.6.0`、torchvision `0.21.0`、torchaudio `2.6.0` |

PyTorch 系列依赖配置了 CUDA 12.6 专用下载源。Embedding 和 Reranker 的运行设备由环境变量控制，示例配置使用 CPU。

## 目录结构

```text
shopkeeper-brain/
├─ api/                         API 预留目录，尚无路由
├─ common/
│  ├─ config/                   MinerU、模型、Milvus、MinIO、MCP 等配置
│  ├─ logging/                  日志初始化与节点、步骤装饰器
│  └─ prompt/                   商品识别、图片描述、问答等提示词模板
├─ processor/
│  ├─ import_processor/
│  │  ├─ main_graph.py          文档导入 LangGraph 编排
│  │  ├─ state.py               导入状态定义与初始化
│  │  └─ nodes/                 导入节点，部分为占位实现
│  └─ query_processor/          查询流程预留目录
├─ utils/
│  ├─ clients/                  Milvus、MinIO、MongoDB 工具
│  ├─ download_model/           ModelScope 模型下载脚本
│  ├─ lm/                       LLM、Embedding、Reranker 工具
│  ├─ task_utils.py             内存任务追踪
│  ├─ sse_utils.py              SSE 会话队列与事件生成
│  └─ path_util.py              项目根目录定位
├─ doc/                         示例 PDF
├─ test/
│  └─ test_torch_cuda.py        PyTorch CUDA 检查脚本
├─ output/                      PDF 解析输出目录，运行时生成
├─ logs/                        日志目录，启用文件日志时生成
├─ .env.example                 环境变量示例
├─ .gitignore                   包含 .env、.venv、output 等忽略规则
├─ pyproject.toml               项目元数据、依赖与 uv 配置
├─ uv.lock                      依赖锁文件
└─ README.md
```

## 环境准备

### 基础要求

- Python 3.12 或 3.13。
- 已安装 uv。
- 依赖安装时能够访问配置的软件源。
- PDF 解析需要可用的 MinerU API Token 及网络连接。

`pyproject.toml` 的 uv 配置将 Windows AMD64 列为必须满足依赖解析的环境，模型下载脚本也使用 Windows 路径。其他平台的安装与运行情况：**待补充**。

如需运行模型或存储工具，还需按模块准备模型文件及 Milvus、MinIO、MongoDB 服务。当前 PDF 转 Markdown 示例不需要这些存储服务或本地模型。

### 安装依赖

在项目根目录执行：

```powershell
uv sync --frozen
```

该命令使用现有 `uv.lock` 安装依赖。项目配置的默认 Python 软件源为清华镜像，PyTorch 系列使用独立的 CUDA 12.6 下载源。

### 配置环境变量

首次使用且根目录尚无 `.env` 时执行：

```powershell
Copy-Item .env.example .env
```

随后按实际环境编辑 `.env`。示例中的服务地址、凭据和模型路径需要自行替换。

项目通过 `python-dotenv` 加载配置。路径工具默认向上查找 `.env` 来定位项目根目录，也支持预先设置 `PROJECT_ROOT` 环境变量。

| 配置用途 | 环境变量 | 当前使用情况 |
| --- | --- | --- |
| PDF 解析 | `MINERU_API_TOKEN`、`MINERU_BASE_URL` | PDF 转 Markdown 节点使用 |
| 文本及视觉模型 | `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`LLM_DEFAULT_MODEL`、`VL_MODEL`、`LLM_DEFAULT_TEMPERATURE` | 模型工具及配置使用，尚未接入导入节点 |
| Embedding | `BGE_M3_PATH`、`BGE_M3`、`BGE_DEVICE`、`BGE_FP16` | 向量工具相关配置 |
| Reranker | `BGE_RERANKER_LARGE`、`BGE_RERANKER_DEVICE`、`BGE_RERANKER_FP16` | 模型加载及 token 计数工具使用 |
| Milvus | `MILVUS_URL`、`CHUNKS_COLLECTION`、`ITEM_NAME_COLLECTION`、`ENTITY_NAME_COLLECTION` | 客户端及集合名称配置；实体集合为预留项 |
| MinIO | `MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`、`MINIO_BUCKET_NAME`、`MINIO_IMG_DIR`、`MINIO_SECURE` | 对象存储相关配置，图片节点尚未接入 |
| MongoDB | `MONGO_URL`、`MONGO_DB_NAME` | 对话历史工具使用 |
| MCP | `MCP_DASHSCOPE_BASE_URL` | 已有配置，尚无搜索业务流程 |
| 日志 | `LOG_CONSOLE_ENABLE`、`LOG_CONSOLE_LEVEL`、`LOG_FILE_ENABLE`、`LOG_FILE_LEVEL`、`LOG_FILE_RETENTION` | 控制日志输出及保留时间 |

配置细节：

- CPU 模式可使用 `BGE_DEVICE=cpu`、`BGE_FP16=0`；Reranker 对应设置为 `BGE_RERANKER_DEVICE=cpu`、`BGE_RERANKER_FP16=0`。
- `MINIO_ENDPOINT` 使用 `主机:端口` 格式，是否启用 HTTPS 由 `MINIO_SECURE` 控制；当前代码仅在值为 `True` 时启用。
- `LLM_DEFAULT_TEMPERATURE` 需要填写可转换为浮点数的值。
- 当前 Embedding 工具优先使用 `BGE_M3_PATH`，为空时使用代码中的 `BAAI/bge-m3`；虽然配置类读取了 `BGE_M3`，该值目前未参与模型选择。

## 运行与使用示例

以下命令均从项目根目录执行。当前提供的是开发脚本和 Python 调用方式，尚无统一 CLI 或 HTTP 服务入口。

### PDF 转 Markdown 示例

完成 MinerU 配置后执行：

```powershell
uv run --frozen python -m processor.import_processor.nodes.node_pdf_to_md
```

该模块中的示例使用：

```text
输入：doc/hak180产品安全手册.pdf
输出目录：output/
```

执行过程会将 PDF 上传至 MinerU，下载解析结果 ZIP，并将内容解压到以 PDF 文件名命名的子目录。

默认输出结构：

```text
output/
├─ hak180产品安全手册_result.zip
└─ hak180产品安全手册/
   ├─ hak180产品安全手册.md
   └─ 其他解析产物
```

重复处理同名 PDF 时，代码会删除并重新创建对应的解压子目录。不要在该生成目录中保存需要保留的手工修改。

### 在 Python 中调用导入流程

安装依赖、准备 `.env` 后，可在项目环境中调用现有接口：

```python
from processor.import_processor.main_graph import kb_import_app
from processor.import_processor.state import create_default_state
from utils.path_util import PROJECT_ROOT

initial_state = create_default_state(
    task_id="demo_pdf_import",
    local_file_path=str(PROJECT_ROOT / "doc" / "万用表RS-12的使用.pdf"),
    local_dir=str(PROJECT_ROOT / "output"),
)

final_state = kb_import_app.invoke(initial_state)
print(final_state.get("md_path"))
```

对于 PDF，该示例会执行转换节点，再经过后续占位节点；不会生成文档切片、向量或 Milvus 入库记录。

`main_graph.py` 自带的 `__main__` 示例目前仅传入 PDF 文件名，未指向 `doc/`，且没有将 `invoke()` 返回值赋给 `final_state`。从项目根目录直接运行该模块前，需要修正示例路径和结果接收方式。

### 下载本地模型

仓库提供以下脚本：

```powershell
uv run --frozen python -m utils.download_model.download_bgem3
uv run --frozen python -m utils.download_model.download_reranker
```

脚本分别下载 `BAAI/bge-m3` 和 `BAAI/bge-reranker-large`。

目前下载目录直接写在脚本中：

- BGE-M3：`D:/ai_models/modelscope_cache/models`
- Reranker：`D:\ai_models\modelscope_cache\models\rerank`

运行前按实际环境调整脚本中的缓存目录，下载后将实际模型目录填入 `.env` 的 `BGE_M3_PATH` 或 `BGE_RERANKER_LARGE`。仅修改 `.env` 不会改变下载脚本的缓存目录。

这些模型不是当前 PDF 转 Markdown 示例的前置条件。

## 检查与测试

### CUDA 检查

```powershell
uv run --frozen python test/test_torch_cuda.py
```

脚本会输出 PyTorch 和 CUDA 信息，并在 GPU 上执行矩阵乘法检查。无法访问 NVIDIA GPU 时返回非零退出码；该检查不用于判断 CPU 模式是否可用。

### 入口节点检查

```powershell
uv run --frozen python -m processor.import_processor.nodes.node_entry
```

该模块内置空路径、不支持格式、Markdown 和 PDF 的调用示例，结果通过日志观察，未使用断言构成自动化测试。

PDF 转 Markdown 模块内置示例属于真实外部服务调用，需要有效配置，会上传文件并写入输出目录。

目前仓库未提供统一测试框架配置或完整业务回归测试。以上命令依据现有文件整理，实际执行结果与验证环境：**待补充**。

## 已知限制

- 图片处理至 Milvus 入库的五个节点均为占位实现，完整导入链路尚未完成。
- Markdown 分支尚未读取正文；PDF 转换节点只更新 Markdown 文件路径，没有填充 `md_content`。
- 入口仅识别小写 `.pdf`、`.md` 后缀，且不检查文件是否存在；PDF 文件存在性检查在转换节点执行。
- 任务与 SSE 队列保存在进程内存中，进程重启后不会保留，也没有多进程共享实现。
- 当前未提供 Milvus 集合与索引初始化脚本，检索工具依赖外部已准备好的集合结构。
- MinIO 工具创建新存储桶时会设置匿名读取对象的策略，实际使用前需确认该行为符合资料访问要求。
- 尚无 FastAPI 应用入口、查询流程或可运行的前端页面。
- 仓库未提供 Docker、Compose、CI 或生产部署配置；服务版本要求与部署步骤待补充。

## 文档维护

后续开发时，建议随代码变更同步更新本 README：

- 节点完成业务逻辑后，更新功能状态和流程说明，并注明是否已完成实际验证。
- 增加入口、参数或脚本时，同步更新运行命令与使用示例。
- 修改依赖或环境变量时，同步检查 `pyproject.toml`、`uv.lock`、`.env.example` 与本文。
- 计划功能注明对应设计文档、TODO 或需求依据；没有明确依据的内容保留为“待补充”。
- 补充实际验证环境、执行命令及结果，避免将代码存在等同于功能已验证。

## 许可证

当前仓库未发现许可证文件。许可证及使用授权范围：**待补充**。
