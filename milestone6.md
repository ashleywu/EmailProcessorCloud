# Milestone 6：CLI、一键 run-daily、preview、配置与端到端测试

**前提**：Milestone 1–5 已完成。编排入口位于 **`app/agents/daily_digest_agent.py`** 的 **`DailyDigestAgent`**（禁止使用 **`app/agent/`** 路径）。

实现前请先阅读：`app/main.py`、`app/config.py`、`app/gmail/fetcher.py`、`app/storage/repository.py`、`app/agents/daily_digest_agent.py`。

---

## 一、设计原则

### 1. 幂等与极简 CLI

- **不提供**独立的 ingestion / retry 子命令。
- **定时或手动**只需执行 **`run-daily`**：`DailyDigestAgent` 已通过 **`fetch_unprocessed_emails`** 与 **`fetch_retryable_errors`** 合并候选；重复执行即「拉新邮件 + 重试未超限的失败邮件」，无需用户区分场景。
- **不得**新增 **`retry-errors`**（或等价命名的第二套「仅重试」命令）。

### 2. 配置单一真相（`Settings` + 校验）

- **LLM、Gmail、Digest、锁、数据库、质检次数**等所有运行时配置必须收口到 **`config.Settings`**（或等价模块中的单一设置类型），在进程启动时 **一次性加载并校验**。
- **须采用**：**`pydantic-settings`**（`BaseSettings`）从环境变量 / `.env` 装载，利用 **类型约束** 与 **`Field(..., min_length=…)` / 必填字段** 完成校验；将现有手写 **`load_settings()`** 迁移为该模型（单一入口 **`load_settings()`** 不变）。
- **禁止**：在 **`app/`** 业务代码、`OpenAIProvider`、`DailyDigestAgent` 等处散落 **`os.getenv("OPENAI_API_KEY")`** 及对同类密钥的直连读取；一律通过 **`Settings` 实例** 注入（构造函数参数或 factory）。
- **测试**：优先 **构造假的 / 最小的 `Settings` 对象** 注入依赖；避免依赖 **`monkeypatch` 篡改全局环境变量**（除非专门测试「从 env 装载 Settings」的极少数用例）。
- **`.env.example` 与 README** 中的变量名必须与 **`Settings` 字段及其 env 映射**一致；禁止维护两套别名。

---

## 二、配置装载与 Fail-fast

### 1. `DIGEST_RECIPIENT_EMAIL`

- **`run-daily`**：**若收件人未配置或为空字符串**，须在 **启动流水线的最早阶段**（在任何 Gmail 拉取、`run_daily()`、网络调用之前）**立即失败退出**（非零退出码 + 明确错误信息）。  
- 推荐由 **`Settings`** 将该字段设为 **必填**（pydantic 校验），CLI 入口仅在捕获校验异常时打印友好文案亦可。

### 2. 其它校验

- **`DAILY_DIGEST_MAX_QUALITY_GATE_ATTEMPTS`**：**须在 `Settings` 层拒绝 ≤ 0**（例如 **`Field(ge=1)`**）；非法整数同理，装载时报错并 fail-fast。

---

## 三、`python -m app.main show-config`（长期保留 + 安全脱敏）

### 1. 定位

- **`show-config` 长期保留**，作为 Cron / 云端排查 **环境隔离、路径、模型名、scope** 的首选工具。
- **严禁**在标准输出中打印 **明文 API Key、访问令牌、refresh token、客户端 secret** 或 **`token.json` / `credentials.json` 的文件内容**。

### 2. 脱敏规则（须实现并测）

- **密钥类字符串**（如 **`OPENAI_API_KEY`** 映射字段）：输出 **打码** 形式，例如保留类型可识别前缀 **`sk-proj-`**，其余以 **`******`**（或固定长度 `*`）替换；若密钥过短，可整串替换为 **`***`**。
- **路径类**：仍可打印 **`GMAIL_CREDENTIALS_PATH`**、**`GMAIL_TOKEN_PATH`** 等 **文件路径字符串**（不构成密钥本体）；不得 **`open()` 读取并打印** 上述文件正文。
- **Gmail 摘要**（标签名、scopes、发件人列表基数等）：延续「仅元数据」策略；任何未来新增的「可能含 secret 的字段」默认归入脱敏分支。
- **自检**：增加测试断言：**`show-config`  stdout 不包含** 完整真实 API key 子串（可使用 fixture key 验证）。

