# Milestone 5：DailyDigestAgent 编排、Digest 合成、质检门

**前提**：Milestone 1–4 已完成。实现前请先阅读现有代码：`app/storage/repository.py`、`app/storage/run_lock.py`、`app/storage/db.py`、`app/gmail/sender.py`、`app/gmail/labeler.py`、`app/agents/router_agent.py`、`app/models/outputs.py`、`app/models/digest.py`。

---

## 一、核心前置动作（必须先完成）

### 1. Schema 与 DB

- 将 `digests` 表中的 `body_markdown` 重命名为 **`body_html`**（类型仍为 TEXT，存 HTML 字符串）。
- 在 `digests` 表与 Pydantic 模型（`DigestRecord` 等）中新增 **`error_message`**（TEXT / `str | None`）。
- **`emails.status` 约定**：与现有 `StateRepository` 查询保持一致，使用**小写**字符串：`'pending'`、`'failed'`、**`'archived'`**（本里程碑新增归档态时亦用小写）。规格与测试禁止使用 `FAILED` / `ARCHIVED` 等大写常量若会与库内不一致。
- **已有 SQLite 文件兼容**：部署/开发环境中可能已有旧库。除更新 `_SCHEMA` 外，需有明确策略（例如启动时检测列名：`body_markdown` 存在则 `ALTER TABLE RENAME COLUMN`，或一次性迁移脚本），避免仅对新库生效。

### 2. `StateRepository` 扩展

- **`update_digest_body(digest_id, *, body_html, title=None)`**（或等价命名）：用于质检重试时覆盖正文；若仅更新正文与 `updated_at`，行为需与现有 `update_digest_status` 一致（时间戳等）。
- **`get_outputs_by_email_ids(email_ids: Sequence[int]) -> ...`** 契约如下：
  - 返回足以组稿的数据：至少包含 **`email_id`**、**`kind`**、**`payload`**（及如需排障的 `created_at` / `id`）。
  - **同 `(email_id, kind)` 多条记录时**：仅消费 **按 `created_at`（或 `id`）最新的一条**，或由本方法直接聚合为「每封邮件、每个 `kind` 至多一条」；实现方须在 docstring 中写死规则，**Composer 不得自行处理歧义**。
- **`create_digest`**：参数与 INSERT 列名与 **`body_html`** 对齐；删除对 `body_markdown` 的引用。

### 3. `RunLock` 安全释放

- **目标**：未在本实例成功 `acquire()` 的流程，**不得在 `finally` 中误删其他实例持有的锁**。
- **实现**：优先在 **`RunLock` 内**维护「本实例是否已 acquire」状态（或 release 时校验 owner / token）；并在类文档中写明：**未 acquire 调用 `release()` 为 no-op 或抛错**，禁止无条件 `DELETE`。
- 若采用调用方布尔标记，须在 `DailyDigestAgent` 中保证唯一路径，且仍建议在 `RunLock` 层加防护，避免未来误用。

### 4. 单封错误策略（不阻断全批次）

- 批处理中，某一封邮件在 **parse / route / processor** 任一步失败时：
  - 将该邮件 **`emails.status` 置为 `'failed'`**；
  - 使用现有 **`update_email_status(..., increment_retry=True)`**（或与 `fetch_retryable_errors` 语义一致的方式）更新 **`retry_count`**，以便未超次邮件仍可被后续运行捞起；
  - **跳过该封**，继续处理其余邮件。
- **Digest 仅包含成功处理并有有效结构化输出的邮件**；仅这些邮件参与 `digest_emails` 关联及 send 成功后的 Gmail 归档/打标。

### 5. 包路径

- 编排入口放在 **`app/agents/daily_digest_agent.py`**（与现有 `app/agents/` 统一，禁止使用 `app/agent/`）。

### 6. 新增目录结构

```
app/digest/
  composer.py
  quality_gate.py
  templates/
    daily_digest.html.j2
app/agents/
  daily_digest_agent.py
```

---

## 二、Milestone 5 功能要求

### 1. `DailyDigestAgent.run_daily()` 编排

1. **获取 run lock**：`acquire()` 失败则**安全退出**（不写 digest、不改邮件、不 send；**不得调用 `release()`**）。
2. **候选邮件**：合并 **`fetch_unprocessed_emails()`**（`pending`）与 **`fetch_retryable_errors()`**（`failed` 且未超次）；去重按 `email_id`。
3. 对候选逐封：**parse → route → 匹配 processor**；遵守第一节单封失败策略。
4. 每笔成功：**`save_agent_output`**（及必要的 router 输出落库，若当前架构如此）；**`attach_email_to_digest(digest_id, email_id)`** 仅针对本会进入 digest 的成功邮件（digest 行可先 `create_digest(status='draft', …)` 再处理，或先累积成功列表再创建——实现自选，但需保证关联一致）。
5. **空成功集**：若**没有任何一封**成功产出可组稿的输出：
   - **不调用 send**；
   - **不**对任何邮件执行 archive / `AI_DIGEST_PROCESSED` / 分类标签；
   - 可选：创建一条 `digests` 记录并标为 **`skipped` 或 `empty`**（若引入新状态须在本文档与模型中命名一致），或**不创建 digest**——**实现须在代码常量或注释中择一并写清楚**；测试需覆盖该分支的预期行为。
