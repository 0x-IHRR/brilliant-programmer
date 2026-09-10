# AI与安全候选核验材料

内部准备，Refs #39。12个候选、24份答案标签均为AI起草，机器字段`origin=ai_draft`、`review_status=pending_human_review`、`human_review=null`；每个答案单独标待核验。没有真人签核或真实模型成绩。生产schema校验、AI审查和受控fixture不证明标签正确或教学效果。

| 候选家族 | 基础 / 进阶 / 综合 | 实际主能力 |
| --- | --- | --- |
| ai.grounding | 引用与主张 / 切片例外与补证 / 来源冲突、版本与权限 | ai.grounding |
| ai.tools | 参数与授权 / 外部指令与原意 / 高风险确认与授权撤销 | ai.tools |
| security.authorization | 登录与资源归属 / 批量与动作 / 后台导出与下载边界 | security.authorization |
| security.boundary | 纯文本和URL输出 / 重定向和DNS出站 / 泄露撤销与日志 | 基础、进阶为security.input；综合为security.secrets |

每领域每档两家族，共12例；不是18例。security.boundary仅为本批候选家族标签，不是新能力；原题与变式target均取现有目录。绑定fullstack-v1.0.0、ai-evidence-v1或security-evidence-v1，不修改目录及前置。单题一个明确联合判断只给主key证据，提及其他领域不顺带授证。未覆盖security.secrets低档、security.input综合及全语言/框架，不冒称这些格已验收。

`candidates.json`复用生产Candidate/Answer/GradingCandidate；`sources.json`复用Source；`REVIEW.md`展开逐条待核原题、变式、来源、反例与帮助边界。来源仅支持规范规则；案例中的政策、日志、角色、权限状态及运行结果全部是明确合成假设，官方文档未观测本题系统。正确补证判断保为可接受候选，不将缺运行事实自动当学习者错误。参考选项是一个可接受见证，符合冻结约束的其他方案及白话理由也应接受，不能用逐字匹配或关键词判分。

实际读取日期2026-09-10：Azure RAG滚动文档保存响应SHA；OWASP页面直接抓取403后改读其官方仓库固定commit的Markdown，Source.url保存实际成功地址，version保存commit及响应SHA。只摘短句，完整适用边界在明确标记为AI中文改写的locator；SHA/引用结构不是语义认证。传输给受控模型必须保完整url/version/locator/text，不只取首段引句。OWASP示例过滤器没有被复制为生产防线，不把单一过滤、分隔符或模型投票当注入免疫。

安全错误见证绑定真实边界：跨账号API/下载、批量逐项及动作权限、后台撤销、HTML/URL上下文、SSRF重定向/DNS、泄露后撤销及明文日志。材料仅自然语言描述，不提供可执行攻击脚本，不触真实目标或凭据。每题实质变式改变可定位事实及对应行动理由；仅改标题而保事实/规则的负例不得当陌生检验。neutral/directional/uncertain均为待核帮助样本；真实资格仍依据实际内容检查与交付事实，确认不等于交付。

backend目录运行`../.venv/bin/pytest tests/test_ai_security_benchmarks.py --noconftest -q`：12逐例生产契约/变式、矩阵状态及特定target映射，共14项。逐case原/变式引用检查只防编辑错绑，不能认证自然语言真值。真实受控API/UI在后续独立test文件记录范围，普通和帮助不外推所有档位。

仍需真人逐条核验来源适用性、假设充分性、标签、多解/补证、档位和帮助方向；真实模型质量须有授权后的实际证据。没有真实付费调用、对外发信、联系他人或部署。内部部分仅draft Refs #39，不Closes，不是固定循环题库或#40完整评测runner。
