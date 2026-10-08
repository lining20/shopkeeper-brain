# shopkeeper-brain

面向店铺商品资料的知识库处理项目，目标是将 PDF、Markdown 文档处理为可检索的向量数据，并通过 API 支持商品信息查询与问答。

> 项目处于开发阶段。当前已搭建文档导入流程骨架，实现文件类型判断、通过 MinerU 将 PDF 转为 Markdown，以及正文读取、图片处理、文档切分和 JSON 保存。商品名称识别节点已编写名称识别、切片回填、商品名称集合初始化和名称向量入库流程；文档切片的向量化及入库节点尚未实现业务逻辑。暂不具备完整的知识库导入与问答能力。

## 当前开发状态

以下状态依据仓库代码整理。“已实现”表示存在具体代码，不代表已经完成实际环境验证或正式发布。

最近核对日期：2026-10-08。入口、PDF 转换、图片处理、文档切分和商品名称识别五个节点已有主要处理流程，具体步骤见“主要状态节点说明”；实际验证结果待补充。

### 已实现功能

| 功能 | 当前实现范围 |
| --- | --- |
| 导入流程编排 | 使用 LangGraph 定义状态、注册节点，并按 PDF / Markdown 类型分流 |
| 文件入口判断 | 检查输入路径是否为空，识别 `.pdf`、`.md` 后缀，提取文件标题 |
| PDF 转 Markdown | 调用 MinerU API 申请上传地址、上传文件、轮询解析结果、下载并解压 ZIP、定位和重命名 Markdown 文件 |
| Markdown 正文读取 | 检查 `md_path` 指向的文件，以 UTF-8 读取正文并写入状态的 `md_content` |
| 本地图片引用扫描 | 遍历 Markdown 同级 `images/` 目录，按支持的图片后缀过滤，查找每张图片的首个 Markdown 引用并截取前后各最多 100 个字符 |
| 图片摘要生成 | 将本地图片编码为 Base64，结合文档名、前后文和 `image_summary.prompt` 调用视觉模型，生成按图片文件名索引的摘要字典 |
| 图片上传与正文替换 | 尝试清理 MinIO 中当前文档前缀下的旧图片，上传被 Markdown 引用的本地图片；将匹配到的图片描述和地址替换为模型摘要及生成的访问地址 |
| 新 Markdown 文件保存 | 在原文件同目录写入 `<原文件名>_new.md`，并更新状态中的 `md_path`、`md_content`；正常返回时将图片节点登记为已完成 |
| 文档切分与 JSON 保存 | 按标题切分、长块递归细分及短块合并，写入同目录 JSON 和状态的 `chunks`；已修正合并时的尾块遗漏和字符串路径检查问题 |
| 商品名称识别与回填 | 结合文件标题及前最多 5 个切片、最多 2000 字符的上下文调用 LLM；结果为空时回退到文件标题，将名称写入状态和各切片的 `item_name` |
| 商品名称向量入库 | 为名称生成 Dense / Sparse 向量，确保商品名称集合存在，按 `file_title` 删除旧记录并插入新记录；不写入文档切片向量 |
| 日志 | 使用 Loguru 输出控制台与文件日志，记录节点和步骤的耗时及异常 |
| 任务追踪工具 | 在进程内存中记录任务状态、运行节点、完成节点和结果 |
| SSE 工具 | 提供会话队列、事件封装和异步生成器，尚未接入 HTTP 路由 |
| 模型调用工具 | 封装 ChatOpenAI 客户端、BGE-M3 稠密及稀疏向量生成、Reranker 模型加载与 token 计数 |
| 存储访问工具 | 提供 Milvus 连接与混合检索、MinIO 客户端和存储桶初始化、MongoDB 对话历史读写工具 |

视觉模型客户端、调用限速工具和 MinIO 客户端已接入图片处理节点；文本模型、BGE-M3 及 Milvus 客户端已接入商品名称识别节点。文档切片向量化、切片入库及查询问答流程尚未完成。

### 开发中功能

文档导入流程正在搭建。五个主要节点已有具体处理流程；文档切片向量化和 Milvus 切片入库节点目前仅返回原状态，下列待办依据这两个节点中的说明整理。

| 节点 | 待实现内容 |
| --- | --- |
| `node_bge_embedding` | 为切片生成 Dense / Sparse 向量，整理入库数据 |
| `node_import_milvus` | 连接 Milvus、按商品名称清理旧数据、批量插入新数据 |

