# 内部软件验证范围

所有候选与标签仍为AI起草、待人工核验。受控模型返回预设候选，仅用于检查生产流程，不是人工真值、真实模型成绩或教学效果证明。

| 路径 | 本批实际范围 | 不能外推 |
| --- | --- | --- |
| 纯契约 | 六家族×三档18例、36评分见证、逐原题/变式引用定位、真实条件变式及仅改名拒绝、伪人工状态拒绝；19通过 | 结构和绑定不证明语义正确或档位充分 |
| 独立API | 全18例真实入口/队列/TLS、原答/相关性/评分、10点、单pass仍未验证、仅实际主target落证据 | 不代表真实模型会生成或判准，也不授其他背景能力 |
| 普通API | 六家族基础档，明确错误但相关原答保同轮10点并显示逐项失败 | 不覆盖全部档位普通矩阵 |
| 变式/帮助API | requirements.acceptance-1、architecture.responsibility-1、team.review-1：已见仅改名拒绝、实质变化接受、确认不等交付、方向帮助receipt后按练习记录 | 其他三个家族及高档帮助路径不在本批矩阵 |
| 浏览器 | 同上三个基础案例，键盘、普通反馈、主动独立新题、方向提示确认/回执、练习反馈、返回原轮保原答、320px/200%字号 | 不代表所有语言/框架、档位或真人理解验收 |

绑定requirements-evidence-v1、architecture-evidence-v1、team-evidence-v1。角色、业务状态和验证结果均为合成假设。受控TLS转载明确不是官方服务器，传输完整原URL/version/locator/text；生成callback逐字段核实际请求，保存摘要适用边界而非只传短引句。

## 复现与结果

从backend目录使用本票专属数据库，DB/worker/browser串行。MAILPIT_URL与NO_PROXY指向本票；浏览器另设置FRONTEND_HOST、PLAYWRIGHT_BASE_URL。

- `../.venv/bin/pytest tests/test_engineering_benchmarks.py --noconftest -q`：19通过，0.24s。
- `../.venv/bin/pytest tests/test_engineering_api.py -q`：27通过，43.25s，只有既有Starlette弃用warning。首轮9通过/18失败来自本票字段误重命名semantic_engineering，修回生产semantic_reliability后保原断言通过。
- `../.venv/bin/python -m tests.engineering_browser`：三个基础流程串行通过，requirements.acceptance-1 8.3s、architecture.responsibility-1 8.2s、team.review-1 7.9s。截图独立保存至`/tmp/bp-issue-38-artifacts`，每例ordinary/directional/200。

ruff、严格mypy93、build及7个自动保存unit（3.90s）通过。未先重复后端全量，按协调等待#25共享GET一致性修复合并后再收口；专项未触发竞态不等于问题已修。本票不改共享产品或CI，专用spec无显式harness环境时跳过。

测试代码以本批材料为输入，复用main已有worker/provider及生产校验器，没有导入35–37未合并模块或创建新评测体系。真实可用语言/框架矩阵仍需人工与真实模型证据。

完整验收仍缺真人逐条核验及获授权后的真实模型质量评测；没有真实付费调用、对外邮件、联系他人或部署。仅部分Refs #38，不Closes。
