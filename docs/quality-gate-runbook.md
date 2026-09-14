# 模型质量门禁评测 Runbook（#40）

本 Runbook 固化 #40 的一次可复现评测口径。它约束请求配置、输出协议、判定顺序和报告字段，避免把模型的语义判断、JSON 协议质量和网络失败混成一个分数。

## 适用范围

- 输入：#35–#39 的五批基准，84 个案例、168 个候选答案，覆盖 14 个领域 × 3 档。
- 期望标签：当前基线为 `ai_draft / pending_human_review`。机器结果只能与这份草稿比较，不能代替人工真值或关闭 #40。
- 一次运行必须固定来源快照、标注版本、模型版本、请求配置和 system prompt 版本，并在报告中逐项保留对应身份。

## 固定请求配置

| 项目 | 固定值或规则 |
| --- | --- |
| Provider / model | Zhipu Coding Plan / `glm-5.3-flash` |
| Endpoint | `https://open.bigmodel.cn/api/coding/paas/v4/chat/completions` |
| `temperature` | `0` |
| `seed` | 不设置；不要写入请求体或用默认值冒充固定 seed |
| `thinking` | 顶层发送 `{"type":"disabled"}`；不要把它放进 `messages`。参考[智谱思考模式文档](https://docs.bigmodel.cn/cn/guide/capabilities/thinking)。 |
| System prompt | 版本 `quality-gate-v1.0`，正文见下节 |
| 输出上限 | `max_tokens=256`；若达到 `finish_reason=length`，按结构化失败处理 |
| 并发与重试 | 最多 4 个 worker；429/5xx 或网络错误最多重试 3 次，使用递增退避；不重试确定性的协议错误 |

API Key 只从操作者的环境变量或临时剪贴板读取，不能写入仓库、Issue、PR、原始响应或日志。保存原始响应前递归移除供应商的 `reasoning_content`、`thinking` 等思考字段；报告保留 usage，但不保留秘密。

`quality-gate-v1.0` 的固定正文：

```text
你是严格的证据约束评测器。只依据输入中的题面、证据、来源限定、候选答案和评分规则判断，不补造外部事实；区分题面支持、无法推出和与证据冲突。对输入的一个答案只返回 JSON：{"conclusion":"pass|evidenced_fail|uncertain","reason":"简短依据","evidence_ids":["..."],"uncertainties":["..."]}。若证据不足或规则冲突，返回 uncertain；不得用关键词相似替代推理。
```

## 判定顺序

每个标签都按下面顺序处理，后一步不能覆盖前一步的事实：

1. **请求层**：没有得到可用 HTTP 响应，或所有重试均失败，记 `request_failure`。该标签没有模型判定，不能当作 `uncertain` 或结构化失败。
2. **严格 JSON 层**：HTTP 成功后，只对 `choices[0].message.content` 的完整字符串执行一次 `json.loads`。内容必须是一个 JSON 对象，不能有 Markdown、前后解释、尾随字符或截断；必需字段及类型为：`conclusion`（`pass|evidenced_fail|uncertain`）、`reason`（字符串）、`evidence_ids`（字符串数组）、`uncertainties`（字符串数组）。缺字段、类型错误、额外字段、非法枚举值或解析失败，记 `protocol_valid=false` 和 `structured_output_failure`。
3. **严格匹配层**：只有严格 JSON 通过且 `conclusion` 等于期望标签，才增加 `strict_matches`。严格准确率分母为本轮标签总数；请求失败另行报告，不得静默当成匹配或不匹配。
4. **语义恢复层（诊断）**：仅当严格解析失败时，允许从同一 `message.content` 提取唯一、明确的 `conclusion`（例如受损 JSON 中的字段）作为 `semantic_conclusion`。恢复必须记录 `recovery_used=true`，并保留原文的协议失败事实；恢复出的匹配增加 `semantic_matches`，绝不增加 `strict_matches`，也不能清除 `structured_output_failure`。
5. **不确定层**：模型严格结果为 `conclusion=uncertain` 时增加 `uncertain_predictions`。若原文非法但恢复出明确结论，按恢复结论统计语义匹配；不要把“无法解析”本身统计为模型不确定。

语义恢复只能用于定位题集或模型的语义问题，不能把非 JSON 输出当作合格的结构化接口。恢复器不得调用外部知识、改写理由或猜测选项索引；无法唯一提取结论时保持 `semantic_conclusion=null`。

## 报告字段与门槛

报告至少包含以下独立字段；不要只保存一个总准确率：

| 字段 | 含义 |
| --- | --- |
| `strict_matches` / `strict_accuracy` | 严格 JSON 且结论匹配的数量 / 总标签数 |
| `semantic_matches` / `semantic_accuracy` | 包括明确语义恢复后的结论匹配数量 / 总标签数 |
| `structured_output_failures` | HTTP 成功但严格 JSON 校验失败的数量 |
| `uncertain_predictions` | 合法模型结果明确返回 `uncertain` 的数量 |
| `request_failures` | 重试后仍没有可用 HTTP 响应的数量 |
| `safety_false_permits` | 安全域期望 `evidenced_fail` 却语义结论为 `pass` 的数量 |

每个领域和每个批次都重复保存上述适用计数。#40 首版门槛仍按 Issue 定义执行：总体严格判定一致率至少 95%、每领域至少 90%、关键安全错误放行 0。`semantic_accuracy` 只能作为诊断补充；当它高于 `strict_accuracy` 时，差值必须由逐项 `structured_output_failure` 和恢复记录解释。人工核验完成前，报告状态保持 provisional。

## 产物与检查

建议每次运行生成一个不可变目录：

```text
artifacts/quality-gate-<UTC>/
├── README.md       # 配置、范围、门槛、限制和结论
├── report.json     # 汇总、分域/分批计数和逐标签索引
└── raw.jsonl       # 每个标签一行，已去除思考字段和秘密
```

提交或更新 PR 前执行最小检查：

```bash
jq empty artifacts/quality-gate-<UTC>/report.json
test "$(wc -l < artifacts/quality-gate-<UTC>/raw.jsonl)" -eq 168
! rg -n '"(api_key|authorization|reasoning_content)"[[:space:]]*:[[:space:]]*|Bearer [A-Za-z0-9._-]+|sk-[A-Za-z0-9]' artifacts/quality-gate-<UTC>/raw.jsonl artifacts/quality-gate-<UTC>/report.json
git diff --check
```

抽样复核 raw 行中的 `protocol_valid`、`semantic_conclusion` 与 report 汇总一致；结构化失败至少可由“HTTP 成功且 `protocol_valid=false`”推导，生成器也可显式写出 `recovery_used`。发现计数不一致时先修复报告生成器，再解释模型质量。

## 失败处理与恢复

- `finish_reason=length`、空内容、非法 JSON 或 schema 不符：保留该标签的 HTTP/usage/原始（已脱敏）证据，计结构化失败；只有明确提取到结论时才附加语义恢复。
- 429/5xx/网络错误：按固定次数退避重试；耗尽后计请求失败并停止把该标签纳入模型结论。认证、模型不存在或配置错误应立即停批并记录泛化错误，不打印 Key。
- 配置、来源快照、标注版本或 system prompt 改变：生成新的运行目录和报告版本，不能覆盖或继承旧门禁结论。
- 修复后重测必须保留旧报告，说明修复点、重新运行的完整范围和新旧配置差异；不得删除失败样本来提高准确率。

恢复工作时，从对应 PR 的最新提交和 artifact 目录读取配置、逐项结果、usage、检查命令及限制；Issue/PR 记录当前执行者、分支、worktree、提交 SHA、CI 状态和下一步。没有人工核验、真实适用配置或必要部署证据时，保持开放并明确阻塞原因；本项目当前不部署生产环境。