PDF 转换结果与直接输入的 Markdown 均进入 `node_md_img` 读取正文。Markdown 同级没有 `images/` 目录或该目录为空时，节点登记完成并直接返回，不生成 `_new.md` 文件。

### 计划功能

原 README 提出了通过 API 提供问答和商品信息查询的目标。目前：

- `api/` 只有空的 `__init__.py`，尚无应用实例或路由。
- `processor/query_processor/` 只有空的 `__init__.py`，尚无查询流程。
- 已有回答生成、问题改写、商品识别、HyDE 等提示词模板，但未形成可调用的完整问答功能。

具体开发优先级、里程碑和交付时间：**待补充**。

## 文档导入流程

以下为代码中已连接的流程。商品名称向量写入独立的名称集合，文档切片向量化及切片入库尚未实现。

```text
文件输入
  └─ 入口判断（已实现）
       ├─ PDF → MinerU 转 Markdown（已实现）
       ├─ Markdown → 设置文件路径
       └─ 空路径或不支持的类型 → 结束

PDF / Markdown 分支
  → 读取 Markdown 正文（已实现）
  → 扫描本地图片引用、生成视觉摘要（已实现；无图片目录或目录为空时跳过）
  → 尝试清理旧图片、上传 MinIO、替换图片引用并保存新文件（已编写实现）
  → 文档切分、JSON 保存与 chunks 状态更新（已编写实现）
  → 商品名称识别、切片回填与名称向量入库（已编写实现）
  → 文档切片 BGE-M3 向量化（待实现）
  → Milvus 文档切片入库（待实现）
```

流程执行结束不等于已经完成文档切片向量入库；目前商品名称节点会单独写入名称及其向量。

## 主要状态节点说明

本节只介绍已有具体主流程的五个 LangGraph 状态节点。它们接收并返回 `ImportGraphState`；`step_*` 是节点内部的处理函数，不是独立注册的状态节点。以下按实际执行顺序说明，代码存在不等于已经完成业务验证。

```text
node_entry
  ├─ PDF → node_pdf_to_md ─┐
  ├─ Markdown ────────────┴→ node_md_img → node_document_split → node_item_name_recognition
  └─ 空路径或不支持类型 → END（使用默认初始状态时）
```

### 1. `node_entry`：文件入口节点

**作用：** 根据输入路径判断文件类型，设置流程分支标志、文件路径及标题，为后续节点准备状态。

**输入与输出：** 读取 `task_id`、`local_file_path`，更新 `is_pdf_read_enabled`、`is_md_read_enabled`、`pdf_path`、`md_path` 和 `file_title`。

**主流程骨架：**

```text
登记运行 → 获取 local_file_path → 非空判断 → 按后缀设置分支与路径
→ 提取 file_title → 登记完成 → 返回状态
```

**主要 step 流程：** 此节点没有拆分独立的 `step_*` 函数，步骤直接写在 `node_entry()` 中。

| 步骤 | 具体处理 |
| --- | --- |
| 1. 登记运行 | 使用 task_id 将 node_entry 加入运行列表 |
| 2. 获取与检查路径 | 读取 local_file_path；为空时记录警告并返回原状态 |
| 3. 判断 Markdown | 小写 .md 后缀启用 Markdown 标志，关闭 PDF 标志；设置 md_path，并将 pdf_path 置为 None |
| 4. 判断 PDF | 小写 .pdf 后缀启用 PDF 标志，关闭 Markdown 标志；设置 pdf_path，并将 md_path 置为 None |
| 5. 标题与完成登记 | 对支持的类型使用 Path(local_file_path).stem 设置 file_title，然后登记完成并返回；其他类型记录警告并提前返回 |

节点只按后缀分类，文件存在性由后续节点检查。空路径和不支持类型的分支不会登记完成；使用默认初始状态时，两个类型标志均为 `False`，图中的路由函数选择 `END`。

### 2. `node_pdf_to_md`：PDF 解析节点

**作用：** 上传 PDF 至 MinerU，取得解析产物并定位 Markdown 文件，为图片处理节点提供文件路径。

**输入与输出：** 读取 `task_id`、`pdf_path`、`local_dir`；必要时设置默认 `local_dir`，成功后将最终 Markdown 的 `Path` 对象写入 `md_path`。此节点不读取正文。

**主流程骨架：**

