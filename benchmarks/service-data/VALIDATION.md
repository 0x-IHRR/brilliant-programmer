# 内部软件验证范围

全部候选仍为AI起草、待人工核验。以下是受控模型回复驱动既有软件的结果，不是人工标签正确率或真实模型质量报告。

| 路径 | 已实际覆盖 | 不可外推 |
| --- | --- | --- |
| 纯契约 | 6家族×3档18例、36评分见证、逐题来源定位、实质变式及仅改名拒绝、机器拒绝伪人工签核；19通过 | 结构/引用不证明自然语言语义、档位或学习效果 |
| 独立API | 18例全档位，真实用户入口、私有生成、比较、原答、相关性和评分、10点、单次pass仍unverified；只落真实主target | 受控回复不能代表真实模型会生成/判准，也没有跨框架授证 |
| 普通API | 六家族基础档，明确错误但相关原答仍获同轮10点、逐项有据失败 | 未声称全部档位普通流程矩阵 |
| 变式/帮助API | api.boundary-1、data.integrity-1、async.cache-1：仅改名拒绝、真实条件变式接受、确认与交付分开、方向帮助实际交付后practice | 另外三个家族及高档帮助路径未作本批实际流程覆盖 |
| 浏览器 | 同上三个基础案例，普通键盘作答、反馈、主动新独立题、方向提示确认与receipt、练习反馈、返回原轮保原答、320px/200%字号无横溢 | 不等于全语言/框架、所有档位或真人理解验收 |

真实背景为api-evidence-v1、data-evidence-v1、async-evidence-v1。合成日志和外部结果不是官方运行记录；本地TLS服务器明确为受控转载，它传输完整原URL/version/locator/短摘录，生成callback逐字段检查真实请求。来源摘要与逐字引句分别标记，SHA只绑定读取响应，不证明结论正确。

## 可复现入口

从backend目录，使用本票专属数据库/worker串行运行，设置MAILPIT_URL和NO_PROXY；浏览器另设FRONTEND_HOST和PLAYWRIGHT_BASE_URL到本票API。

- `../.venv/bin/pytest tests/test_service_data_benchmarks.py --noconftest -q`：19通过。
- `../.venv/bin/pytest tests/test_service_data_api.py -q`：27通过，79.00s，仅既有Starlette弃用warning。
- `../.venv/bin/python -m tests.service_data_browser`：三个基础领域逐个运行真实Playwright；全部通过（每例1项，最终分别8.8s、8.7s、9.1s，以日志为准）。专属截图目录`/tmp/bp-issue-36-artifacts`，每例有ordinary/directional/200。

ruff、严格mypy93、前端build、7个自动保存unit通过。本阶段未运行整个后端全量；先等待#25共享GET一致性修复合并，不能以这次专项未触发该竞态宣称问题已修。专用spec无显式harness环境时跳过，不改公共CI或产品实现。

本批无#35未合并模块导入，沿main已有测试worker/provider和生产校验器。浏览器脚本沿已验证同类真实流程编排，以本批案例作为输入；没有新评测框架。

尚缺真人逐条核验与获授权后的真实模型质量证据。没有真实付费模型、真实对外发信或部署；只能部分关联#36，不能关闭Issue。