6. **`DigestComposer`**：仅依赖 **`get_outputs_by_email_ids`**（及组稿所需的元数据如 subject 若已在上游结构化输出中则不必再读全文），使用 **Jinja2** 渲染 **HTML**（模板语文可配置；默认 UI 文案为英文，与你的产品一致即可）。章节与分类映射固定为：

   | `RouteCategory` | 章节标题           |
   |-----------------|--------------------|
   | TECHNOLOGY      | Technical Index    |
   | RADAR           | AI Radar           |
   | LEADERSHIP      | Leadership Signals |
   | NOISE           | Filtered Noise     |

7. **质检**：`DigestQualityGateAgent` 检查 HTML（乱码、异常未转义的大段标记、明显结构破坏等）。**重试语义**：**初稿 + 最多 2 次根据 `problems` 的重写 = 最多 3 次生成**；第 3 次仍失败则抛出 **`QualityGateFailedException`**（或项目约定异常名）。
8. **Send**：质检通过后 **`GmailSender.send_html`**。
9. **仅在 send 成功之后**（对**成功进入 digest 的邮件**）：
   - `GmailLabeler.add_category(message_id, category)`；
   - `GmailLabeler.mark_processed(message_id)`（`AI_DIGEST_PROCESSED`）；
   - `GmailLabeler.archive(message_id)`；
   - DB：`emails.status` 更新为 **`'archived'`**（与第一节约定一致）。
10. **`finally`**：仅当本运行**已成功 `acquire()`** 时调用 **`release()`**。

### 2. Send 失败时的 digest 状态

- **Send 抛错或返回无效**：**不** archive、**不**打 `AI_DIGEST_PROCESSED`、**不**打分类标签。
- **持久化建议**：将对应 `digests.status` 置为可区分的状态（例如 **`'send_failed'`** 或 `'error'`，与质检失败区分或合并——**实现选定一种并在 `DigestRecord`/常量中固定**），并可在 **`error_message`** 中记录简短原因；**`body_html` 保留最后一次有效 HTML**。测试需覆盖「send 失败不 archive」。

### 3. 质检失败降级（`QualityGateFailedException`）

- **不** send digest；
- **不** archive 源邮件；
- **不**打 `AI_DIGEST_PROCESSED`（及不因本 digest 打分类标签）；
- 将 **`digests.status`** 置为 **`'error'`**（或与上节统一的错误态，但需能区分 **质检失败** vs **send 失败** 若产品需要；最小实现可共用 `'error'` 并在 `error_message` 前缀区分）；
- 持久化 **最后一次失败的 `body_html` 草稿** 与 **`error_message`**（含质检 `problems` 摘要或最后一次门禁返回文本）。

### 4. `DigestComposer`

- 仅使用 Repository 提供的结构化输出，**不重新读取邮件全文**。
- 输出为 **HTML**（模板 `app/digest/templates/daily_digest.html.j2`；标题/章节名等业务文案语言由模板与 `DigestComposer`/`DailyDigestAgent` 参数决定）。
- 质检失败后的重写：Composer 需能接受 **`problems: list[str]`（或约定类型）** 并生成修订版 HTML（由 `DailyDigestAgent` 驱动循环）。

### 5. `DigestQualityGateAgent`

- **推荐**：以**确定性规则**（解析 HTML、长度、可疑片段、未闭合标签等）为主，便于单元测试稳定；若辅以 LLM，**测试必须 stub**，避免 flaky。
- 返回结构明确：**`pass: bool`**，**`problems: list[str]`**（fail 时非空）。

---

## 三、测试要求（必测）

1. **Send 成功前**不会对源邮件 **`archive`**。
2. **Send 失败**不会对源邮件 **`archive`**（且不打 processed，与第二节一致）。
3. **质检**：超过 3 次尝试仍失败时，digest **`status`** 与 **`error_message`**、`body_html` 持久化符合第三节。
4. **Run lock**：未获得锁的实例运行结束时**不会清除**其他持有者写入的 `run_locks` 行（即不误释他人锁）。
5. **单封失败**：一批中一封处理失败为 `'failed'` 且**不影响**其余成功邮件进入同一 digest 的流程（或可测：最终 HTML/关联仅含成功邮件）。
6. **（推荐）** `digest_emails`：send 成功后，成功处理的 `email_id` 与本次 `digest_id` 关联正确。

---

## 四、参考文件（实现时对照）

- `app/gmail/labeler.py`：`PROCESSED_LABEL`、`category_label_name`、`archive` 语义。
- `app/gmail/sender.py`：send 成功判定。
- `app/models/outputs.py`：`RouteCategory` 与各 `*Output` 模型（Composer 反序列化 `payload`）。
- `app/storage/repository.py`：`fetch_unprocessed_emails` / `fetch_retryable_errors` / `attach_email_to_digest` / `update_email_status`。

---

**本文档为 Milestone 5 唯一需求说明**；实现时若有与本文冲突的局部代码，以本文与现有数据库查询约定对齐为准。