```text
登记运行
→ step_1_getdata_validate
→ step_2_upload_poll
→ step_3_download_extract
→ 更新 md_path → 登记完成 → 返回状态
```

**主要 step 流程：**

| step 函数 | 具体处理 | 结果 |
| --- | --- | --- |
| `step_1_getdata_validate` | 校验 pdf_path 非空且是现有文件；local_dir 为空时使用 PROJECT_ROOT / output 并写回状态，输出目录不存在时创建 | PDF 路径对象与输出目录对象 |
| `step_2_upload_poll` | 检查 MinerU Token 和基础地址；申请上传 URL，上传 PDF，使用批次 ID 轮询解析结果。轮询等待间隔为 3 秒，超时阈值为 600 秒 | 解析结果 ZIP 地址 |
| `step_3_download_extract` | 下载 ZIP，删除并重建同名解压目录；在解压目录顶层查找 .md 文件，优先 PDF 同名文件，其次 full.md，最后取第一个文件，必要时重命名 | 最终 Markdown 路径对象 |

默认本地产物为 `output/<PDF文件名>_result.zip` 和 `output/<PDF文件名>/` 下的解析内容。缺少配置、解析失败或轮询超时等情况会抛出异常；同名解压目录会被重新创建。

### 3. `node_md_img`：Markdown 图片处理节点

**作用：** 读取 Markdown，识别其中引用的本地图片，生成图片摘要并上传 MinIO，再保存替换图片引用后的新 Markdown。

**输入与输出：** 读取 `task_id`、`md_path`。正常处理图片后，`md_content` 更新为替换后的正文，`md_path` 更新为同目录 `<原文件名>_new.md` 的路径字符串；没有图片目录或目录为空时，保留原路径及读取到的正文。

**主流程骨架：**

```text
登记运行 → step_1_validate_and_get_data
  ├─ images/ 不存在或为空 → 登记完成 → 返回状态
  └─ images/ 非空
       → step_2_scan_images
       → step_3_image_summary
       → step_4_upload_images_get_url
       → step_5_md_content_replace_image
       → step_6_backup_new_md_content
       → 更新 md_content、md_path → 登记完成 → 返回状态
```

**主要 step 流程：**

| step 函数 | 具体处理 | 结果 |
| --- | --- | --- |
| `step_1_validate_and_get_data` | 校验 md_path 指向现有文件，以 UTF-8 读取正文并写入 md_content，确定同级 images/ 目录 | 文件路径、正文和图片目录 |
| `step_2_scan_images` | 遍历目录直接子项，过滤支持的图片后缀；寻找每张图片的首个 Markdown 引用，截取前后各最多 100 个字符，跳过未引用图片 | 图片名、本地路径、上下文列表 |
| `step_3_image_summary` | 加载 image_summary.prompt，将图片编码为 Base64；结合文档名、上下文调用视觉模型，每次调用前执行限速 | 按图片名索引的摘要字典 |
| `step_4_upload_images_get_url` | 获取 MinIO 客户端，按文档前缀尝试清理旧对象；上传图片并生成访问地址，单张上传失败时记录警告并继续 | 成功上传图片的 URL 字典 |
| `step_5_md_content_replace_image` | 根据图片名匹配 Markdown 引用，用摘要替换图片描述，用上传地址替换图片路径 | 更新后的正文 |
| `step_6_backup_new_md_content` | 以 UTF-8 将新正文写入原文件同目录的 <原文件名>_new.md | 新 Markdown 路径对象 |

图片摘要和 URL 字典是内部中间数据，处理结果通过新正文及文件传递。非空目录中没有匹配图片时仍会初始化模型客户端、尝试清理 MinIO 并保存新文件；上传与替换的已知限制见下文。

### 4. `node_document_split`：文档切分节点

**作用：** 将 Markdown 按标题层级初次切分，再按长度细分及尝试合并短块，补充来源信息并保存 JSON，供后续商品识别和向量化使用。

**输入与输出：** 读取 `task_id`、`md_content`、`md_path` 和 `file_title`；结果写入 `state["chunks"]`，并保存到 Markdown 同目录的 `<Markdown文件名>.json`。切片字段包括 `file_title`、`parent_title`、`part`、`title`、`content`。

**主流程骨架：**

```text
登记运行
→ step_1_validate_get_data
→ step_2_split_document_by_title
→ step_3_refine_split_and_merge_chunks
→ step_4_backup_chunks_json
→ 更新 chunks → 登记完成 → 返回状态
```

