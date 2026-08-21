# China Targeted Resume

`china-targeted-resume` 可将只读的 Markdown 职业知识库转换为面向目标公司和岗位、以证据为依据的简历。它会分析岗位要求、映射有来源支持的个人证据、记录差距与约束、审计简历中可见的陈述，并在本地渲染适合 ATS（Applicant Tracking System，申请人跟踪系统）的 PDF。

本仓库提供两个需要分别安装、均受支持的使用界面：

- 一个独立的 Python 3.14 命令行应用；以及
- 一个 OMP Plugin，其中包含 Extension、命令、类型化工具、Agent，以及位于 [`skills/china-targeted-resume/SKILL.md`](skills/china-targeted-resume/SKILL.md) 的唯一规范 Skill。

最终运行时决策是 **Option A: Plugin-first hybrid**。TypeScript 负责 OMP 集成以及纳入跨语言约定的确定性边界；Python 保留为独立 CLI，以及显式的结构解析、编排/审计、Chromium 渲染与 PyMuPDF 检查后端。安装 Plugin 不会在全局安装 Python CLI；安装 Python 软件包也不会向 OMP 注册 Plugin。详见[最终产品边界](docs/final-product-boundary.md)和[第三阶段一致性矩阵](docs/parity-matrix.md)。

## 生成内容

成功生成后，会在指定的输出根目录下创建一个新的、不会覆盖已有内容的运行目录。默认运行会同时生成一页招聘筛选版和两页技术版：

```text
OUTPUT_ROOT/
└── company-slug--role-slug--YYYYMMDDTHHMMSSffffffZ/
    ├── resume-variants.json
    ├── resume-recruiter-1p.document.json
    ├── resume-recruiter-1p.provenance.json
    ├── resume-recruiter-1p.validation.json
    ├── resume-recruiter-1p.audit.md
    ├── resume-recruiter-1p.md
    ├── resume-recruiter-1p.txt
    ├── resume-recruiter-1p.html
    ├── resume-recruiter-1p.pdf
    ├── resume-recruiter-1p.preview.png
    ├── resume-technical-2p.document.json
    ├── resume-technical-2p.provenance.json
    ├── resume-technical-2p.validation.json
    ├── resume-technical-2p.audit.md
    ├── resume-technical-2p.md
    ├── resume-technical-2p.txt
    ├── resume-technical-2p.html
    ├── resume-technical-2p.pdf
    ├── resume-technical-2p.preview.png
    ├── resume-technical-2p.preview-2.png
    ├── requirements.json
    ├── competencies.json
    ├── evidence-map.json
    ├── gaps.json
    ├── application-constraints.json
    ├── application-recommendation.json
    ├── confirmation-questions.md
    ├── interview-questions.md
    ├── source-manifest.json
    ├── run.json
    └── role-dossier/
```

第一页预览使用 `<base>.preview.png`；后续页面依次使用 `<base>.preview-2.png`、`<base>.preview-3.png` 等名称。传入 `--include-extended-profile` 后，还会增加一套以 `technical-profile-3p` 为基础名的版本产物。`resume-variants.json` 是产物发现的权威清单：其中列出所有已生成版本、目标页数与实际页数、验证结果、产物路径和预览路径。使用方应读取该清单，而不是自行推断文件名。

运行目录不会被自动删除。每次调用都会创建一个带 UTC 时间戳的目录，因此不会静默覆盖之前的运行结果。

## 安全模型

- 职业知识库是只读的运行时输入。
- 输出根目录必须位于源根目录之外。
- 运行目录使用 `0700` 权限模式；生成的文件使用 `0600` 权限模式。
- 持久化索引只包含导航元数据和哈希，不包含源文件正文或联系方式。
- 公司调研内容绝不会变成候选人的个人经历。
- 未验证、有冲突、私密、过时或缺乏支持的陈述会被省略，或转换为待确认问题。
- 生成的 PDF 只有在确定性的内容检查与 PDF 检查全部通过后才会被接受。

## 安装与环境要求

### OMP Plugin

