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

获得授权并发布 GitHub 仓库后，使用同一远程源安装和更新：

```bash
omp plugin install github:OWNER/REPOSITORY
omp plugin install github:OWNER/REPOSITORY --force
```

当前本地仓库尚未通过远程 GitHub 安装、记录源更新和全新项目外会话发现；这些仍属于发布后的外部门禁。本地链接结果不能替代该门禁。

Python 后端 Plugin 工具会通过 `uv run --project PLUGIN_ROOT --offline --frozen china-targeted-resume …` 运行随包检出的源码。请提前准备好锁定的 Python 依赖，并在渲染前安装 Playwright Chromium 与受支持的 CJK 字体。Plugin 安装只负责注册 OMP 组件；它**不会**把 `china-targeted-resume` 加入全局 `PATH`，不会运行 `uv sync`，也不会安装浏览器或字体。只要项目本地桥接命令可用，就不需要全局安装 CLI。

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