**主要 step 流程：**

| step 函数 | 具体处理 | 结果 |
| --- | --- | --- |
| `step_1_validate_get_data` | 读取正文、路径与文件标题；正文为空时尝试从文件读取，标题为空时从文件名推导，统一换行符 | 正文、文件标题及 Markdown 路径 |
| `step_2_split_document_by_title` | 逐行识别 1～6 级 Markdown 标题，维护标题路径；代码围栏内不识别标题，将标题前正文并入首个内容块，全文无标题时用文件标题 | 包含 file_title、title、content 的初次切片列表 |
| `step_3_refine_split_and_merge_chunks` | 超过 600 字符的块调用 _split_chunk_content 递归细分，补充 parent_title、part 等字段；随后调用 _merge_chunk_content，尝试合并同父标题下的相邻短块，合并时去除后块的父标题前缀 | 精细切片列表 |
| `step_4_backup_chunks_json` | 将结果序列化为保留中文、带缩进的 JSON，以 UTF-8 写入 Markdown 同目录 | 同名 .json 文件 |

当前长度参数在节点文件中定义：目标长度 `CHUNK_SIZE=600`、重叠长度 `CHUNK_OVERLAP=50`、短块阈值 `CHUNK_MIN=400`、合并长度检查值 `CHUNK_MAX_SIZE=1000`，单位均为字符。递归切分会扣除标题前缀长度来计算正文目标长度；合并在当前块不超过 400 字符、父标题一致且当前内容与去除父标题前缀后的下一块正文长度之和不超过 1000 时尝试。

### 5. `node_item_name_recognition`：商品名称识别节点

**作用：** 根据文件标题和文档切片识别核心商品名称，将名称回填到切片和状态，并把商品名称及其向量写入 Milvus 的商品名称集合。

**输入与输出：** 读取 `task_id`、`chunks`、`file_title`、`md_path`。`md_path` 需要提供，即使状态中已有切片，节点也会先将其转换为 Path。成功后更新 `state["item_name"]`，并原地更新各切片的 `item_name` 字段；数据库中按文件标题保存名称和名称向量。节点不会生成文档切片向量，也不会重写切片 JSON 备份。

**主流程骨架：**

```text
登记运行
→ step_1_validate_and_get_data
→ step_2_call_llm_return_item_name
→ step_3_padding_item_name_to_chunks
→ step_4_prepared_item_name_collection
→ step_5_insert_item_name_data
→ 更新 item_name → 登记完成 → 返回状态
```

**主要 step 流程：**

| step 函数 | 具体处理 | 结果 |
| --- | --- | --- |
| `step_1_validate_and_get_data` | 获取 chunks 和 file_title；切片为空时，检查 Markdown 文件及同目录同名 .json，从 JSON 恢复切片并写回状态；标题为空时从 Markdown 文件名推导 | 切片列表和文件标题；无法找到恢复文件时抛出异常 |
| `step_2_call_llm_return_item_name` | 从前最多 5 个切片提取 parent_title 和 content，将上下文截断到最多 2000 字符；加载 item_name_recognition.prompt，调用 LLM_DEFAULT_MODEL 对应的文本模型并解析文本，结果为空时使用 file_title | 商品名称字符串 |
| `step_3_padding_item_name_to_chunks` | 遍历切片列表，将 item_name 写入每个切片字典 | 原地更新后的切片 |
| `step_4_prepared_item_name_collection` | 获取 Milvus 客户端；ITEM_NAME_COLLECTION 已存在时直接复用，不存在时创建字段及稠密、稀疏向量索引 | 商品名称集合 |
| `step_5_insert_item_name_data` | 按 file_title 删除旧记录；调用 generate_embeddings([item_name]) 生成名称的稠密、稀疏向量，再插入新记录 | 包含文件标题、名称和名称向量的记录 |

识别上下文参数在节点文件中定义：`ITEM_NAME_CONTEXT_CHUNK_K=5`、`ITEM_NAME_CONTEXT_TOTAL_MAX_CHARS=2000`。提示词要求输出商品名称与型号，无法识别时返回空字符串；节点对空结果使用文件标题作为默认名称。

商品名称集合由 `ITEM_NAME_COLLECTION` 指定，创建时定义以下字段：