---

## 四、`python -m app.main run-daily`

### 1. 一键端到端顺序（强制）

以下三步须在同一 invocation 内按序执行（可在 **`app/main.py`** 或 **`app`** 内极薄封装函数中串联；**不要求**用户事先运行其他命令）。**Settings 校验通过且 `DIGEST_RECIPIENT_EMAIL` 已满足必填后**再执行：

1. 使用 **`Settings`** 构造 **`GmailClient`** / **`GmailFetcher`**（**`senders`** ← **`NEWSLETTER_SENDERS`**，**`lookback_days`** ← **`GMAIL_LOOKBACK_DAYS`** 等）。
2. **`fetcher.fetch_recent()`** → 对每条 **`GmailMessage`** 调用 **`StateRepository.upsert_email(msg.to_email_input())`**。
3. 构造完整的 **`DailyDigestAgent`**（repo、lock、fetcher、router/processors、composer、quality gate、labeler、sender；**`digest_to`** 来自 **`Settings.digest_recipient_email`**；LLM 客户端由 **`Settings`** 注入），调用 **`run_daily()`**。

**说明**：若 **`NEWSLETTER_SENDERS`** 为空，`fetch_recent` 行为与现有 **`GmailFetcher`** 一致（返回空列表）；README 须提示有效 run-daily 需配置发件人列表。

### 2. `DailyDigestAgent.run_daily()` 边界

- **允许**保持 **`run_daily()`** 内部不包含 **`fetch_recent`**（便于单元测试「仅 DB 候选」）；**同步 Gmail → SQLite** 放在 **`run-daily` 命令入口**即可。
- **`run_daily()`** 现有语义（锁、候选合并、单封失败、质检、send、成功后归档等）不变，除非本文另有明确要求。

### 3. 运行锁与 CLI 退出码

若因 **`RunLock.acquire()` 失败**而未执行编排主体：**`run-daily` CLI 须以非零退出码结束**，并向 **stderr** 输出简短说明（例如另一实例占锁），以便 Cron / 脚本判定失败。**不得**将此情形当作成功（退出码 0）。

---

## 五、`python -m app.main preview-digest --date YYYY-MM-DD`

### 1. 行为

- 从 SQLite **`digests`** 表读取 **`body_html`**。
- **日期语义**：参数 **`YYYY-MM-DD`** 表示 **UTC 日历日**（与 digest 标题中日期的约定一致）。
- **选取规则**：在所有满足「**`created_at` 落在该 UTC 日历日**」的 digest 行中，取 **`created_at` 最新的一条**；**永远只输出这一条**。若该日无任何 digest：CLI 以明确错误信息退出并使用非零退出码。
- **输出**：默认将 HTML 写入 **stdout**；可选参数将同一内容写入本地文件（例如 **`--output path.html`**），由实现选定具体 flag 名称并在 **`--help`** 中说明。
- **禁止**：发送邮件、调用 Gmail 修改 API、修改 **`emails` / `digests`** 状态（只读查询除外无所写）。
- **CLI 失败路径（实现约束）**：对本命令而言，**预期失败**（含当日无 digest、§2 之空 `body_html` 等）须在 **`preview-digest` 路径内处理**：**stderr 友好提示 + 非零退出码**；**禁止**把此类情形当作**未捕获异常**甩给用户（避免 traceback）。与 §2 细则一致。

### 2. `body_html` 为 `NULL` 或空字符串（拍板）

选中「该 UTC 日 **`created_at` 最新」的一条 digest 后，若 **`body_html` 为 SQL `NULL`** 或 **去除空白后为空字符串**（例如 **`draft`**、未完成写入即中断、或仅有 **`error_message`** 的行）：

