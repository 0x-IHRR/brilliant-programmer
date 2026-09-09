# 可靠性基准候选 v0.1

本批为 #37 内部准备，不是完整验收。18个案例、36个标签及正反变式全部为AI起草，机器字段明确 `origin=ai_draft`、`review_status=pending_human_review`、`human_review=null`；标签也逐条待核。不得由 #40 作为人工基准导入，没有真人签名或真实模型成绩。

范围为测试/验证、性能/并发、部署/运维三个领域各两家族、基础/进阶/综合三档，复用 fullstack-v1.0.0 的 testing.coverage/bias、performance.bottleneck/capacity、operations.configuration/recovery 与既有背景及前置。每题一个联合判断，只记受考主能力，不把涉及组件全记通过。档位实质复杂度、标签语义与多解充分性仍需真人审查。

## 来源与假设

实际读取官方 Playwright、scikit-learn1.7.2、Google SRE书、Docker Compose、Kubernetes1.34和PostgreSQL17文档。读取日期2026-09-10，9份来源各保URL、版本/快照、完整响应SHA-256及具体章节定位；固定版本路径优先，滚动文档明确读取快照，不承诺版本永远兼容。

Source.text仅保存空白折叠后的短逐字摘录，[…]区分非连续片段；locator另有明确标注的AI中文摘要，保存限定条件且仍待核验，不能当原文引句。每个原题及变式分别选择相关片段，不默认引用首片。完整网页没有入库，SHA只绑定响应不证明推理。

时序、错误率、请求耗时、流量、备份日期与所有业务状态均为合成教学假设，不是官方文档实际观测的生产数据。Google SRE中的重试数字不移作本题硬阈值；部署回退不等数据恢复，PITR目标与WAL条件均保留。

`REVIEW.md`供真人逐条复核；JSON是精确冻结记录。检查来源适用性、假设冲突/缺项、可接受与错误标签、补证是否误标、变式因果变化和帮助方向。不确定就保留缺项/争议，不预签通过。正确结论允许先补证，不以术语匹配证明理解。

## 软件验证边界

本批只复用生产 Source/Candidate/Answer/GradingCandidate 与 validate_candidate、validate_grading、assess_novelty；载入封装仅约束审阅元数据，未新增评分系统或 #40 runner。没有导入 #35/#36 未合并模块，也没有修改公共目录/API/worker/evidence。

从backend运行 `../.venv/bin/pytest tests/test_reliability_benchmarks.py --noconftest -q`。19项检查覆盖矩阵、36评分见证、逐题引句映射、实质变化候选、仅改名拒绝和伪人工状态拒绝。纯通过仅代表契约检查，不证明自然语言质量。真实受控API/UI尚待本票后续新增验证；source完整URL/version/locator/text必须进入实际请求，不能只转发短引而丢规则限定。

完整验收还缺18份人工核验、36份人工标签依据与明确授权后的真实模型质量证据。只发布实际测过的语言/框架范围，本批不宣称通用兼容、职业认证或学习效果。无真实付费模型、真实对外邮件、联系他人或部署；部分PR只能Refs #37，不能Closes。