| 字段 | 定义 |
| --- | --- |
| `pk` | INT64 自动生成主键 |
| `file_title` | VARCHAR，最大长度 512 |
| `item_name` | VARCHAR，最大长度 512 |
| `dense_vector` | 1024 维 FLOAT_VECTOR；HNSW 索引，COSINE 度量，M=64、efConstruction=100 |
| `sparse_vector` | SPARSE_FLOAT_VECTOR；SPARSE_INVERTED_INDEX 索引，IP 度量，算法 DAAT_MAXSCORE |

同一 `file_title` 对应的旧记录会先被删除，再进行名称向量生成和插入。运行此节点需要文本模型、BGE-M3 和 Milvus 配置；具体限制见下文。

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

图片处理节点使用远程视觉模型及 MinIO，需配置 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`VL_MODEL`、`LLM_DEFAULT_TEMPERATURE`，以及 MinIO 端点、凭据、桶名和图片目录。完整导入图已引用该节点，导入模块时会读取模型配置；进入图片摘要步骤时会初始化模型客户端。没有 `images/` 目录或目录为空时，图片节点只读取正文，不调用视觉模型或 MinIO。

商品名称识别节点需要可调用的文本模型（`LLM_DEFAULT_MODEL`）、BGE-M3 模型及运行设备配置，以及 `MILVUS_URL`、`ITEM_NAME_COLLECTION`。这一节点已接入导入图，因此执行完整导入流程也需要准备这些依赖；商品名称集合不存在时由节点创建。

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
| 文本及视觉模型 | `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`LLM_DEFAULT_MODEL`、`VL_MODEL`、`LLM_DEFAULT_TEMPERATURE` | 文本模型用于商品名称识别；视觉模型用于图片摘要 |
| Embedding | `BGE_M3_PATH`、`BGE_M3`、`BGE_DEVICE`、`BGE_FP16` | 商品名称向量生成及向量工具相关配置 |
| Reranker | `BGE_RERANKER_LARGE`、`BGE_RERANKER_DEVICE`、`BGE_RERANKER_FP16` | 模型加载及 token 计数工具使用 |
| Milvus | `MILVUS_URL`、`CHUNKS_COLLECTION`、`ITEM_NAME_COLLECTION`、`ENTITY_NAME_COLLECTION` | 商品名称节点使用名称集合；文档切片入库未实现，实体集合为预留项 |
| MinIO | `MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`、`MINIO_BUCKET_NAME`、`MINIO_IMG_DIR`、`MINIO_SECURE` | 图片处理节点清理旧对象、上传图片并生成访问地址时使用 |
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

### Markdown 图片处理示例

先准备 Markdown 文件、需要处理的同级 `images/` 目录，并完成视觉模型及 MinIO 配置。内置示例读取以下路径，可使用前述 PDF 解析产物：

```text
output/
└─ hak180产品安全手册/
   ├─ hak180产品安全手册.md
   └─ images/
