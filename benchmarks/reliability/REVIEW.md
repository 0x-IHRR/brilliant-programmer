# 逐条人工复核待办

全部为 AI 草稿，尚无人类签核。以下便于审阅，JSON保留完整结构；此清单不自动认可标签。

## testing.coverage-1 — 保存按钮亮起能证明什么

状态：pending_human_review；技术背景：testing-evidence-v1；档位：基础

**原题**

验收要求刷新后保留草稿；测试仅断言保存按钮变灰，未等待服务响应或重新读取。

可接受：补保存成功响应和刷新后实际恢复内容的检查。

明确错误：按钮变灰就宣布持久保存通过。

依据候选：内部按钮状态不足以证明刷新后的用户行为契约，需观察真正保存与恢复。

反例：反例：验收要求刷新后保留草稿；测试仅断言保存按钮变灰，未等待服务响应或重新读取。 因此“按钮变灰就宣布持久保存通过。”不成立。

来源：[playwright](https://playwright.dev/docs/best-practices)；Playwright best practices; response-sha256:40566088678afc665d5f604ec0f38239337f3112e6bde76e77189ee17ca3f108；Playwright best practices, snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：测试关注用户可观察行为及明确契约，不以内部函数或样式名替代验收；测试数据/会话隔离。网页断言等待所需条件，不用一次即时查询证明异步结果。真实服务持久性仍须按本题契约另验。

本判断短引定位：avoid relying on implementation details

**实质变式候选**

已等待保存200并重新读取同版本内容一致；缺失的是保存失败后输入保留路径。

可接受：保留成功路径，新增明确保存失败时本地输入仍在的验收。

明确错误：按钮变灰就宣布持久保存通过。

依据候选：已有持久成功证据不需抹去，但不能覆盖尚未测的失败恢复。

反例：反例：已等待保存200并重新读取同版本内容一致；缺失的是保存失败后输入保留路径。 因此“按钮变灰就宣布持久保存通过。”不成立。

来源：[playwright](https://playwright.dev/docs/best-practices)；Playwright best practices; response-sha256:40566088678afc665d5f604ec0f38239337f3112e6bde76e77189ee17ca3f108；Playwright best practices, snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：测试关注用户可观察行为及明确契约，不以内部函数或样式名替代验收；测试数据/会话隔离。网页断言等待所需条件，不用一次即时查询证明异步结果。真实服务持久性仍须按本题契约另验。

本判断短引定位：avoid relying on implementation details

变化依据：由“验收要求刷新后保留草稿；测试仅断言保存按钮变灰，未等待服务响应或重新读取。”变为“已等待保存200并重新读取同版本内容一致；缺失的是保存失败后输入保留路径。”，故“补保存成功响应和刷新后实际恢复内容的检查。”改为“保留成功路径，新增明确保存失败时本地输入仍在的验收。”。

仅改名反例：保存按钮亮起能证明什么（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：内部按钮状态不足以证明刷新后的用户行为契约，需观察真正保存与恢复。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## testing.coverage-2 — 迟到提示与即时断言

状态：pending_human_review；技术背景：testing-evidence-v1；档位：进阶

**原题**

点击提交后提示在网络响应后显示；测试立即查询一次可见性并失败，受控响应尚未释放。

可接受：用响应/条件屏障建立时序，再等待提示可见，保留结果断言。

明确错误：加固定长sleep并删掉提示断言。

依据候选：异步条件尚未满足不等于功能失败，等待真实条件能保留契约而不凭时间猜。

反例：反例：点击提交后提示在网络响应后显示；测试立即查询一次可见性并失败，受控响应尚未释放。 因此“加固定长sleep并删掉提示断言。”不成立。

来源：[playwright](https://playwright.dev/docs/best-practices)；Playwright best practices; response-sha256:40566088678afc665d5f604ec0f38239337f3112e6bde76e77189ee17ca3f108；Playwright best practices, snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：测试关注用户可观察行为及明确契约，不以内部函数或样式名替代验收；测试数据/会话隔离。网页断言等待所需条件，不用一次即时查询证明异步结果。真实服务持久性仍须按本题契约另验。

本判断短引定位：wait and retry if needed

**实质变式候选**

受控响应已明确失败，页面错误提示可见但输入被清空，验收要求失败保输入。

可接受：保错误反馈断言并报告输入丢失，不再延长等待掩盖缺陷。

明确错误：加固定长sleep并删掉提示断言。

依据候选：等待条件已确定，实际持久输入行为与要求冲突，不属于尚未就绪。

反例：反例：受控响应已明确失败，页面错误提示可见但输入被清空，验收要求失败保输入。 因此“加固定长sleep并删掉提示断言。”不成立。

来源：[playwright](https://playwright.dev/docs/best-practices)；Playwright best practices; response-sha256:40566088678afc665d5f604ec0f38239337f3112e6bde76e77189ee17ca3f108；Playwright best practices, snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：测试关注用户可观察行为及明确契约，不以内部函数或样式名替代验收；测试数据/会话隔离。网页断言等待所需条件，不用一次即时查询证明异步结果。真实服务持久性仍须按本题契约另验。

本判断短引定位：wait and retry if needed

变化依据：由“点击提交后提示在网络响应后显示；测试立即查询一次可见性并失败，受控响应尚未释放。”变为“受控响应已明确失败，页面错误提示可见但输入被清空，验收要求失败保输入。”，故“用响应/条件屏障建立时序，再等待提示可见，保留结果断言。”改为“保错误反馈断言并报告输入丢失，不再延长等待掩盖缺陷。”。

仅改名反例：迟到提示与即时断言（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：异步条件尚未满足不等于功能失败，等待真实条件能保留契约而不凭时间猜。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## testing.coverage-3 — 跨账号测试共用会话

状态：pending_human_review；技术背景：testing-evidence-v1；档位：综合

**原题**

退出旧会话后应拒绝旧token；测试A/B共用storage，B的登录替换了A凭据，旧token从未再次调用API。

可接受：隔离两账号会话，保存A旧token并实际请求受保护端点核拒绝，同时验证B合法访问。

明确错误：B能登录就证明A旧token失效且无跨用户泄漏。

依据候选：共享测试状态污染了被测身份，必须按明确会话契约分别观察。

反例：反例：退出旧会话后应拒绝旧token；测试A/B共用storage，B的登录替换了A凭据，旧token从未再次调用API。 因此“B能登录就证明A旧token失效且无跨用户泄漏。”不成立。

来源：[playwright](https://playwright.dev/docs/best-practices)；Playwright best practices; response-sha256:40566088678afc665d5f604ec0f38239337f3112e6bde76e77189ee17ca3f108；Playwright best practices, snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：测试关注用户可观察行为及明确契约，不以内部函数或样式名替代验收；测试数据/会话隔离。网页断言等待所需条件，不用一次即时查询证明异步结果。真实服务持久性仍须按本题契约另验。

本判断短引定位：Each test should be completely isolated from another test

**实质变式候选**

两账号已隔离，A旧token确实401；B合法写入失败后其本地输入消失，A数据未改。

可接受：保已证实会话隔离结论，另测B失败恢复与原记录不变，不把问题归为旧token绕过。

明确错误：B能登录就证明A旧token失效且无跨用户泄漏。

依据候选：身份和数据边界已有证据，新增失败属于不同的用户可观察恢复契约。

反例：反例：两账号已隔离，A旧token确实401；B合法写入失败后其本地输入消失，A数据未改。 因此“B能登录就证明A旧token失效且无跨用户泄漏。”不成立。

来源：[playwright](https://playwright.dev/docs/best-practices)；Playwright best practices; response-sha256:40566088678afc665d5f604ec0f38239337f3112e6bde76e77189ee17ca3f108；Playwright best practices, snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：测试关注用户可观察行为及明确契约，不以内部函数或样式名替代验收；测试数据/会话隔离。网页断言等待所需条件，不用一次即时查询证明异步结果。真实服务持久性仍须按本题契约另验。

本判断短引定位：Each test should be completely isolated from another test

变化依据：由“退出旧会话后应拒绝旧token；测试A/B共用storage，B的登录替换了A凭据，旧token从未再次调用API。”变为“两账号已隔离，A旧token确实401；B合法写入失败后其本地输入消失，A数据未改。”，故“隔离两账号会话，保存A旧token并实际请求受保护端点核拒绝，同时验证B合法访问。”改为“保已证实会话隔离结论，另测B失败恢复与原记录不变，不把问题归为旧token绕过。”。

仅改名反例：跨账号测试共用会话（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：共享测试状态污染了被测身份，必须按明确会话契约分别观察。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## testing.bias-1 — 拿训练分数当陌生表现

状态：pending_human_review；技术背景：testing-evidence-v1；档位：基础

**原题**

模型在训练样本上得到99%；没有独立测试集，目标是预测未见样本。

可接受：保留训练结果但补未参与选择的测试集评价，当前泛化尚未证明。

明确错误：99%训练分数可直接宣传所有陌生样本准确率。

依据候选：测试数据不能参与模型选择，训练表现不足以估计未见数据。

反例：反例：模型在训练样本上得到99%；没有独立测试集，目标是预测未见样本。 因此“99%训练分数可直接宣传所有陌生样本准确率。”不成立。

来源：[pitfalls](https://scikit-learn.org/1.7/common_pitfalls.html)；scikit-learn1.7.2 Common pitfalls §11.2; response-sha256:d565b1ef30e88ce406c27d28a02bc5a61af28cd65f2c6959676dbfb3509f807b；scikit-learn1.7.2 Common pitfalls §11.2。规范摘要（AI中文改写，待人工核验，非逐字引句）：测试集不用于模型选择；先划分再拟合预处理，只在训练集学习变换并同样应用于测试集。一次分数不能证明其他分布有效。

本判断短引定位：Test data should never be used to make choices about the model

**实质变式候选**

已冻结独立同分布测试集并完成一次评价；目标新增了另一设备分布但该分布无样本。

可接受：仅报告已测同分布结果，另补目标设备分布样本，不自动外推。

明确错误：99%训练分数可直接宣传所有陌生样本准确率。

依据候选：独立测试成立也只覆盖实际抽样分布，改变目标需新证据。

反例：反例：已冻结独立同分布测试集并完成一次评价；目标新增了另一设备分布但该分布无样本。 因此“99%训练分数可直接宣传所有陌生样本准确率。”不成立。

来源：[pitfalls](https://scikit-learn.org/1.7/common_pitfalls.html)；scikit-learn1.7.2 Common pitfalls §11.2; response-sha256:d565b1ef30e88ce406c27d28a02bc5a61af28cd65f2c6959676dbfb3509f807b；scikit-learn1.7.2 Common pitfalls §11.2。规范摘要（AI中文改写，待人工核验，非逐字引句）：测试集不用于模型选择；先划分再拟合预处理，只在训练集学习变换并同样应用于测试集。一次分数不能证明其他分布有效。

本判断短引定位：Test data should never be used to make choices about the model

变化依据：由“模型在训练样本上得到99%；没有独立测试集，目标是预测未见样本。”变为“已冻结独立同分布测试集并完成一次评价；目标新增了另一设备分布但该分布无样本。”，故“保留训练结果但补未参与选择的测试集评价，当前泛化尚未证明。”改为“仅报告已测同分布结果，另补目标设备分布样本，不自动外推。”。

仅改名反例：拿训练分数当陌生表现（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：测试数据不能参与模型选择，训练表现不足以估计未见数据。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## testing.bias-2 — 先全量归一化再切分

状态：pending_human_review；技术背景：testing-evidence-v1；档位：进阶

**原题**

先用全部数据拟合归一化均值，再随机拆训练/测试并调模型，测试样本影响了变换。

可接受：先切分，仅在训练数据拟合变换，再对测试数据应用该变换重评。

明确错误：归一化没有标签所以不可能造成测试信息泄漏。

依据候选：预处理也会从数据学习，测试数据参与拟合会污染独立评价。

反例：反例：先用全部数据拟合归一化均值，再随机拆训练/测试并调模型，测试样本影响了变换。 因此“归一化没有标签所以不可能造成测试信息泄漏。”不成立。

来源：[pitfalls](https://scikit-learn.org/1.7/common_pitfalls.html)；scikit-learn1.7.2 Common pitfalls §11.2; response-sha256:d565b1ef30e88ce406c27d28a02bc5a61af28cd65f2c6959676dbfb3509f807b；scikit-learn1.7.2 Common pitfalls §11.2。规范摘要（AI中文改写，待人工核验，非逐字引句）：测试集不用于模型选择；先划分再拟合预处理，只在训练集学习变换并同样应用于测试集。一次分数不能证明其他分布有效。

本判断短引定位：split the data into train and test subsets first

**实质变式候选**

归一化已仅fit训练集，但模型每次调参都根据同一测试集得分挑选。

可接受：保预处理边界，另用验证集选参并保最终测试集未参与选择。

明确错误：归一化没有标签所以不可能造成测试信息泄漏。

依据候选：变换泄漏已移除，重复使用测试分数选模型仍会破坏最终评价独立性。

反例：反例：归一化已仅fit训练集，但模型每次调参都根据同一测试集得分挑选。 因此“归一化没有标签所以不可能造成测试信息泄漏。”不成立。

来源：[pitfalls](https://scikit-learn.org/1.7/common_pitfalls.html)；scikit-learn1.7.2 Common pitfalls §11.2; response-sha256:d565b1ef30e88ce406c27d28a02bc5a61af28cd65f2c6959676dbfb3509f807b；scikit-learn1.7.2 Common pitfalls §11.2。规范摘要（AI中文改写，待人工核验，非逐字引句）：测试集不用于模型选择；先划分再拟合预处理，只在训练集学习变换并同样应用于测试集。一次分数不能证明其他分布有效。

本判断短引定位：Test data should never be used to make choices about the model

变化依据：由“先用全部数据拟合归一化均值，再随机拆训练/测试并调模型，测试样本影响了变换。”变为“归一化已仅fit训练集，但模型每次调参都根据同一测试集得分挑选。”，故“先切分，仅在训练数据拟合变换，再对测试数据应用该变换重评。”改为“保预处理边界，另用验证集选参并保最终测试集未参与选择。”。

仅改名反例：先全量归一化再切分（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：预处理也会从数据学习，测试数据参与拟合会污染独立评价。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## testing.bias-3 — 同主体随机拆分与未来部署

状态：pending_human_review；技术背景：testing-evidence-v1；档位：综合

**原题**

每台设备有多条近似记录，随机按行拆分使同设备进入训练和测试；目标是预测未见设备。

可接受：按设备组隔离再评估，不能用同设备随机拆分成绩代表新设备。

明确错误：随机打乱足够充分，所以同设备重复不影响未见设备结论。

依据候选：分组结构使样本不独立，目标未见主体需要对应的组隔离。

反例：反例：每台设备有多条近似记录，随机按行拆分使同设备进入训练和测试；目标是预测未见设备。 因此“随机打乱足够充分，所以同设备重复不影响未见设备结论。”不成立。

来源：[cross](https://scikit-learn.org/1.7/modules/cross_validation.html)；scikit-learn1.7.2 Cross validation §3.1.2; response-sha256:a3dfd7d11c008eebad9f56bc0f68605554e769d8147a7cf23f1a15df95ca0643；scikit-learn1.7.2 Cross validation §3.1.2。规范摘要（AI中文改写，待人工核验，非逐字引句）：同主体多样本宜按组隔离；时间依赖过程宜用时间序列感知切分。普通随机切分不自动满足组/时间独立性；选择须服从目标部署分布。

本判断短引定位：same subject is never in both testing and training

**实质变式候选**

目标改为已知设备的未来时段，所有训练记录须早于测试；随机组拆分却打乱时间。

可接受：按目标保时间顺序评价未来时段，并说明是否还需设备分组条件。

明确错误：随机打乱足够充分，所以同设备重复不影响未见设备结论。

依据候选：新的部署目标强调时间依赖，不能把组隔离自动当未来时间验证。

反例：反例：目标改为已知设备的未来时段，所有训练记录须早于测试；随机组拆分却打乱时间。 因此“随机打乱足够充分，所以同设备重复不影响未见设备结论。”不成立。

来源：[cross](https://scikit-learn.org/1.7/modules/cross_validation.html)；scikit-learn1.7.2 Cross validation §3.1.2; response-sha256:a3dfd7d11c008eebad9f56bc0f68605554e769d8147a7cf23f1a15df95ca0643；scikit-learn1.7.2 Cross validation §3.1.2。规范摘要（AI中文改写，待人工核验，非逐字引句）：同主体多样本宜按组隔离；时间依赖过程宜用时间序列感知切分。普通随机切分不自动满足组/时间独立性；选择须服从目标部署分布。

本判断短引定位：time-series aware cross-validation scheme

变化依据：由“每台设备有多条近似记录，随机按行拆分使同设备进入训练和测试；目标是预测未见设备。”变为“目标改为已知设备的未来时段，所有训练记录须早于测试；随机组拆分却打乱时间。”，故“按设备组隔离再评估，不能用同设备随机拆分成绩代表新设备。”改为“按目标保时间顺序评价未来时段，并说明是否还需设备分组条件。”。

仅改名反例：同主体随机拆分与未来部署（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：分组结构使样本不独立，目标未见主体需要对应的组隔离。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## performance.bottleneck-1 — 均值下降与错误变多

状态：pending_human_review；技术背景：performance-evidence-v1；档位：基础

**原题**

发布后平均响应从200ms降到80ms，同时快速500从1%升到40%；成功请求耗时尚未分开。

可接受：先拆成功/失败延迟及错误率，不把均值下降宣称性能改善。

明确错误：平均值下降说明用户请求整体变好了。

依据候选：快速错误会拉低均值，必须保成功质量和错误成本一起看。

反例：反例：发布后平均响应从200ms降到80ms，同时快速500从1%升到40%；成功请求耗时尚未分开。 因此“平均值下降说明用户请求整体变好了。”不成立。

来源：[monitoring](https://sre.google/sre-book/monitoring-distributed-systems/)；Google SRE book; response-sha256:ea5268bca492024a399730734132c7513b4412b10098a207f2e3090eeae1a6fe；Google SRE book, Monitoring Distributed Systems (2016)。规范摘要（AI中文改写，待人工核验，非逐字引句）：延迟/流量/错误/饱和度应联合观察；成功与失败延迟分开，否则快速错误可能压低均值。尾延迟可提示饱和，但不能仅凭一个指标证明根因。

本判断短引定位：distinguish between the latency of successful requests

**实质变式候选**

错误率稳定1%，成功请求p99从250ms升到2s；均值仍80ms且没有等待分解。

可接受：报告成功尾延迟退化并补等待/资源证据，不凭均值或单p99认定根因。

明确错误：平均值下降说明用户请求整体变好了。

依据候选：错误混淆已排除，尾部问题需进一步定位，不能猜是某个SQL。

反例：反例：错误率稳定1%，成功请求p99从250ms升到2s；均值仍80ms且没有等待分解。 因此“平均值下降说明用户请求整体变好了。”不成立。

来源：[monitoring](https://sre.google/sre-book/monitoring-distributed-systems/)；Google SRE book; response-sha256:ea5268bca492024a399730734132c7513b4412b10098a207f2e3090eeae1a6fe；Google SRE book, Monitoring Distributed Systems (2016)。规范摘要（AI中文改写，待人工核验，非逐字引句）：延迟/流量/错误/饱和度应联合观察；成功与失败延迟分开，否则快速错误可能压低均值。尾延迟可提示饱和，但不能仅凭一个指标证明根因。

本判断短引定位：99th percentile response time

变化依据：由“发布后平均响应从200ms降到80ms，同时快速500从1%升到40%；成功请求耗时尚未分开。”变为“错误率稳定1%，成功请求p99从250ms升到2s；均值仍80ms且没有等待分解。”，故“先拆成功/失败延迟及错误率，不把均值下降宣称性能改善。”改为“报告成功尾延迟退化并补等待/资源证据，不凭均值或单p99认定根因。”。

仅改名反例：均值下降与错误变多（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：快速错误会拉低均值，必须保成功质量和错误成本一起看。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## performance.bottleneck-2 — 请求总耗时与连接池等待

状态：pending_human_review；技术背景：performance-evidence-v1；档位：进阶

**原题**

单请求总900ms，其中连接池等待800ms、SQL实际20ms；CPU空闲且没有SQL计划异常证据。

可接受：先测连接占用与等待来源，不把总耗时归给SQL执行。

明确错误：总900ms意味着SQL慢，立即加索引。

依据候选：测得的主要时间在等待而非SQL，需用能区分假设的指标定位。

反例：反例：单请求总900ms，其中连接池等待800ms、SQL实际20ms；CPU空闲且没有SQL计划异常证据。 因此“总900ms意味着SQL慢，立即加索引。”不成立。

来源：[monitoring](https://sre.google/sre-book/monitoring-distributed-systems/)；Google SRE book; response-sha256:ea5268bca492024a399730734132c7513b4412b10098a207f2e3090eeae1a6fe；Google SRE book, Monitoring Distributed Systems (2016)。规范摘要（AI中文改写，待人工核验，非逐字引句）：延迟/流量/错误/饱和度应联合观察；成功与失败延迟分开，否则快速错误可能压低均值。尾延迟可提示饱和，但不能仅凭一个指标证明根因。

本判断短引定位：latency, traffic, errors, and saturation

**实质变式候选**

连接等待已降到5ms；SQL实际800ms且计划扫描大部分无关行，CPU未饱和。

可接受：转向SQL执行与选择性验证，再比较索引成本，不重复扩大连接池。

明确错误：总900ms意味着SQL慢，立即加索引。

依据候选：主要时间归属已改变，旧连接池判断不能覆盖新执行证据。

反例：反例：连接等待已降到5ms；SQL实际800ms且计划扫描大部分无关行，CPU未饱和。 因此“总900ms意味着SQL慢，立即加索引。”不成立。

来源：[monitoring](https://sre.google/sre-book/monitoring-distributed-systems/)；Google SRE book; response-sha256:ea5268bca492024a399730734132c7513b4412b10098a207f2e3090eeae1a6fe；Google SRE book, Monitoring Distributed Systems (2016)。规范摘要（AI中文改写，待人工核验，非逐字引句）：延迟/流量/错误/饱和度应联合观察；成功与失败延迟分开，否则快速错误可能压低均值。尾延迟可提示饱和，但不能仅凭一个指标证明根因。

本判断短引定位：latency, traffic, errors, and saturation

变化依据：由“单请求总900ms，其中连接池等待800ms、SQL实际20ms；CPU空闲且没有SQL计划异常证据。”变为“连接等待已降到5ms；SQL实际800ms且计划扫描大部分无关行，CPU未饱和。”，故“先测连接占用与等待来源，不把总耗时归给SQL执行。”改为“转向SQL执行与选择性验证，再比较索引成本，不重复扩大连接池。”。

仅改名反例：请求总耗时与连接池等待（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：测得的主要时间在等待而非SQL，需用能区分假设的指标定位。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## performance.bottleneck-3 — 均匀平均掩盖热点尾部

状态：pending_human_review；技术背景：performance-evidence-v1；档位：综合

**原题**

总体CPU50%、均值稳定；一个分片p99与队列上升，其他分片空闲，错误集中在热点；路由键分布尚未核对。

可接受：按分片拆流量/饱和/错误，核热点分布及迁移风险，再决定调整。

明确错误：总体CPU没满就无限增加同热点并发。

依据候选：总体平均可掩盖局部饱和，跨指标与分片观察才区分热点假设。

反例：反例：总体CPU50%、均值稳定；一个分片p99与队列上升，其他分片空闲，错误集中在热点；路由键分布尚未核对。 因此“总体CPU没满就无限增加同热点并发。”不成立。

来源：[monitoring](https://sre.google/sre-book/monitoring-distributed-systems/)；Google SRE book; response-sha256:ea5268bca492024a399730734132c7513b4412b10098a207f2e3090eeae1a6fe；Google SRE book, Monitoring Distributed Systems (2016)。规范摘要（AI中文改写，待人工核验，非逐字引句）：延迟/流量/错误/饱和度应联合观察；成功与失败延迟分开，否则快速错误可能压低均值。尾延迟可提示饱和，但不能仅凭一个指标证明根因。

本判断短引定位：99th percentile response time

**实质变式候选**

分片流量已均衡且队列低；外部依赖慢错误使成功/失败耗时分布不同。

可接受：转向依赖链和成功/错误延迟拆分，保当前分片均衡事实。

明确错误：总体CPU没满就无限增加同热点并发。

依据候选：新证据不再支持热点瓶颈，应跟随实际等待与错误边界改判。

反例：反例：分片流量已均衡且队列低；外部依赖慢错误使成功/失败耗时分布不同。 因此“总体CPU没满就无限增加同热点并发。”不成立。

来源：[monitoring](https://sre.google/sre-book/monitoring-distributed-systems/)；Google SRE book; response-sha256:ea5268bca492024a399730734132c7513b4412b10098a207f2e3090eeae1a6fe；Google SRE book, Monitoring Distributed Systems (2016)。规范摘要（AI中文改写，待人工核验，非逐字引句）：延迟/流量/错误/饱和度应联合观察；成功与失败延迟分开，否则快速错误可能压低均值。尾延迟可提示饱和，但不能仅凭一个指标证明根因。

本判断短引定位：distinguish between the latency of successful requests

变化依据：由“总体CPU50%、均值稳定；一个分片p99与队列上升，其他分片空闲，错误集中在热点；路由键分布尚未核对。”变为“分片流量已均衡且队列低；外部依赖慢错误使成功/失败耗时分布不同。”，故“按分片拆流量/饱和/错误，核热点分布及迁移风险，再决定调整。”改为“转向依赖链和成功/错误延迟拆分，保当前分片均衡事实。”。

仅改名反例：均匀平均掩盖热点尾部（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：总体平均可掩盖局部饱和，跨指标与分片观察才区分热点假设。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## performance.capacity-1 — 持续入流超过服务率

状态：pending_human_review；技术背景：performance-evidence-v1；档位：基础

**原题**

受控测得到达120/s、服务80/s，积压持续增长，内存有限；未受理请求允许明确拒绝重试。

可接受：设置有界受理与明确背压，记录已受理任务；不能承诺无限排队立即成功。

明确错误：把队列改无限就能长期保持零延迟零失败。

依据候选：持续净流入会增加积压，容量限制需明确反馈而非隐藏资源耗尽。

反例：反例：受控测得到达120/s、服务80/s，积压持续增长，内存有限；未受理请求允许明确拒绝重试。 因此“把队列改无限就能长期保持零延迟零失败。”不成立。

来源：[overload](https://sre.google/sre-book/handling-overload/)；Google SRE book; response-sha256:8ca912a82390e7f61e8bbae7baab3a74489f5068d71dee1ff24aed99375e0373；Google SRE book, Handling Overload (2016)。规范摘要（AI中文改写，待人工核验，非逐字引句）：只接受容量能处理的工作并明确拒绝其余；积压无限增长会耗尽资源。重试也消耗容量，需请求级/客户端级预算，不能多层无限放大。关键性分级要以真实业务损害决定，书中数字是实例而非本题硬阈值。

本判断短引定位：only accept that load as capacity frees up

**实质变式候选**

流量已降到40/s、服务80/s，队列正下降且内存安全。

可接受：按测量逐步恢复受理并观察排空，不继续按旧峰值拒绝全部流量。

明确错误：把队列改无限就能长期保持零延迟零失败。

依据候选：净流入改变后可恢复容量利用，过载保护不等于永久停服。

反例：反例：流量已降到40/s、服务80/s，队列正下降且内存安全。 因此“把队列改无限就能长期保持零延迟零失败。”不成立。

来源：[overload](https://sre.google/sre-book/handling-overload/)；Google SRE book; response-sha256:8ca912a82390e7f61e8bbae7baab3a74489f5068d71dee1ff24aed99375e0373；Google SRE book, Handling Overload (2016)。规范摘要（AI中文改写，待人工核验，非逐字引句）：只接受容量能处理的工作并明确拒绝其余；积压无限增长会耗尽资源。重试也消耗容量，需请求级/客户端级预算，不能多层无限放大。关键性分级要以真实业务损害决定，书中数字是实例而非本题硬阈值。

本判断短引定位：only accept that load as capacity frees up

变化依据：由“受控测得到达120/s、服务80/s，积压持续增长，内存有限；未受理请求允许明确拒绝重试。”变为“流量已降到40/s、服务80/s，队列正下降且内存安全。”，故“设置有界受理与明确背压，记录已受理任务；不能承诺无限排队立即成功。”改为“按测量逐步恢复受理并观察排空，不继续按旧峰值拒绝全部流量。”。

仅改名反例：持续入流超过服务率（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：持续净流入会增加积压，容量限制需明确反馈而非隐藏资源耗尽。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## performance.capacity-2 — 三层重试放大故障

状态：pending_human_review；技术背景：performance-evidence-v1；档位：进阶

**原题**

入口/业务/数据库客户端各自最多重试3次，失败立即重试；下游过载，重试流量远超新请求。

可接受：核整链请求预算与退避，限制重试占比并传递不可重试失败，保实际用量。

明确错误：每层都有3次上限，所以全链最多只会请求3次。

依据候选：独立层级预算会相乘放大，重试同样消耗已紧张的容量。

反例：反例：入口/业务/数据库客户端各自最多重试3次，失败立即重试；下游过载，重试流量远超新请求。 因此“每层都有3次上限，所以全链最多只会请求3次。”不成立。

来源：[overload](https://sre.google/sre-book/handling-overload/)；Google SRE book; response-sha256:8ca912a82390e7f61e8bbae7baab3a74489f5068d71dee1ff24aed99375e0373；Google SRE book, Handling Overload (2016)。规范摘要（AI中文改写，待人工核验，非逐字引句）：只接受容量能处理的工作并明确拒绝其余；积压无限增长会耗尽资源。重试也消耗容量，需请求级/客户端级预算，不能多层无限放大。关键性分级要以真实业务损害决定，书中数字是实例而非本题硬阈值。

本判断短引定位：per-client retry budget

**实质变式候选**

已统一请求预算，但租户A重试占用多数容量，租户B关键新请求被挤压。

可接受：进一步按客户端/业务关键性隔离预算与受理，不只改全局次数。

明确错误：每层都有3次上限，所以全链最多只会请求3次。

依据候选：全链上限解决单请求放大，仍不能自动解决跨客户端资源公平。

反例：反例：已统一请求预算，但租户A重试占用多数容量，租户B关键新请求被挤压。 因此“每层都有3次上限，所以全链最多只会请求3次。”不成立。

来源：[overload](https://sre.google/sre-book/handling-overload/)；Google SRE book; response-sha256:8ca912a82390e7f61e8bbae7baab3a74489f5068d71dee1ff24aed99375e0373；Google SRE book, Handling Overload (2016)。规范摘要（AI中文改写，待人工核验，非逐字引句）：只接受容量能处理的工作并明确拒绝其余；积压无限增长会耗尽资源。重试也消耗容量，需请求级/客户端级预算，不能多层无限放大。关键性分级要以真实业务损害决定，书中数字是实例而非本题硬阈值。

本判断短引定位：per-client retry budget

变化依据：由“入口/业务/数据库客户端各自最多重试3次，失败立即重试；下游过载，重试流量远超新请求。”变为“已统一请求预算，但租户A重试占用多数容量，租户B关键新请求被挤压。”，故“核整链请求预算与退避，限制重试占比并传递不可重试失败，保实际用量。”改为“进一步按客户端/业务关键性隔离预算与受理，不只改全局次数。”。

仅改名反例：三层重试放大故障（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：独立层级预算会相乘放大，重试同样消耗已紧张的容量。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## performance.capacity-3 — 扩容十分钟与账务积压

状态：pending_human_review；技术背景：performance-evidence-v1；档位：综合

**原题**

到达突增十倍，扩容需10分钟；已受理账务不得丢，低优先级报表允许延后，持久队列有容量上限。

可接受：优先保已受理账务的持久状态，限制新受理并延后报表，测排空与重试恢复。

明确错误：删除全部积压让队列变短，再宣称恢复成功。

依据候选：关键性及容量需同时考虑，丢弃已受理账务不符合冻结业务规则。

反例：反例：到达突增十倍，扩容需10分钟；已受理账务不得丢，低优先级报表允许延后，持久队列有容量上限。 因此“删除全部积压让队列变短，再宣称恢复成功。”不成立。

来源：[overload](https://sre.google/sre-book/handling-overload/)；Google SRE book; response-sha256:8ca912a82390e7f61e8bbae7baab3a74489f5068d71dee1ff24aed99375e0373；Google SRE book, Handling Overload (2016)。规范摘要（AI中文改写，待人工核验，非逐字引句）：只接受容量能处理的工作并明确拒绝其余；积压无限增长会耗尽资源。重试也消耗容量，需请求级/客户端级预算，不能多层无限放大。关键性分级要以真实业务损害决定，书中数字是实例而非本题硬阈值。

本判断短引定位：how critical we consider that request

**实质变式候选**

扩容完成且服务率高于入流，但重复回放出现同业务身份；账务不得重复结算。

可接受：在恢复吞吐时核持久业务防重与排空结果，不能只看队列下降。

明确错误：删除全部积压让队列变短，再宣称恢复成功。

依据候选：容量恢复不等于业务完整性恢复，重复记录使验证条件改变。

反例：反例：扩容完成且服务率高于入流，但重复回放出现同业务身份；账务不得重复结算。 因此“删除全部积压让队列变短，再宣称恢复成功。”不成立。

来源：[overload](https://sre.google/sre-book/handling-overload/)；Google SRE book; response-sha256:8ca912a82390e7f61e8bbae7baab3a74489f5068d71dee1ff24aed99375e0373；Google SRE book, Handling Overload (2016)。规范摘要（AI中文改写，待人工核验，非逐字引句）：只接受容量能处理的工作并明确拒绝其余；积压无限增长会耗尽资源。重试也消耗容量，需请求级/客户端级预算，不能多层无限放大。关键性分级要以真实业务损害决定，书中数字是实例而非本题硬阈值。

本判断短引定位：how critical we consider that request

变化依据：由“到达突增十倍，扩容需10分钟；已受理账务不得丢，低优先级报表允许延后，持久队列有容量上限。”变为“扩容完成且服务率高于入流，但重复回放出现同业务身份；账务不得重复结算。”，故“优先保已受理账务的持久状态，限制新受理并延后报表，测排空与重试恢复。”改为“在恢复吞吐时核持久业务防重与排空结果，不能只看队列下降。”。

仅改名反例：扩容十分钟与账务积压（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：关键性及容量需同时考虑，丢弃已受理账务不符合冻结业务规则。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## operations.configuration-1 — 镜像ENV与运行覆盖

状态：pending_human_review；技术背景：operations-evidence-v1；档位：基础

**原题**

镜像ENV设MODE=old；Compose environment字面设MODE=new；无CLI覆盖或其他插值；新建容器。

可接受：按运行environment覆盖镜像ENV预期new，并在实例核实际值。

明确错误：镜像构建成功说明运行一定仍为old。

依据候选：明确运行注入优先于镜像默认，构建状态不能替代运行配置核验。

反例：反例：镜像ENV设MODE=old；Compose environment字面设MODE=new；无CLI覆盖或其他插值；新建容器。 因此“镜像构建成功说明运行一定仍为old。”不成立。

来源：[compose](https://docs.docker.com/compose/how-tos/environment-variables/envvars-precedence/)；Docker Compose environment precedence; response-sha256:df570bba23523f10d1023d7167ba410f78d21645cb4098c5954b8ec9b6917438；Docker Compose environment precedence, snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：同变量优先级依次涉及run命令显式值、environment/env_file中由shell或环境文件插值的值、environment字面值、env_file、镜像ENV。宿主环境不会无映射地自动成为容器变量；应核真实部署输入及运行实例。

本判断短引定位：Set using just the environment attribute

**实质变式候选**

Compose已移除该变量及env_file；仅宿主shell设MODE=new，未映射；镜像仍old。

可接受：不能把宿主变量自动当容器注入，预期镜像old并核实例。

明确错误：镜像构建成功说明运行一定仍为old。

依据候选：映射被移除改变了生效来源，宿主值本身不自动覆盖镜像。

反例：反例：Compose已移除该变量及env_file；仅宿主shell设MODE=new，未映射；镜像仍old。 因此“镜像构建成功说明运行一定仍为old。”不成立。

来源：[compose](https://docs.docker.com/compose/how-tos/environment-variables/envvars-precedence/)；Docker Compose environment precedence; response-sha256:df570bba23523f10d1023d7167ba410f78d21645cb4098c5954b8ec9b6917438；Docker Compose environment precedence, snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：同变量优先级依次涉及run命令显式值、environment/env_file中由shell或环境文件插值的值、environment字面值、env_file、镜像ENV。宿主环境不会无映射地自动成为容器变量；应核真实部署输入及运行实例。

本判断短引定位：Set in a container image in the ENV directive

变化依据：由“镜像ENV设MODE=old；Compose environment字面设MODE=new；无CLI覆盖或其他插值；新建容器。”变为“Compose已移除该变量及env_file；仅宿主shell设MODE=new，未映射；镜像仍old。”，故“按运行environment覆盖镜像ENV预期new，并在实例核实际值。”改为“不能把宿主变量自动当容器注入，预期镜像old并核实例。”。

仅改名反例：镜像ENV与运行覆盖（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：明确运行注入优先于镜像默认，构建状态不能替代运行配置核验。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## operations.configuration-2 — 存活与就绪分开

状态：pending_human_review；技术背景：operations-evidence-v1；档位：进阶

**原题**

Kubernetes容器进程存活，liveness成功，readiness因依赖不可用失败；Service应只向就绪实例发流量。

可接受：定位就绪失败和依赖，不能以存活成功强行标可服务。

明确错误：进程存在就禁用readiness以完成发布。

依据候选：就绪决定接流量，存活与能完成请求是不同事实。

反例：反例：Kubernetes容器进程存活，liveness成功，readiness因依赖不可用失败；Service应只向就绪实例发流量。 因此“进程存在就禁用readiness以完成发布。”不成立。

来源：[probes](https://v1-34.docs.kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)；Kubernetes1.34 liveness/readiness/startup probes; response-sha256:4c36479fa0d2e3c7cc26910a4bbf1632241b3e9ce0eb6e962cd8f51f13a954fb；Kubernetes1.34 liveness/readiness/startup probes。规范摘要（AI中文改写，待人工核验，非逐字引句）：readiness判断可否接流量，失败时从Service后端移除；liveness用于判断重启。startup成功前不会开始后两类探针延迟。进程存活、启动完成和可服务不是同一状态。

本判断短引定位：ready to start accepting traffic

**实质变式候选**

依赖恢复、readiness成功，但liveness连续失败到阈值，探针自身检查路径仍需核对。

可接受：核对liveness失败依据与重启行为，不能用一次就绪成功否定它。

明确错误：进程存在就禁用readiness以完成发布。

依据候选：两探针职责不同，新故障不能沿用旧的依赖就绪诊断。

反例：反例：依赖恢复、readiness成功，但liveness连续失败到阈值，探针自身检查路径仍需核对。 因此“进程存在就禁用readiness以完成发布。”不成立。

来源：[probes](https://v1-34.docs.kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)；Kubernetes1.34 liveness/readiness/startup probes; response-sha256:4c36479fa0d2e3c7cc26910a4bbf1632241b3e9ce0eb6e962cd8f51f13a954fb；Kubernetes1.34 liveness/readiness/startup probes。规范摘要（AI中文改写，待人工核验，非逐字引句）：readiness判断可否接流量，失败时从Service后端移除；liveness用于判断重启。startup成功前不会开始后两类探针延迟。进程存活、启动完成和可服务不是同一状态。

本判断短引定位：liveness probes to know when to restart a container

变化依据：由“Kubernetes容器进程存活，liveness成功，readiness因依赖不可用失败；Service应只向就绪实例发流量。”变为“依赖恢复、readiness成功，但liveness连续失败到阈值，探针自身检查路径仍需核对。”，故“定位就绪失败和依赖，不能以存活成功强行标可服务。”改为“核对liveness失败依据与重启行为，不能用一次就绪成功否定它。”。

仅改名反例：存活与就绪分开（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：就绪决定接流量，存活与能完成请求是不同事实。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## operations.configuration-3 — 慢启动与探针接管

状态：pending_human_review；技术背景：operations-evidence-v1；档位：综合

**原题**

应用冷启动需90秒，未配置startup；liveness每10秒失败3次导致启动未完成即重启；资源与启动日志无死锁证据。

可接受：按实际启动上界配置startup窗口并验证成功后liveness接管，不永久关闭健康检查。

明确错误：直接删掉全部探针即可证明服务可靠。

依据候选：启动阶段与运行失活需分别检查，合适窗口避免把正常初始化误杀。

反例：反例：应用冷启动需90秒，未配置startup；liveness每10秒失败3次导致启动未完成即重启；资源与启动日志无死锁证据。 因此“直接删掉全部探针即可证明服务可靠。”不成立。

来源：[probes](https://v1-34.docs.kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)；Kubernetes1.34 liveness/readiness/startup probes; response-sha256:4c36479fa0d2e3c7cc26910a4bbf1632241b3e9ce0eb6e962cd8f51f13a954fb；Kubernetes1.34 liveness/readiness/startup probes。规范摘要（AI中文改写，待人工核验，非逐字引句）：readiness判断可否接流量，失败时从Service后端移除；liveness用于判断重启。startup成功前不会开始后两类探针延迟。进程存活、启动完成和可服务不是同一状态。

本判断短引定位：until the startup probe has succeeded

**实质变式候选**

startup已成功，此后进程真正死锁且liveness按阈值失败；readiness也失败。

可接受：让运行期探针执行既定恢复并查死锁，不继续无限延长启动宽限。

明确错误：直接删掉全部探针即可证明服务可靠。

依据候选：启动已结束，新的运行故障不能用冷启动理由掩盖。

反例：反例：startup已成功，此后进程真正死锁且liveness按阈值失败；readiness也失败。 因此“直接删掉全部探针即可证明服务可靠。”不成立。

来源：[probes](https://v1-34.docs.kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)；Kubernetes1.34 liveness/readiness/startup probes; response-sha256:4c36479fa0d2e3c7cc26910a4bbf1632241b3e9ce0eb6e962cd8f51f13a954fb；Kubernetes1.34 liveness/readiness/startup probes。规范摘要（AI中文改写，待人工核验，非逐字引句）：readiness判断可否接流量，失败时从Service后端移除；liveness用于判断重启。startup成功前不会开始后两类探针延迟。进程存活、启动完成和可服务不是同一状态。

本判断短引定位：liveness probes to know when to restart a container

变化依据：由“应用冷启动需90秒，未配置startup；liveness每10秒失败3次导致启动未完成即重启；资源与启动日志无死锁证据。”变为“startup已成功，此后进程真正死锁且liveness按阈值失败；readiness也失败。”，故“按实际启动上界配置startup窗口并验证成功后liveness接管，不永久关闭健康检查。”改为“让运行期探针执行既定恢复并查死锁，不继续无限延长启动宽限。”。

仅改名反例：慢启动与探针接管（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：启动阶段与运行失活需分别检查，合适窗口避免把正常初始化误杀。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## operations.recovery-1 — 回滚镜像会恢复数据吗

状态：pending_human_review；技术背景：operations-evidence-v1；档位：基础

**原题**

新Deployment版本故障且已错误修改部分数据库行；只有Pod模板回退操作，尚未数据恢复。

可接受：先止损并保留证据，回退应用后仍需独立核对受损数据与恢复方案。

明确错误：回到旧镜像就表示被改数据也回到旧值。

依据候选：Deployment回退只作用Pod模板，不逆转数据库写入。

反例：反例：新Deployment版本故障且已错误修改部分数据库行；只有Pod模板回退操作，尚未数据恢复。 因此“回到旧镜像就表示被改数据也回到旧值。”不成立。

来源：[deployment](https://v1-34.docs.kubernetes.io/docs/concepts/workloads/controllers/deployment/)；Kubernetes1.34 Deployments; response-sha256:c5a65a50279595dab5791b5abab2e515570e9755e799922273b55f87ba0d6ed8；Kubernetes1.34 Deployments, Rolling Back a Deployment。规范摘要（AI中文改写，待人工核验，非逐字引句）：Deployment回退只恢复Pod模板版本，不逆转数据库写入或手动配置变化；数据损坏需要独立核对恢复方案。

本判断短引定位：only the Deployment's Pod template part is rolled back

**实质变式候选**

确认新版本没有写坏数据，故障仅错误镜像名导致未启动；旧模板可用。

可接受：回退到已核旧模板并做启动/就绪与关键读写冒烟，不进行无依据的数据覆盖。

明确错误：回到旧镜像就表示被改数据也回到旧值。

依据候选：没有数据损坏的证据使恢复范围变小，不能照搬整库还原。

反例：反例：确认新版本没有写坏数据，故障仅错误镜像名导致未启动；旧模板可用。 因此“回到旧镜像就表示被改数据也回到旧值。”不成立。

来源：[deployment](https://v1-34.docs.kubernetes.io/docs/concepts/workloads/controllers/deployment/)；Kubernetes1.34 Deployments; response-sha256:c5a65a50279595dab5791b5abab2e515570e9755e799922273b55f87ba0d6ed8；Kubernetes1.34 Deployments, Rolling Back a Deployment。规范摘要（AI中文改写，待人工核验，非逐字引句）：Deployment回退只恢复Pod模板版本，不逆转数据库写入或手动配置变化；数据损坏需要独立核对恢复方案。

本判断短引定位：only the Deployment's Pod template part is rolled back

变化依据：由“新Deployment版本故障且已错误修改部分数据库行；只有Pod模板回退操作，尚未数据恢复。”变为“确认新版本没有写坏数据，故障仅错误镜像名导致未启动；旧模板可用。”，故“先止损并保留证据，回退应用后仍需独立核对受损数据与恢复方案。”改为“回退到已核旧模板并做启动/就绪与关键读写冒烟，不进行无依据的数据覆盖。”。

仅改名反例：回滚镜像会恢复数据吗（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：Deployment回退只作用Pod模板，不逆转数据库写入。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## operations.recovery-2 — 有备份但WAL中间缺段

状态：pending_human_review；技术背景：operations-evidence-v1；档位：进阶

**原题**

PostgreSQL基础备份可读，目标在其结束后；但从备份起点到目标之间缺一段WAL，源数据已损坏。

可接受：明确目标尚不可达，先找齐连续WAL或选择可证实恢复点，隔离演练。

明确错误：基础备份存在就保证能恢复到任意后来时间。

依据候选：PITR依赖连续日志，不能跨缺段冒称重放成功。

反例：反例：PostgreSQL基础备份可读，目标在其结束后；但从备份起点到目标之间缺一段WAL，源数据已损坏。 因此“基础备份存在就保证能恢复到任意后来时间。”不成立。

来源：[pitr](https://www.postgresql.org/docs/17/continuous-archiving.html)；PostgreSQL17 §25.3 continuous archiving/PITR; response-sha256:84ca17012c72f25c8b371649b6f57cb2fe9af07851fdfba003f8c80a00de4ffc；PostgreSQL17 §25.3 continuous archiving/PITR。规范摘要（AI中文改写，待人工核验，非逐字引句）：PITR需要覆盖基础备份起点起的连续WAL；目标必须晚于该基础备份结束。数据WAL不恢复手动配置文件变化。恢复点选择需核数据损失窗口、时间线及隔离恢复结果，不能凭备份存在宣称恢复成功。

本判断短引定位：continuous sequence of archived WAL files

**实质变式候选**

所需WAL与时间线已补齐；隔离恢复到目标完成，但手动认证配置文件未备份。

可接受：保已恢复数据结果，另恢复并核对配置权限，不能把WAL当配置备份。

明确错误：基础备份存在就保证能恢复到任意后来时间。

依据候选：数据重放条件成立仍不包含手动配置，恢复验收还需独立配置证据。

反例：反例：所需WAL与时间线已补齐；隔离恢复到目标完成，但手动认证配置文件未备份。 因此“基础备份存在就保证能恢复到任意后来时间。”不成立。

来源：[pitr](https://www.postgresql.org/docs/17/continuous-archiving.html)；PostgreSQL17 §25.3 continuous archiving/PITR; response-sha256:84ca17012c72f25c8b371649b6f57cb2fe9af07851fdfba003f8c80a00de4ffc；PostgreSQL17 §25.3 continuous archiving/PITR。规范摘要（AI中文改写，待人工核验，非逐字引句）：PITR需要覆盖基础备份起点起的连续WAL；目标必须晚于该基础备份结束。数据WAL不恢复手动配置文件变化。恢复点选择需核数据损失窗口、时间线及隔离恢复结果，不能凭备份存在宣称恢复成功。

本判断短引定位：will not restore changes made to configuration files

变化依据：由“PostgreSQL基础备份可读，目标在其结束后；但从备份起点到目标之间缺一段WAL，源数据已损坏。”变为“所需WAL与时间线已补齐；隔离恢复到目标完成，但手动认证配置文件未备份。”，故“明确目标尚不可达，先找齐连续WAL或选择可证实恢复点，隔离演练。”改为“保已恢复数据结果，另恢复并核对配置权限，不能把WAL当配置备份。”。

仅改名反例：有备份但WAL中间缺段（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：PITR依赖连续日志，不能跨缺段冒称重放成功。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## operations.recovery-3 — 恢复点不能落在基础备份内部

状态：pending_human_review；技术背景：operations-evidence-v1；档位：综合

**原题**

现有基础备份10:00开始10:20结束，拟恢复到10:10避免损坏；没有更早基础备份，另有WAL。

可接受：拒绝宣称该目标可由此备份恢复，先找更早可用基础备份并界定损失窗口。

明确错误：WAL足够多就能把10:20结束的备份恢复到10:10。

依据候选：目标必须晚于所用基础备份结束，日志不能取消此条件。

反例：反例：现有基础备份10:00开始10:20结束，拟恢复到10:10避免损坏；没有更早基础备份，另有WAL。 因此“WAL足够多就能把10:20结束的备份恢复到10:10。”不成立。

来源：[pitr](https://www.postgresql.org/docs/17/continuous-archiving.html)；PostgreSQL17 §25.3 continuous archiving/PITR; response-sha256:84ca17012c72f25c8b371649b6f57cb2fe9af07851fdfba003f8c80a00de4ffc；PostgreSQL17 §25.3 continuous archiving/PITR。规范摘要（AI中文改写，待人工核验，非逐字引句）：PITR需要覆盖基础备份起点起的连续WAL；目标必须晚于该基础备份结束。数据WAL不恢复手动配置文件变化。恢复点选择需核数据损失窗口、时间线及隔离恢复结果，不能凭备份存在宣称恢复成功。

本判断短引定位：after the ending time of the base backup

**实质变式候选**

找到9:00结束的备份及连续WAL；10:10目标可恢复，但10:10后有合法新订单和后续删除记录。

可接受：先隔离恢复并核对损失与合法变更/删除，再决定授权修复，不直接覆盖当前库。

明确错误：WAL足够多就能把10:20结束的备份恢复到10:10。

依据候选：技术恢复点成立不等于可无损替换当前数据，必须核对目标后的合法事实。

反例：反例：找到9:00结束的备份及连续WAL；10:10目标可恢复，但10:10后有合法新订单和后续删除记录。 因此“WAL足够多就能把10:20结束的备份恢复到10:10。”不成立。

来源：[pitr](https://www.postgresql.org/docs/17/continuous-archiving.html)；PostgreSQL17 §25.3 continuous archiving/PITR; response-sha256:84ca17012c72f25c8b371649b6f57cb2fe9af07851fdfba003f8c80a00de4ffc；PostgreSQL17 §25.3 continuous archiving/PITR。规范摘要（AI中文改写，待人工核验，非逐字引句）：PITR需要覆盖基础备份起点起的连续WAL；目标必须晚于该基础备份结束。数据WAL不恢复手动配置文件变化。恢复点选择需核数据损失窗口、时间线及隔离恢复结果，不能凭备份存在宣称恢复成功。

本判断短引定位：after the ending time of the base backup

变化依据：由“现有基础备份10:00开始10:20结束，拟恢复到10:10避免损坏；没有更早基础备份，另有WAL。”变为“找到9:00结束的备份及连续WAL；10:10目标可恢复，但10:10后有合法新订单和后续删除记录。”，故“拒绝宣称该目标可由此备份恢复，先找更早可用基础备份并界定损失窗口。”改为“先隔离恢复并核对损失与合法变更/删除，再决定授权修复，不直接覆盖当前库。”。

仅改名反例：恢复点不能落在基础备份内部（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：目标必须晚于所用基础备份结束，日志不能取消此条件。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。
