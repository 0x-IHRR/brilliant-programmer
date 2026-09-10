# 内部软件验证范围

全部材料与24标签仍为AI起草、待人工核验。受控模型返回预设候选，只验证真实软件路径，不是人工真值、真实模型成绩或教学效果证明。

| 路径 | 范围 | 限制 |
| --- | --- | --- |
| 纯契约 | 12逐例生产Candidate/Grading/novelty契约、两域三档矩阵/伪human状态拒绝、安全家族实际target映射；14通过 | 结构和引用绑定不证明语义正确 |
| 独立API | 12原题全档，真实入口/queue/TLS/原答/评分，10点、单pass未验证、semantic_reliability未验证、仅主target | 不代表模型实际能生成或判准 |
| 普通API | 四家族基础，明确错但相关原答保10点、有据失败 | 未覆盖高档普通、secrets综合错误API |
| 帮助API | ai.grounding-1、security.authorization-1，已见改名拒绝、实质变式接受、确认不等交付、directional receipt后practice | 不覆盖其他家族/高档帮助 |
| 浏览器 | 同两个基础案例，键盘、普通反馈、主动独立轮、方向帮助、原答恢复、320px/200%字号 | 不泛称全语言/框架/档位可用 |

真实受控TLS正文明确不是上游官方服务，逐字段传输并断言来源url/version/locator/text，包含引用以外的适用限定。教学政策/权限/运行事实不冒官方观测。能力键使用ai-evidence-v1/security-evidence-v1，security.boundary不成为虚拟能力。

从backend目录、本票独立数据库运行，DB/worker/browser串行；MAILPIT_URL/NO_PROXY与FRONTEND_HOST/PLAYWRIGHT_BASE_URL使用本票地址。

- `../.venv/bin/pytest tests/test_ai_security_benchmarks.py --noconftest -q`：14通过1.63s；秘密配置文案澄清后14通过0.21s。
- `../.venv/bin/pytest tests/test_ai_security_api.py -q`：18通过32.41s，仅既有Starlette弃用warning；该轮加载澄清前材料，改动的secrets综合变式不在本轮受测路径。
- `../.venv/bin/python -m tests.ai_security_browser`：两个基础流程串行通过，ai.grounding-1 8.5s、security.authorization-1 7.7s；截图独立保存在`/tmp/bp-issue-39-artifacts`，每例ordinary/directional/200。

ruff、严格mypy99、build与7unit（3.87s）通过。新环境从空库迁移到0022_score_review并执行既有initial_data。尚未本地重复完整后端集合，最终同HEAD CI结果另记。专用browser spec没有harness环境时跳过，不修改共享CI，也没有导入35–38未合并模块。

完整验收仍缺真人逐条核验和授权后的真实模型质量评测。没有真实付费模型、对外邮件、联系他人或部署。内部部分draft仅Refs #39，不Closes。