```

执行：

```powershell
uv run --frozen python -m processor.import_processor.nodes.node_md_img
```

当前行为：

- 读取 Markdown 正文并更新 `md_content`。
- 扫描同级 `images/` 目录的直接子项，支持 `.jpg`、`.jpeg`、`.png`、`.gif`、`.bmp`、`.webp`，后缀匹配不区分大小写。
- 对正则匹配到引用的图片，结合上下文调用视觉模型生成摘要。请求会发送图片内容及相关文本，并使用限速工具的默认参数：每 60 秒最多 3000 次调用记录；该值是代码配置，不代表模型服务额度。
- 在 MinIO 中尝试列出并删除以当前文档名称为前缀的旧图片对象，再上传被 Markdown 引用的本地图片。随后将匹配到的 Markdown 图片引用替换为摘要和访问地址。
- 将处理后的正文写入原文件同目录的 `<原文件名>_new.md`，并将返回状态的 `md_path` 指向新文件，`md_content` 更新为新正文。原 Markdown 文件不被此步骤覆盖。

没有同级 `images/` 目录或该目录为空时，节点直接返回原文件路径和正文，也不会创建 `_new.md`。目录中有文件、但没有图片被 Markdown 引用时，代码仍会进入视觉模型客户端初始化、MinIO 旧对象清理和新文件写入步骤。

该示例会访问外部服务，并尝试删除 MinIO 中当前文档前缀下的旧对象。当前代码先删除后上传；单张图片上传失败时会记录警告并继续，但替换步骤仍可能把对应图片地址写成 `None`。运行前应使用可重建的图片数据。

### 在 Python 中调用导入流程

安装依赖、准备 MinerU、文本及视觉模型、MinIO、BGE-M3 和 Milvus 配置后，可在项目环境中调用现有接口。图片节点会根据解析结果是否包含同级 `images/` 目录决定是否处理图片：

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

对于 PDF，该示例会执行转换和正文读取；存在非空图片目录时，还会尝试摘要生成、MinIO 上传及新文件保存，再进入文档切分，写入 JSON 和 `chunks`，然后识别商品名称、回填状态并写入 Milvus 商品名称集合。没有图片目录或目录为空时，图片节点保留原路径及正文，后续仍进入切分和名称识别。最后两个占位节点不会生成文档切片向量或切片入库记录。

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

Markdown 图片处理模块内置示例依赖实际文件和外部服务配置；存在非空图片目录时会初始化远程视觉模型客户端、清理 MinIO 旧图片并写入新文件。当前没有针对该节点的自动化断言测试。本次文档更新仅依据代码检查，未执行这些外部服务调用。

### 文档切分与商品名称识别联动检查

准备文本模型、BGE-M3、Milvus 配置及以下 Markdown 文件：

```text
output/hak180产品安全手册/hak180产品安全手册_new.md
```

执行模块中已有的联动测试入口：

```powershell
uv run --frozen python -m processor.import_processor.nodes.node_item_name_recognition
```

入口调用 `test_node_item_name_recognition()`，先执行文档切分，再执行名称识别，使用断言检查切片非空、JSON 备份一致性、名称回填和 Milvus 中对应文件标题的记录。也可以在 Python 中调用该函数并传入 `md_path`、`file_title`；相对路径以项目根目录为基准。

该检查会写入切片 JSON、调用文本模型及 BGE-M3，并删除、重新插入当前文件标题对应的商品名称记录。它不调用图片处理节点。本次文档更新未运行该检查，实际结果待补充。

目前仓库未提供统一测试框架配置或完整业务回归测试。以上命令依据现有文件整理，实际执行结果与验证环境：**待补充**。

## 已知限制

- 五个主要节点已有具体处理流程，商品名称节点还提供了联动检查入口；实际执行结果未在本 README 中确认。文档切片向量化及切片入库节点仍为占位实现，完整导入链路尚未完成。
- 标题切分会跳过空行（包括代码块内空行），且没有检查代码围栏的开闭类型是否一致。
- 商品名称节点原地更新切片的 item_name，但不重写 JSON 备份，因此名称识别后的状态与切分阶段备份可能不同。恢复 JSON 时未进行切片结构或非空检查，模型结果也只对空值回退，没有清理空白或验证名称格式。
- 商品名称记录按 file_title 替换，同名文件会使用相同替换条件；删除过滤表达式直接拼接标题，带引号的标题可能导致过滤失败。代码先删除旧记录再生成向量、插入新记录，后续步骤失败时没有恢复旧数据。
- 图片节点仅扫描 Markdown 同级 `images/` 目录的直接子项，并为每张图片提取首个匹配引用的上下文；未实现任意图片路径或远程图片获取。
- MinIO 上传前会按前缀尝试删除旧对象。示例 `MINIO_IMG_DIR` 以 `/` 开头，但列举旧对象时会去掉开头的 `/`，上传对象名却保留它；因此旧对象清理可能无法匹配刚上传的图片。同前缀的其他文档对象也可能被纳入清理范围。上传失败会跳过该图片，但 Markdown 替换仍可能写入 `None` 地址。当前生成的访问 URL 固定以 `http://` 开头，与 `MINIO_SECURE=True` 配置不一致。
- `_new.md` 使用固定文件名，重复处理同一原文件会覆盖之前生成的 `_new.md`。对已生成的 `_new.md` 再运行，会继续生成带 `_new` 后缀的文件。
- 入口仅识别小写 `.pdf`、`.md` 后缀，且不检查文件是否存在；PDF 文件存在性检查在转换节点执行。
- 任务与 SSE 队列保存在进程内存中，进程重启后不会保留，也没有多进程共享实现。
- 商品名称集合不存在时由识别节点创建，已存在时直接复用，不校验结构。文档切片集合与索引的初始化尚未实现，相关检索工具仍依赖外部已准备好的切片集合。
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