- **语义**：**不得**将该情况当作成功预览；**须以非零退出码结束进程**（例如 **`sys.exit(1)`**），以便 Cron / 脚本 / CI 能判定失败。
- **用户体验**：在 **`preview-digest` 命令路径内优雅拦截**，向 **stderr** 打印**简短友好说明**（含 **`digest_id`**、**`status`** 若可得）；**禁止让该情形以未捕获异常的形式冒泡到顶层**（避免对用户打出 traceback）。允许在内部捕获异常后再写入 stderr 并退出。
- **输出副作用**：**不向 stdout 写入实质 HTML**；若指定 **`--output`**，**不得留下误导性的「看似成功的预览文件」**（以实现统一为准：可不创建文件，或不写入有效 HTML——须在 **`--help`** 中写明与其它失败分支一致）。
- **文档分层**：**README 仅记录 `preview-digest` 的基本用法**（日期参数、可选输出文件），**不要求**展开上述边界行为；**契约细节以本节 + `--help` 为准**（`--help` 至少用一两句说明：**指定 UTC 日无任何 digest**、或 **有记录但无可预览正文** 时，命令**失败并以非零码退出**）。

### 3. `StateRepository`

- 新增查询方法（名称自定，须在 docstring 中写明 UTC 日与「最新一条」规则），供 **`preview-digest`** 使用。

### 4. 配置依赖（相对 `run-daily`）

**`preview-digest`** **仅需能解析数据库路径**（**`DAILY_DIGEST_DB_PATH`** 或其默认 **`Settings.db_path`**）；**不得**要求用户必须配置 **`OPENAI_API_KEY`**、**`DIGEST_RECIPIENT_EMAIL`** 等 **`run-daily` 专用项** 才能执行预览。实现方式：该子命令装载 **`Settings`** 后 **跳过** run-daily 的必填校验（仅校验日期参数与 DB 可读性等）；环境变量仍来自同一 **`Settings` / `.env` 源**，禁止引入第二套变量名。

---

## 六、质检次数：环境变量与重构

- 将 **`DailyDigestAgent`** 内写死的 **`_MAX_QUALITY_ATTEMPTS = 3`** 改为从 **`Settings`** 读取。
- **环境变量名**：**`DAILY_DIGEST_MAX_QUALITY_GATE_ATTEMPTS`**（默认值 **`3`**），由 **`Settings`** 装载。
- **语义**：**最多进行 N 次「compose → quality gate」尝试**（含首次草稿）。须在 **`Settings` 字段注释**中写死，避免与「仅额外重试次数」混淆。

---

## 七、`.env.example`

与 **`Settings`**（含 pydantic-settings 的 env 名映射）保持同步，至少包含：

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | OpenAI API 密钥（**`run-daily` 必填**；**`preview-digest` 不要求**） |
| `ROUTER_MODEL` | Router 模型 |
| `PROCESSOR_MODEL` | Processor 模型 |
| `DIGEST_RECIPIENT_EMAIL` | Digest 收件人（**`run-daily` 必填 / fail-fast**；**`preview-digest` 不要求**） |
| `NEWSLETTER_SENDERS` | 逗号分隔发件人，供 fetch query |
| `GMAIL_CREDENTIALS_PATH` | OAuth 客户端密钥 JSON |
| `GMAIL_TOKEN_PATH` | 令牌缓存路径 |
| `GMAIL_LOOKBACK_DAYS` | 拉取窗口（天） |
| `DAILY_DIGEST_DB_PATH` | SQLite 路径（可选；有默认） |
| `DAILY_DIGEST_LOCK_NAME` | 锁名（可选） |
| `DAILY_DIGEST_LOCK_TTL_MINUTES` | 锁 TTL |
| `DAILY_DIGEST_MAX_EMAIL_RETRIES` | 邮件失败重试上限（与 `fetch_retryable_errors` 一致） |
| `DAILY_DIGEST_MAX_QUALITY_GATE_ATTEMPTS` | 质检最大尝试次数（见第六节） |

**禁止**在文档中引入代码未读取的别名（例如单独的 `RUN_LOCK_TTL_MINUTES`）。**`DigestComposer` 当前无 LLM**，若无代码读取 **`COMPOSER_MODEL`**，则 **不要**写入 `.env.example`。

**依赖**：**`pydantic-settings`** 须列入 **`pyproject.toml` / 依赖列表**（核心依赖，非可选）。

---

## 八、`README.md`