Plugin 的 OMP 兼容性下限是 `17.3.7`；此外还需要 Bun `1.3.0` 或更高版本。完整生成流程还需要 [`uv`](https://docs.astral.sh/uv/) 和 Python `3.14` 或更高版本，因为基于解析器的验证、编排/审计、Chromium 渲染和 PyMuPDF 检查仍是显式 Python 后端。

本地开发或仓库尚未发布时，请链接项目的绝对路径：

```bash
omp plugin link /absolute/path/to/china-targeted-resume-plugin --force
```

使用已发布的 GitHub 源安装或刷新：

```bash
omp plugin install github:ParticleG/china-targeted-resume-plugin
omp plugin install github:ParticleG/china-targeted-resume-plugin --force
```

GitHub 安装、`.bun-tag` 中记录的远程源/提交、强制刷新，以及全新项目外 `/resume-status` 发现均已在 OMP `17.3.7` 上验证；详见 `docs/migration-decision-log.md`。

Python 后端 Plugin 工具会通过 `uv run --project PLUGIN_ROOT --offline --frozen china-targeted-resume …` 运行随包检出的源码。请提前准备好锁定的 Python 依赖，并在渲染前安装 Playwright Chromium 与受支持的 CJK 字体。Plugin 安装只负责注册 OMP 组件；它**不会**把 `china-targeted-resume` 加入全局 `PATH`，不会运行 `uv sync`，也不会安装浏览器或字体。只要项目本地桥接命令可用，就不需要全局安装 CLI。

## Plugin 使用：五分钟路径

本节是已安装 OMP Plugin 的面向用户指南，与下面的独立 Python CLI 分开说明。发布的软件包是 [`ParticleG/china-targeted-resume-plugin`](https://github.com/ParticleG/china-targeted-resume-plugin)。安装它会注册 Extension、命令、类型化确定性工具、随包 Agent 和 Skill；但**不会**提供 `uv`、Python、Chromium、CJK 字体，也不会提供全局 `china-targeted-resume` 可执行文件。请使用 OMP `17.3.7` 或更高版本（以及 Bun `1.3.0` 或更高版本）。

### 五分钟快速开始

1. 安装或刷新已发布的 Plugin：

   ```bash
   omp plugin install github:ParticleG/china-targeted-resume-plugin
   ```

2. 开始前先请求本地帮助。帮助通过 `ctx.ui.notify` 显示，不会调用模型。无头客户端或其他客户端是否显示通知取决于该客户端。

   ```text
   /resume-help overview
   ```

3. 初始化运行。每次运行都从 **metadata-only** 开始：

   ```text
   /resume-init demo-metadata
   ```

4. 发现只读源的结构：

   ```text
   /resume-discover /tmp/synthetic-career-db
   ```

5. 将目标上下文交给随包 Skill，然后让 Plugin 执行分析和生成。本例使用合成路径，并请求默认的一页招聘筛选版和两页技术版；不会暗示可选的扩展技术档案。

   ```text
   使用随包的 china-targeted-resume Skill，源根目录为
   /tmp/synthetic-career-db，合成 JD 为 /tmp/synthetic-jd.md，公司为
   "Example Company"，确切岗位为 "Platform Engineer"，语言为 zh-CN，
   模式为 targeted_application，输出为 ATS，输出根目录为
   /tmp/private-resume-output。保持源只读，并将输出放在源根目录之外。
   只生成默认的一页招聘筛选版和两页技术版。

   /resume-analyze demo-metadata
   /resume-generate demo-metadata
   ```

6. 复制生成流程报告的确切 `resume-variants.json` 路径，然后检查清单列出的每个版本并查看状态：

   ```text
   /resume-audit /tmp/private-resume-output/<run-directory>/resume-variants.json
   /resume-status demo-metadata
   ```

   将 `<run-directory>` 替换为 Skill 实际返回的带时间戳目录。不要根据文件名推断版本，也不要把 PDF 检查当成内容审计结果。

### 应该使用哪个命令？

| 目标 | 命令 | 使用时机 | 安全边界 |
| --- | --- | --- | --- |
| 在本地了解 Plugin | `/resume-help [topic]` | 开始运行前或不清楚某个阶段时 | 仅显示本地通知；不调用模型、不读取源、不改变状态 |
| 开始一次运行 | `/resume-init [run-id] [--reviewed-semantic]` | 发现前，每次运行一次 | 默认 metadata-only；授权只能缩小到已记录的片段 |
| 映射源结构 | `/resume-discover SOURCE_ROOT` | 初始化后 | 只将路径交给随包 Skill；确定性发现只返回元数据，不返回源正文 |
| 分析岗位和证据 | `/resume-analyze [run-id]` | 发现后，或需要重建分析时 | 启动独立的内置 task 审查；绝不批准陈述 |
| 编排输出 | `/resume-generate [run-id]` | 证据、批准和用户确认门禁都准备好后 | 没有锁定结果时只发出警告；确定性锁和验证器仍会阻止编排 |
| 检查已生成版本 | `/resume-audit RESUME_VARIANTS_JSON` | 生成后或重新渲染后 | 读取权威清单并检查其中所有 PDF；不能静默跳过子集 |
| 查看运行状态 | `/resume-status [run-id\|RESUME_VARIANTS_JSON]` | 任何阶段，且不需要暴露源正文时 | 仅报告元数据、回执、隐私状态和清单摘要 |

### 命令参考

七个命令都接受 `-h`、`--help` 或 `help` 作为本地确定性帮助请求。例如，`/resume-init --help`、`/resume-discover help` 和 `/resume-status -h` 会显示用法而不调用模型。这些帮助形式不能用于把源正文偷偷放进参数。路径参数有长度和字符边界；应传入路径，不要粘贴 Markdown 正文。
逐命令参数摘要：`/resume-help` 接受可选主题；`/resume-init` 接受可选运行 ID 和 `--reviewed-semantic`；`/resume-discover` 接受一个 `SOURCE_ROOT`；`/resume-analyze` 与 `/resume-generate` 接受可选运行 ID；`/resume-audit` 接受一个 `RESUME_VARIANTS_JSON` 路径；`/resume-status` 接受可选运行 ID 或清单路径。除此之外没有其他工作流标志。

#### `/resume-help [topic]`

- **参数：** 可选主题；省略时使用 `overview`。
- **主题：** `overview`、`init`、`discover`、`analyze`、`generate`、`audit`、`status`、`workflow`、`privacy`、`tools` 和 `troubleshooting`。
- **作用：** 通过 `ctx.ui.notify` 显示选定的本地帮助主题；不会初始化运行、调用模型、调用确定性工具或读取源内容。
- **示例：**

  ```text
  /resume-help workflow
  ```

- **安全失败：** 未知主题会在本地报告，并列出可用主题。如果客户端无法显示通知，请使用交互式 OMP 客户端；不要根据无头客户端的空响应推断帮助已经执行。

#### `/resume-init [run-id] [--reviewed-semantic]`

- **参数：** 可选的有界运行 ID，以及可选的 `--reviewed-semantic` 标志。不带该标志时使用 metadata-only。
- **作用：** 创建或激活运行状态。该标志会启动交互式授权提案，但不会自动披露源片段。
- **示例：**

  ```text
  /resume-init demo-metadata
  ```

- **安全失败：** 无效的运行 ID、非交互式 UI、缺少提供方或模型身份、缺少 OMP session JSONL，或所有权/权限不合格，都会让运行保持 metadata-only 并通知用户。用户拒绝授权时也保持 metadata-only。

#### `/resume-discover SOURCE_ROOT`

- **参数：** 恰好一个只读源根目录路径。不要把源正文、JD 正文、凭据或 JSON 负载放入此参数。
- **作用：** 用发现提示启动随包 Skill。Skill 会调用 `resume_discover_structure`，构建包含路径、哈希、标题、区间、标题祖先、块类型和策略元数据的边界感知映射。
- **示例：**

  ```text
  /resume-discover /tmp/synthetic-career-db
  ```

- **安全失败：** 空路径、过长路径、包含换行的路径或其他无效路径会在本地拒绝。源不存在、不可读，或源与输出边界不合法时会安全失败；不会把源正文作为后备方案发送出去。

#### `/resume-analyze [run-id]`

- **参数：** 可选运行 ID；省略时使用当前活动运行。
- **作用：** 启动随包 Skill，通过 OMP 内置 `task` 扇出执行岗位、要求、证据、贡献和隐私分析，然后要求确定性 IR 验证器检查结果。它不会批准陈述，也不会创建陈述锁。
- **示例：**

  ```text
  /resume-analyze demo-metadata
  ```

- **安全失败：** 无效或未初始化的运行 ID 会在本地报告。缺少发现结果、回执过时、目标有歧义、审查者意见不一致或确定性验证错误都会停止流程；分析文字不能绕过这些门禁。

#### `/resume-generate [run-id]`

- **参数：** 可选运行 ID；省略时使用当前活动运行。
- **作用：** 启动随包 Skill，处理确认，使用精确的确定性批准锁，编排每个请求的版本并渲染产物。默认版本是 `resume-recruiter-1p` 加 `resume-technical-2p`；扩展版 `technical-profile-3p` 只有在明确请求时才生成。
- **示例：**

  ```text
  /resume-generate demo-metadata
  ```

- **安全失败：** 如果同一次运行没有证据回执和批准/陈述锁回执，命令会发出警告，确定性流程仍保持阻塞。它不会把警告变成批准、编造证据或填充 `underfilled` 版本。

#### `/resume-audit RESUME_VARIANTS_JSON`

- **参数：** 恰好一个私有 `resume-variants.json` 清单路径。
- **作用：** 读取并记录清单摘要，在适用时审计保留的 reviewed-semantic 会话数据，然后启动 Skill，让它对清单列出的每个 PDF 调用 `resume_inspect_variants`。
- **示例：**

  ```text
  /resume-audit /tmp/private-resume-output/<run-directory>/resume-variants.json
  ```

- **安全失败：** 清单缺失、格式错误、遍历不安全或不完整时会安全失败。不能将命令指向一个手工挑选的 PDF 来隐藏清单中的其他版本。

#### `/resume-status [run-id|RESUME_VARIANTS_JSON]`

- **参数：** 可选运行 ID 或 `resume-variants.json` 路径。以 `.json` 结尾的参数按清单路径处理，否则按运行 ID 处理。
- **作用：** 显示隐私模式、授权与保留元数据、已完成确定性工具、源/证据/批准回执、确认数和清单摘要的本地 JSON 状态。它不会包含源正文。
- **示例：**

  ```text
  /resume-status demo-metadata
  /resume-status /tmp/private-resume-output/<run-directory>/resume-variants.json
  ```

- **安全失败：** 无效 ID 或不可读清单会在本地报告，不会切换运行，也不会暴露源正文。状态通知不代表成功声明。

### Metadata-only 示例（默认模式）

当结构元数据、哈希、区间、策略值和确定性摘要已经足够时，使用此模式。以下是可复制的顺序；只需将合成路径替换成你自己的只读源、JD 和私有输出路径：

```text
/resume-init demo-metadata
/resume-discover /tmp/synthetic-career-db

使用随包 Skill。根据 /tmp/synthetic-career-db，使用 /tmp/synthetic-jd.md
中的 JD，分析 "Example Company" 的确切 "Platform Engineer" 岗位。
使用 targeted_application、zh-CN、ats-simple，输出根目录为
/tmp/private-resume-output，并且只生成默认的一页招聘筛选版和两页技术版。

/resume-analyze demo-metadata
/resume-generate demo-metadata
/resume-status demo-metadata
```

在 metadata-only 模式中，模型和内置任务只接收 ID、哈希、区间、标题、策略元数据和确定性摘要，不接收源正文。如果重要语义问题无法由这些信息解决，Skill 必须提出聚焦的问题或省略该陈述；不能静默读取更多内容。

### Reviewed-semantic 初始化（明确、有界且保留）

仅当元数据无法解决重要决策时才使用 reviewed-semantic 模式。交互式启动：

```text
/resume-init demo-reviewed --reviewed-semantic
```

出现提示时，记录准确的合成身份（不是凭据）、处理位置、类别和最小必要片段。例如：

```text
Main provider: example-provider
Main model: example-main-model
Main locality: local
Built-in task provider: example-task-provider
Built-in task model: example-task-model
Built-in task locality: local
Authorized disclosure categories: jd,evidence
Exact minimum slices:
[
  {
    "path": "/tmp/synthetic-career-db/roles/example-platform.md",
    "startLine": 8,
    "endLine": 16,
    "category": "jd",
    "consumers": ["main", "role-analyst", "requirement-reviewer"],
    "purpose": "classify the synthetic Platform Engineer requirements"
  },
  {
    "path": "/tmp/synthetic-career-db/projects/example-platform.md",
    "startLine": 42,
    "endLine": 49,
    "category": "evidence",
    "consumers": ["evidence-reviewer", "contribution-reviewer", "privacy-reviewer"],
    "purpose": "verify one synthetic delivery claim and its contribution boundary"
  }
]
```

授权披露必须显示准确的主模型提供方/模型/本地或远程属性，**以及**内置任务的提供方/模型/本地或远程属性；还必须显示每个类别、每个片段的路径/行区间/类别/消费者/用途、已观察到的 OMP session JSONL 位置和权限，以及保留/清理限制。主 session JSONL 必须是当前用户拥有的私有普通文件，不能有组或其他用户权限（通常为 `0600`）；其父 session 目录必须是当前用户拥有的私有目录，权限为 `0700` 且不能有组或其他用户权限。整个 OMP task/advisor 会话树都会审计所有权、权限、格式错误行、回执证明、范围外片段和禁止标记。

授权只适用于本次运行、指定提供方/模型、消费者、类别、用途和精确区间。OMP 所有的 task 和 advisor JSONL 是保留的私有数据；Extension 没有经过验证的选择性删除保证，因此披露必须如实说明。即使已经授权，联系方式、凭据、秘密、整个仓库以及 F6/P3 内容仍然禁止披露。如果任何交互或权限门禁失败，运行会保持 metadata-only。

`resume_read_source_slice` 是唯一的有界正文读取路径。它会在返回一个片段前重新检查源策略、授权 ID、消费者、提供方/模型/本地属性、精确行区间、字节上限和预过滤结果。绝不要把私有正文放入斜杠命令参数，也不要声称被拒绝或被阻止的读取已经发生。

### 精确的回执驱动工作流

Plugin 命令只会启动下面的状态机，不会取代它：

```text
init
  → discover
  → source-map receipt
  → analyze/reviews
  → evidence receipt
  → approval receipt
  → compose
  → manifest render
  → inspect/audit
```

遵循回执，不要依赖文件名或模型文字：

1. `/resume-init` 建立 metadata-only 状态，或记录 reviewed-semantic 授权。
2. `/resume-discover` 引导调用 `resume_discover_structure`。通过 OMP 内置 `task` 工具运行独立的 source-mapper 和 role-analyst 任务。
3. 调用 `resume_validate_source_map`，保留同一次运行的 `source_map_receipt.digest`。该验证器会重新打开源并检查身份、哈希、区间、引文和策略。
4. 使用 `resume_validate_role_ir` 验证 role IR。运行独立的 requirement、evidence、contribution 和 privacy 审查。意见不一致是硬门禁，不是可以忽略的投票。
5. 使用步骤 3 中的准确 `sourceMapDigest` 调用 `resume_validate_evidence_ir`，输入已接受的 selector ID 或明确授权的规范化 evidence。保留 `evidence_receipt.digest`；不要重新发送调用方提供的 source map。
6. 解决确认和硬门禁后，使用同一次运行的证据回执与未经改写的审查 wrapper 调用 `resume_lock_approved_claims`。它返回 `approval_receipt`/陈述锁摘要；这是唯一的批准边界。
7. 使用准确的证据和批准回执摘要，以及仅用于生成的元数据调用 `resume_compose_variants`。它会拒绝过时、跨运行、输出模式不一致或负载不一致的回执。
8. 读取 `resume-variants.json`，调用 `resume_render_variants`，然后对清单列出的每个版本调用 `resume_inspect_variants`。
9. 分别报告每个版本的内容审计、来源追踪/隐私检查、PDF 检查、实际页数和 `underfilled` 状态。PDF 检查成功绝不能替代 `audit_success`。

随包 Skill 和七个 Agent 使用 OMP 内置 `task` 编排独立分析与审查。斜杠命令只会启动该工作流并显示状态，不能绕过确定性 source-policy、IR、evidence、approval、composition、rendering 或 inspection 工具。

### 按用户阶段分组的九个确定性工具

| 阶段 | 工具 | 作用与拒绝边界 |
| --- | --- | --- |
| 发现 | `resume_discover_structure` | 构建 metadata-only 源映射（路径、哈希、区间、标题、祖先、块和策略）；不暴露正文，也不编排 Agent |
| 有界披露 | `resume_read_source_slice` | 只在 reviewed-semantic 模式下读取一个准确授权且已预过滤的行区间；metadata-only 运行以及未授权、无关、禁止、超大或不匹配的片段都会安全失败 |
| 源映射验证 | `resume_validate_source_map` | 重新打开源并验证身份、哈希、区间、引文和策略；Agent 输出不能覆盖它，并记录 source-policy 回执 |
| 岗位验证 | `resume_validate_role_ir` | 检查规范化 role IR、要求引文/区间、时效性以及公司/岗位/路线图区分 |
| 证据验证 | `resume_validate_evidence_ir` | metadata-only 模式只物化批准的 extractive ID，或验证明确授权的规范化 evidence IR；返回 evidence 回执，并拒绝调用方提供的 source map |
| 批准 | `resume_lock_approved_claims` | 应用硬分歧规则，验证审查 wrapper 和重新验证的来源，收集必要的用户确认并创建陈述锁；禁止调用方布尔值/证据正文 |
| 编排 | `resume_compose_variants` | 验证同一次运行的回执与确认状态，然后调用私有 Python 编排；不能接收调用方提供的 evidence/review/approval 正文 |
| 渲染 | `resume_render_variants` | 将清单列出的每个 document 重新渲染为清单列出的 PDF；遍历不安全或缺少产物时安全失败 |
| 检查/审计 | `resume_inspect_variants` | 按页面约定和真实提取文本检查清单列出的每个 PDF；不能传入子集 |

所有工具都返回类型化的成功/错误 envelope，并使用一个配置好的后端。没有静默的 TypeScript/Python 回退。Python 后端工具需要项目本地桥接前置条件。

### 发现产物和权威清单

生成始终创建 `resume-recruiter-1p` 和 `resume-technical-2p`。只有在确实需要扩展技术档案时才请求 `technical-profile-3p`；它不是默认版本。Skill 会在私有输出根目录下创建新的带时间戳运行目录。`resume-variants.json` 是权威清单，其中列出每个版本的目标和实际页数、验证/审计结果、产物路径和预览路径。请先读取它：

```text
RUN_DIR/resume-variants.json
```

随后只打开该版本清单列出的路径，例如 `.document.json`、`.provenance.json`、`.validation.json`、`.audit.md`、`.md`、`.txt`、`.html`、`.pdf` 和预览图。清单可以合理地将证据稀疏的版本标记为 `underfilled`；不要为了达到页数目标加入没有依据的填充内容。清单列出的每个版本都必须分别通过内容审计和 PDF 检查。PDF 通过、页数符合或文件存在本身都不表示内容审计通过。

### Plugin 前置条件与隐私门禁速查

- 完整 Plugin 工作流需要 OMP `17.3.7+`、Bun `1.3.0+`、`uv` 和 Python `3.14+`。
- 随包桥接通过 `uv run --project PLUGIN_ROOT --offline --frozen` 运行；调用 Python 后端工具前请安装锁定的依赖。
- 渲染需要 Playwright Chromium，以及位于 `/usr/share/fonts` 的 Noto Sans CJK SC 或 Source Han Sans SC；Plugin 安装不会安装它们。
- 源必须保持只读，输出根目录必须在源目录之外。运行目录/文件为私有权限（`0700`/`0600`）。
- 默认模式是 metadata-only。reviewed-semantic 还需要交互式 UI、每次运行的明确授权和权限严格的 OMP 私有会话树。
- 不得披露联系方式、凭据、秘密或 F6/P3 内容。不得从之前的运行或 CLI 访问推断授权。

### Plugin 故障排除

#### “No deterministic claim-lock result is recorded”

`/resume-generate` 可能会针对该状态发出警告，但它不能批准陈述。回到 `/resume-analyze`，确认同一次运行拥有成功的 source-map 和 evidence 回执，解决独立审查分歧与必要确认，并让 Skill 调用 `resume_lock_approved_claims`。不要将 evidence 或 approval JSON 粘贴进 `/resume-generate`，也不要把警告当成成功。

#### `SOURCE_POLICY_REQUIRED` 或无关片段

证据工具或片段读取器缺少同一次运行验证过的 source-policy 回执，或者请求的路径/区间不在授权策略映射或最小片段清单中。重新运行发现和 `resume_validate_source_map`，使用其返回的摘要，并且只请求带有记录的消费者/类别/用途的准确授权区间。绝不要扩大区间、替换文件或把源正文粘贴到命令参数中。

#### OMP 会话树权限较弱

当 JSONL 文件或任何经过审计的 task/advisor 目录/文件不是当前用户拥有、权限私有、类型正确或无法证明回执时，reviewed-semantic 授权会保持禁用。修复 OMP 会话目录/文件的权限和所有权；必要时开启新的私有交互式会话并初始化新运行。弱会话树、`outOfScopeSliceCount`、`forbiddenSentinelCount`、格式错误行或保留产物审计失败都必须如实报告；绝不要声称没有证据的清理或删除已经完成。

#### 缺少 Python 桥接依赖

Plugin 安装不会执行依赖设置。从检出目录中准备锁定环境和渲染前置条件，然后再使用 Python 后端工具：

```bash
cd /path/to/china-targeted-resume-plugin
uv sync
uv run playwright install chromium
```

按前置条件在 `/usr/share/fonts` 下安装 Noto Sans CJK SC 或 Source Han Sans SC。桥接会从随包项目以 offline/frozen 模式运行；缺少软件包、浏览器或字体时会显式报告后端失败，不能因此绕过确定性工具。

#### `audit_success` 为 false 或版本为 `underfilled`

读取 `resume-variants.json`，再阅读受影响版本的 `.validation.json` 和 `.audit.md`。修复有来源支持的陈述、策略、隐私、布局或渲染问题，并重新运行受影响的确定性阶段。`underfilled` 可能是证据稀疏时少于目标页数的有效结果；不要填充它，也不要静默加入可选扩展技术档案。即使 PDF 通过页面/文本检查，`audit_success` 仍可能为 `false`；即使 `audit_success: true`，仍必须检查真实 PDF。

### 独立 Python CLI

CLI 不依赖 OMP 或 Plugin，但需要：

- Linux；
- Python 3.14 或更高版本；
- [`uv`](https://docs.astral.sh/uv/)；
- Playwright Chromium；以及
- 安装在 `/usr/share/fonts` 下的 Noto Sans CJK SC 或 Source Han Sans SC。

在 Arch Linux 上，可通过以下命令安装字体依赖：

```bash
sudo pacman -S --needed noto-fonts-cjk
```

安装项目依赖和 Chromium：

```bash
cd /path/to/china-targeted-resume-plugin
uv sync
uv run playwright install chromium
```

确认项目本地 CLI 可用：

```bash
uv run china-targeted-resume --help
```

下文所有 CLI 示例均使用 `uv run china-targeted-resume`。只有在另行将 Python 软件包安装为全局命令后，才可省略 `uv run`。

## 教程：准备源路径和输出路径

为当前 shell 设置路径：

```bash
export SOURCE_ROOT=/path/to/read-only-career-knowledge-base
export OUTPUT_ROOT=/path/to/private-resume-output
```

`OUTPUT_ROOT` 不能等于 `SOURCE_ROOT`，也不能位于 `SOURCE_ROOT` 之下。

## 教程：发现公司和岗位

列出源适配器识别到的公司：

```bash
uv run china-targeted-resume list-companies \
  --source "$SOURCE_ROOT"
```

列出某个确切公司 ID 或显示名称下的岗位：

```bash
uv run china-targeted-resume list-roles \
  --source "$SOURCE_ROOT" \
  --company COMPANY
```

在后续命令中使用返回的标识符。如果有多个公司或岗位匹配，请明确选择一个，而不是猜测。

## 教程：根据完整且当前有效的 JD 生成简历

完整且当前有效的职位描述会产生 Tier A、`exact-current-jd` 分析。必须且只能提供 `--jd-file`、`--jd-text` 或 `--jd-url` 中的一个参数。

使用本地 UTF-8 JD 文件：

```bash
uv run china-targeted-resume generate \
  --source "$SOURCE_ROOT" \
  --company COMPANY \
  --role "ROLE TITLE" \
  --jd-file /path/to/job-description.md \
  --mode targeted_application \
  --language zh-CN \
  --template ats-simple \
  --output "$OUTPUT_ROOT"
```

使用 HTTPS JD URL：

```bash
uv run china-targeted-resume generate \
  --source "$SOURCE_ROOT" \
  --company COMPANY \
  --role "ROLE TITLE" \
  --jd-url https://jobs.example.invalid/ROLE \
  --mode targeted_application \
  --language zh-CN \
  --template ats-simple \
  --output "$OUTPUT_ROOT"
```

该命令会输出 JSON，其中包含 `run_dir` 和各个生成产物的路径。请保留 `run_dir`；后续验证和刷新命令会用到它。

生成命令始终输出 `resume-recruiter-1p` 和 `resume-technical-2p`。如需同时输出三页扩展技术档案，请添加：

```bash
uv run china-targeted-resume generate \
  --source "$SOURCE_ROOT" \
  --company COMPANY \
  --role "ROLE TITLE" \
  --jd-file /path/to/job-description.md \
  --mode targeted_application \
  --language zh-CN \
  --template ats-simple \
  --include-extended-profile \
  --output "$OUTPUT_ROOT"
```

## 教程：仅知道岗位时生成简历

如果没有完整且当前有效的 JD，请省略所有 JD 选项。当源中包含确切岗位以及注明日期的公司调研资料时，流水线会以 Tier B 继续执行：

```bash
uv run china-targeted-resume generate \
  --source "$SOURCE_ROOT" \
  --company COMPANY \
  --role "ROLE TITLE" \
  --mode targeted_application \
  --language zh-CN \
  --template human-readable \
  --output "$OUTPUT_ROOT"
```

Tier B 输出会在审计产物中记录来源时效、缺失的要求、冲突、推断侧重点以及覆盖范围限制，而不会将这些内容作为简历事实呈现。

## 教程：检查已完成的运行

将变量设置为 `generate` 返回的确切时间戳目录：

```bash
export RUN_DIR="$OUTPUT_ROOT/company-slug--role-slug--YYYYMMDDTHHMMSSffffffZ"
```

重新执行内容审计：

```bash
uv run china-targeted-resume validate-content \
  --run "$RUN_DIR"
```

使用各版本的确切页数上限，分别独立检查每个 PDF：

```bash
uv run china-targeted-resume inspect-pdf \
  --pdf "$RUN_DIR/resume-recruiter-1p.pdf" \
  --max-pages 1 \
  --expected-name "CANDIDATE NAME"

uv run china-targeted-resume inspect-pdf \
  --pdf "$RUN_DIR/resume-technical-2p.pdf" \
  --max-pages 2 \
  --expected-name "CANDIDATE NAME"
```

如果生成时请求了扩展技术档案，请使用 `--max-pages 3` 检查 `technical-profile-3p.pdf`。

通过 `resume-variants.json` 发现各版本，并打开每个版本自己的 Markdown、PDF、预览图、审计、来源追踪和验证 JSON。例如：

```text
RUN_DIR/resume-variants.json
RUN_DIR/resume-recruiter-1p.pdf
RUN_DIR/resume-recruiter-1p.validation.json
RUN_DIR/resume-technical-2p.pdf
RUN_DIR/resume-technical-2p.validation.json
```

只有清单中每个版本的内容审计和 PDF 检查均成功，并且所有预览中都没有裁切、重叠、CJK 文字损坏、项目符号格式异常，也没有在简历可见区域出现审计或来源追踪措辞时，本次运行才算完成。

## 教程：单独重建各个阶段

重建确定性的证据映射：

```bash
uv run china-targeted-resume build-evidence-map \
  --run "$RUN_DIR"
```

重新渲染某个已有版本的规范化文档：

```bash
uv run china-targeted-resume render \
  --document "$RUN_DIR/resume-technical-2p.document.json" \
  --output "$RUN_DIR/resume-technical-2p.pdf"
```

输出目录必须保持私密，并且不能通过符号链接穿越路径边界。渲染后，应使用该版本对应的确切 `--max-pages` 值检查 PDF。

## 教程：分析请求 JSON

`analyze-role` 接受经过验证的 `RunRequest` JSON 文档。完整约定见 [`schemas/request.schema.json`](schemas/request.schema.json)。

示例：

```json
{
  "schema_version": 1,
  "source_adapter": "markdown-career-v1",
  "source_root": "/path/to/read-only-career-knowledge-base",
  "output_root": "/path/to/private-resume-output",
  "company_ref": "COMPANY",
  "role_ref": "ROLE TITLE",
  "jd": {
    "text": null,
    "file": "/path/to/job-description.md",
    "url": null
  },
  "output_mode": "targeted_application",
  "language": "zh-CN",
  "include_extended_profile": false,
  "template": "ats-simple",
  "persist_role_research": false,
  "refresh_external_sources": false,
  "export_roadmap_handoff": false,
  "application_constraints": {}
}
```

执行分析：

```bash
uv run china-targeted-resume analyze-role \
  --request /path/to/request.json
```

除非已明确审阅并批准将其持久化到源仓库，否则岗位档案会保留在本次运行目录中。

## 教程：刷新岗位或证据分析

JD 或公司调研发生变化后，刷新岗位分析：

```bash
uv run china-targeted-resume refresh-role \
  --role "$RUN_DIR"
```

负责归属的个人数据源发生变化后，刷新证据映射：

```bash
uv run china-targeted-resume refresh-match \
  --role "$RUN_DIR"
```

刷新操作会创建新的、不会覆盖已有内容的输出，而不是重写源知识库。路线图条目绝不会提升匹配状态；经过验证的工作必须先记录到正确的个人数据归属文件中。

## 教程：导出已确认的差距

路线图移交必须显式执行，并且是单向的。只有在审阅差距并决定创建独立学习计划后，才应导出：

```bash
uv run china-targeted-resume export-roadmap-handoff \
  --role "$RUN_DIR" \
  --severity Critical,Major \
  --output "$RUN_DIR/roadmap-handoff.json"
```

该命令会导出已确认的差距，但不会创建学习计划，也不会更改当前证据状态。

## 输出模式、版本和模板

输出模式：

- `targeted_application`：允许使用已确认的、仅限求职申请场景的 P2 证据。
- `public_portfolio`：排除仅限求职申请的材料，并按要求排除私密联系方式。
- `master_resume`：生成更广泛、以证据为依据的简历，不会把信息不足的目标伪装成确切岗位。

输出版本：

- `resume-recruiter-1p`：供招聘人员快速筛选的一页版，始终生成。
- `resume-technical-2p`：两页技术版，始终生成。
- `technical-profile-3p`：三页扩展技术档案，仅在传入 `--include-extended-profile` 时生成。

每个版本都会针对不同读者和自己的页数目标独立编排内容；它们并非同一文档按任意页数重复渲染。当源证据不足以在不填充内容的前提下支撑目标页数时，清单会将该版本标记为 `underfilled`，通过验证的 PDF 也可能少于目标页数。

模板：

- `ats-simple`：保守的单栏 ATS 布局。
- `human-readable`：保持相同的语义阅读顺序，但采用更面向人工阅读的视觉呈现。

## 使用 OMP Plugin 与 Skill

安装后的 Plugin 通过 **Plugin-first hybrid** 后端让 OMP 会话理解自然语言请求。先使用 `/resume-init`，再按需使用 `/resume-discover`、`/resume-analyze`、`/resume-generate`、`/resume-audit` 和 `/resume-status`。这些命令是编排入口，不会取代策略验证。

每个 Plugin 工具只有一个配置好的后端；后端不可用时会显式失败，不会在 Python 与 TypeScript 之间静默回退。TypeScript 负责授权源片段读取器和已批准陈述锁定；基于 `markdown-it-py` 的 source-map/role/evidence 验证、编排与审计、Playwright Chromium 渲染和 PyMuPDF 检查仍使用显式 Python 后端。完整逐工具矩阵见 [`docs/final-product-boundary.md`](docs/final-product-boundary.md)。

每次运行均默认采用 metadata-only 模式：模型只接收结构元数据、ID、哈希、区间、策略值和确定性摘要，不接收源正文。只有当重要语义判断确实需要某个私密原文片段时，Plugin 才可先披露所选模型提供方及其本地/远程属性、披露类别与最小片段、私密 OMP JSONL 的位置和实际权限，以及保留/清理限制。reviewed-semantic 访问必须获得针对本次运行的明确授权；联系方式、凭据和 F6/P3 内容始终禁止披露。

Skill 要求主模型通过 OMP 内置 `task` 工具扇出七个随包 Agent。要求、证据、贡献和隐私审查中的独立分歧构成硬门禁；resume advisor 只监视工作流，不能批准陈述。必须先执行基于解析器的验证，再由 TypeScript 锁定已批准陈述；只有文本完全一致的锁定陈述才能用于编排、渲染和检查。

示例提示词：

```text
使用 /path/to/career-db 下的职业知识库和 /path/to/job-description.md
中的 JD，为公司 A 的确切 AI 基础设施工程师岗位生成默认的一页招聘筛选版
和两页技术版 zh-CN ATS 简历，同时包含扩展技术档案。将所有产物保存到
/path/to/private-output，并报告每个版本的内容审计和 PDF 检查结果。
```

Skill 会解析目标层级，仅提出会对结果产生实质影响的确认问题，并报告带时间戳的运行目录。它绝不会将生成的简历文本写回 `personal-data/`。仅安装 Plugin 或 `.skill` 并不会安装 Python CLI；上述项目本地内核桥接前置条件必须事先可用。

## 测试

运行独立 Python 与真实产物测试套件：

```bash
uv run pytest -q
```

运行 Plugin 类型检查和完整 Bun 约定套件：

```bash
bun run check
```

如只需执行第三阶段的 schema、安全 I/O 与源身份门禁：

```bash
bun run test:kernel
```

## 构建和打包

构建 Python 发行包和经过筛选的 Skill 归档：

```bash
uv build
uv run python scripts/package_skill.py
```

预期产物：

```text
dist/china_targeted_resume-0.1.0.tar.gz
dist/china_targeted_resume-0.1.0-py3-none-any.whl
dist/china-targeted-resume-plugin.skill
```

Git/源码形式的 OMP Plugin 软件包遵循 `package.json#files`：其中包含 Extension、确定性 TypeScript 内核、Agent、规范 Skill、schema、资源、Python 专用后端、锁定的 Python 项目元数据，以及最终边界/一致性文档；不包含测试。Python wheel 包含独立运行时、渲染资源以及已安装验证命令所需的五个 IR schema；sdist 包含 Plugin 布局下的规范 Skill 及其参考文档。经过筛选的 `.skill` 归档使用同一份规范源文件，在归档根部暂存唯一的 `SKILL.md` 与 `references/`，并包含 Python 运行时源码、schema、模板、脚本和英文 README，但不创建递归的 `.agents/skills` 或 `.claude/skills` 链接。它不包含测试、评估工作区、缓存、真实源数据或生成的简历输出。

这些是不同的安装产物：安装 OMP Plugin 或解包 `.skill` 都不会执行全局 Python CLI 安装；`.skill` 是编排包，并不是 OMP Extension 软件包。

## 评估工作区

Skill Creator 评估工作流会创建一个同级目录，例如：

```text
<project-parent>/china-targeted-resume-workspace
```

其中包含各次迭代输出、使用 Skill 与基线的对比、评分、计时、基准数据和 `review.html`。Python 包不会导入该目录，`.skill` 归档也不会包含它，运行 CLI 或安装后的 Skill 均不依赖它。

需要保留可复现的基准测试历史时，请保留该目录。只有在不再需要这些评估记录时，才归档或删除它。

## 查找生成的运行结果

生成的简历保存在 `--output` 指定的根目录下，而不是项目仓库或评估工作区中。

例如：

```text
<output-root>/
└── company-slug--role-slug--YYYYMMDDTHHMMSSffffffZ/
```

每次运行都包含共享分析产物和独立编排的简历版本。请通过 `resume-variants.json` 发现这些版本；清单中的每个版本都有自己的文档、Markdown、ATS 文本、HTML、PDF、预览图、来源追踪、审计和验证报告。

如果文件管理器中没有显示该目录：

1. 将完整绝对路径粘贴到位置栏；
2. 刷新父目录；
3. 确认打开的是通过 `--output` 传入的确切根目录；
4. 在终端中对完整路径运行 `stat`。

## 故障排除

### 缺少 Chromium 可执行文件

```bash
uv run playwright install chromium
```

### 缺少 CJK 字体

请在 `/usr/share/fonts` 下安装 Noto Sans CJK SC 或 Source Han Sans SC。在 Arch Linux 上：

```bash
sudo pacman -S --needed noto-fonts-cjk
```

### 输出路径与源路径重叠

请选择职业知识库之外的输出根目录。源路径和输出路径不能相同，输出路径也不能是源路径的后代目录。

### 现有输出根目录权限过宽

使用私密输出目录：

```bash
chmod 700 "$OUTPUT_ROOT"
```

生成的文件会自动限制为 `0600` 权限模式。

### 公司或岗位存在歧义

运行 `list-companies` 和 `list-roles`，然后传入确切的返回标识符。流水线会有意避免在多个匹配项之间进行猜测。

### PDF 已存在，但验证失败

打开 `resume-variants.json`，再阅读失败版本对应的 `<base>.validation.json` 和 `<base>.audit.md`。修复有来源支持的内容问题或渲染问题，重新运行 `validate-content`，渲染受影响的 `<base>.document.json`，并以确切页数上限（`1`、`2` 或 `3`）检查其 PDF。仅有文件存在并不代表验收通过。

## 更多文档

- [`docs/final-product-boundary.md`](docs/final-product-boundary.md)：Option A 运行时决策、受支持环境、安装/更新门禁和逐工具后端归属
- [`docs/parity-matrix.md`](docs/parity-matrix.md)：第三阶段一致性证据、精确规范化规则和最终验证矩阵

- [`skills/china-targeted-resume/SKILL.md`](skills/china-targeted-resume/SKILL.md)：唯一规范的 OMP 编排约定
- [`skills/china-targeted-resume/references/source-adapter.md`](skills/china-targeted-resume/references/source-adapter.md)：源发现与隔离
- [`skills/china-targeted-resume/references/role-resolution.md`](skills/china-targeted-resume/references/role-resolution.md)：Tier A-D 解析
- [`skills/china-targeted-resume/references/evidence-policy.md`](skills/china-targeted-resume/references/evidence-policy.md)：事实与披露门禁
- [`skills/china-targeted-resume/references/role-dossier-contract.md`](skills/china-targeted-resume/references/role-dossier-contract.md)：七文件岗位档案边界
- [`skills/china-targeted-resume/references/output-contract.md`](skills/china-targeted-resume/references/output-contract.md)：产物约定
- [`skills/china-targeted-resume/references/resume-audit.md`](skills/china-targeted-resume/references/resume-audit.md)：内容与 PDF 验收
- [`skills/china-targeted-resume/references/privacy-policy.md`](skills/china-targeted-resume/references/privacy-policy.md)：隐私与保留规则
- [`skills/china-targeted-resume/references/roadmap-handoff.md`](skills/china-targeted-resume/references/roadmap-handoff.md)：显式差距导出