更新或补足：

1. **Setup**：venv、可编辑安装、`pip install -e ".[dev]"` / `pip install -e ".[dev,gmail]"`（与现有说明一致）；配置来自 `.env`，由 **`Settings`** 校验。
2. **Gmail OAuth**：所需 scope 或指向 **`python -m app.main show-config`**（**脱敏输出**）查看路径、标签名、scopes。
3. **运行命令**：**`run-daily`**、**`preview-digest`**、**`show-config`**（长期保留）。其中 **`preview-digest`** 在 README 中**仅需基本用法**（示例命令与参数）；边界语义（**指定日无 digest**、**无正文**、退出码等）**不写进 README**，见 **第五节 §1–§2** 与 **`--help`**（**`--help` 须一并概括「无记录 / 无正文」失败与非零退出**）。
4. **开发里程碑工作流**：简述 M1–M6 职责边界（一至两行即可）。
5. **安全保证**：send 失败 / 质检失败时不归档源邮件；**`preview-digest`** 只读库且不改 Gmail；**`run_lock`** 防止并发重复跑；幂等语义（重复 **`run-daily`** 安全、可恢复）；**`show-config` 永不打印明文密钥**。

---

## 九、测试要求

1. **端到端 dry run**（本地 pytest，无真实网络）：
   - **Mock Gmail**（现有 fake service 模式）。
   - **Mock LLM**（inject **`Settings`** 或 fake client，**不**依赖篡改 **`OPENAI_API_KEY`** 环境变量）。
   - **Mock 或断言 send** 未真实发出（与现有 **`GmailSender`** fake 一致）。
2. **验证**：执行 **fetch → upsert → `run_daily`** 链路后，digest 按预期生成（或可接受 empty/skipped 分支）；**labels / archive 仅在 send 成功之后**。
3. **验证**：锁行为符合 **`RunLock`** 设计（含不误释他人锁）。
4. **`preview-digest`**：
   - 对同日多条 digest 仅输出 **`created_at` 最新**的一条的正文预览。
   - 若该行 **`body_html` 为空 / `NULL`**：须 **非零退出**、**stderr 友好提示**、**不向用户暴露未捕获异常的 traceback**（见第五节 §2）。
   - 若指定 UTC 日 **库中无任何 digest**：须同样 **非零退出**、**stderr 友好提示**，且无未捕获异常 traceback（见第五节 §1）。
5. **`show-config`**：**stdout 不包含**未脱敏的完整敏感值（见第三节）。
6. **`run-daily`**：**未设置收件人**时 **fail-fast**（可在 Settings 校验或 CLI 层断言）。
7. 删除或勿新增与已废弃的 **`retry-errors`** 相关的测试与文档描述。

---

## 十、交付清单（自检）

- [ ] **`Settings`**：**`pydantic-settings`** 单一装载；**无散落 `os.getenv` 读取密钥**。
- [ ] **`python -m app.main run-daily`**：校验通过后 **Gmail 拉取 → `upsert_email` → `DailyDigestAgent.run_daily()`**；**`DIGEST_RECIPIENT_EMAIL` 缺失则立刻失败**。
- [ ] **`python -m app.main preview-digest --date YYYY-MM-DD`**：UTC 当日最新一篇 digest HTML → stdout 或文件；无 send、无 Gmail 写操作；**选中行 `body_html` 为空 / `NULL` 或当日无 digest 时**：**非零退出 + stderr 友好提示**，**禁止未捕获异常 traceback**（第五节 §1–§2）；**`--help`** 含失败语义摘要；**README 仅基本用法**（第八节）。
- [ ] **`python -m app.main show-config`**：**长期保留**；敏感字段 **脱敏**；不测路径泄漏密钥文件内容。
- [ ] **`DAILY_DIGEST_MAX_QUALITY_GATE_ATTEMPTS`** 接入 **`Settings`** 与 **`DailyDigestAgent`**。
- [ ] **`.env.example`**、**`README.md`** 与 **`Settings`** 一致。
- [ ] 上述测试通过。

---

**本文档为 Milestone 6 唯一需求说明**；若与已实现代码冲突，以实现本文与既有数据库 / 状态约定对齐为准。
