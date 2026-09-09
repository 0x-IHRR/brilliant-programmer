# 逐条人工复核待办

全部为 AI 草稿，尚无人类签核。以下便于审阅，JSON保留完整结构；此清单不自动认可标签。

## ai.grounding-1 — 带引用也可能答非所据

状态：pending_human_review；技术背景：ai-evidence-v1；档位：基础

**原题**

合成手册写“免费计划每月100次”；模型引用该段却回答无限次，未提供其他条款。

可接受：指出回答与实际片段不符，按明确条款纠正或要求补充支持依据。

明确错误：只要引用链接存在就认定无限次已被来源证明。

依据候选：引用定位只是可追溯，当前片段的数量约束与主张直接冲突。

反例：反例：合成手册写“免费计划每月100次”；模型引用该段却回答无限次，未提供其他条款。 因此“只要引用链接存在就认定无限次已被来源证明。”不成立。

来源：[rag](https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview)；Azure AI Search RAG overview, Content preparation / token constraints; snapshot2026-09-10; response-sha256:4c632701639b52666b3dde2da702350a0143cd50c52cad2272559ed157242ba6；Azure AI Search RAG overview, Content preparation / token constraints; snapshot2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：RAG以检索内容支持回答，内容准备和真正相关片段决定可用依据；引用标识可追溯来源但不自动证明主张符合片段。检索需服从权限，不能把未获准资料发给模型。具体产品承诺、适用版本及例外仍需核原文；本题政策片段全部为教学假设。

本判断短引定位：Built-in citation tracking shows provenance

**实质变式候选**

完整片段显示每月100次只适用于2024旧版，用户问2026新版但新条款未取得。

可接受：保旧版范围，补当前适用条款后再回答新版额度，不拿旧版数字直接推广。

明确错误：只要引用链接存在就认定无限次已被来源证明。

依据候选：新增版本限制改变可支持范围，应补证而不是猜当前额度。

反例：反例：完整片段显示每月100次只适用于2024旧版，用户问2026新版但新条款未取得。 因此“只要引用链接存在就认定无限次已被来源证明。”不成立。

来源：[rag](https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview)；Azure AI Search RAG overview, Content preparation / token constraints; snapshot2026-09-10; response-sha256:4c632701639b52666b3dde2da702350a0143cd50c52cad2272559ed157242ba6；Azure AI Search RAG overview, Content preparation / token constraints; snapshot2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：RAG以检索内容支持回答，内容准备和真正相关片段决定可用依据；引用标识可追溯来源但不自动证明主张符合片段。检索需服从权限，不能把未获准资料发给模型。具体产品承诺、适用版本及例外仍需核原文；本题政策片段全部为教学假设。

本判断短引定位：RAG quality depends on how you prepare content for retrieval

变化依据：由“合成手册写“免费计划每月100次”；模型引用该段却回答无限次，未提供其他条款。”变为“完整片段显示每月100次只适用于2024旧版，用户问2026新版但新条款未取得。”，故“指出回答与实际片段不符，按明确条款纠正或要求补充支持依据。”改为“保旧版范围，补当前适用条款后再回答新版额度，不拿旧版数字直接推广。”。

仅改名反例：带引用也可能答非所据（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：引用定位只是可追溯，当前片段的数量约束与主张直接冲突。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## ai.grounding-2 — 切片遗漏关键例外

状态：pending_human_review；技术背景：ai-evidence-v1；档位：进阶

**原题**

合成政策完整句为“已付款可退款，但已履约服务不可退款”；检索只取前半句，订单已履约。

可接受：恢复相关例外上下文，按已履约条件核结论，不把截断片段当完整规则。

明确错误：召回分数高就允许忽略未传输的例外。

依据候选：缺失限定会改变判断，相关性分数不能代替完整适用条件。

反例：反例：合成政策完整句为“已付款可退款，但已履约服务不可退款”；检索只取前半句，订单已履约。 因此“召回分数高就允许忽略未传输的例外。”不成立。

来源：[rag](https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview)；Azure AI Search RAG overview, Content preparation / token constraints; snapshot2026-09-10; response-sha256:4c632701639b52666b3dde2da702350a0143cd50c52cad2272559ed157242ba6；Azure AI Search RAG overview, Content preparation / token constraints; snapshot2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：RAG以检索内容支持回答，内容准备和真正相关片段决定可用依据；引用标识可追溯来源但不自动证明主张符合片段。检索需服从权限，不能把未获准资料发给模型。具体产品承诺、适用版本及例外仍需核原文；本题政策片段全部为教学假设。

本判断短引定位：RAG quality depends on how you prepare content for retrieval

**实质变式候选**

已完整取得例外；订单履约状态缺失，只有付款记录且无法确定履约。

可接受：保已知退款规则并查询履约事实，再判该订单是否符合，不能凭付款推断未履约。

明确错误：召回分数高就允许忽略未传输的例外。

依据候选：规范缺口已解决，当前缺的是应用规则所需的运行事实。

反例：反例：已完整取得例外；订单履约状态缺失，只有付款记录且无法确定履约。 因此“召回分数高就允许忽略未传输的例外。”不成立。

来源：[rag](https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview)；Azure AI Search RAG overview, Content preparation / token constraints; snapshot2026-09-10; response-sha256:4c632701639b52666b3dde2da702350a0143cd50c52cad2272559ed157242ba6；Azure AI Search RAG overview, Content preparation / token constraints; snapshot2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：RAG以检索内容支持回答，内容准备和真正相关片段决定可用依据；引用标识可追溯来源但不自动证明主张符合片段。检索需服从权限，不能把未获准资料发给模型。具体产品承诺、适用版本及例外仍需核原文；本题政策片段全部为教学假设。

本判断短引定位：RAG quality depends on how you prepare content for retrieval

变化依据：由“合成政策完整句为“已付款可退款，但已履约服务不可退款”；检索只取前半句，订单已履约。”变为“已完整取得例外；订单履约状态缺失，只有付款记录且无法确定履约。”，故“恢复相关例外上下文，按已履约条件核结论，不把截断片段当完整规则。”改为“保已知退款规则并查询履约事实，再判该订单是否符合，不能凭付款推断未履约。”。

仅改名反例：切片遗漏关键例外（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：缺失限定会改变判断，相关性分数不能代替完整适用条件。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## ai.grounding-3 — 多来源冲突与越权补证

状态：pending_human_review；技术背景：ai-evidence-v1；档位：综合

**原题**

合成两份同版本政策给不同保留期，均无优先级；另有无权限内部文件可能澄清，系统尚未读取。

可接受：标明冲突并请求可授权的权威澄清，禁止为补证越权读取内部文件。

明确错误：两个模型都选同一数字就可跳过来源冲突和权限。

依据候选：未决冲突不能由模型一致解决，补证仍受实际授权范围约束。

反例：反例：合成两份同版本政策给不同保留期，均无优先级；另有无权限内部文件可能澄清，系统尚未读取。 因此“两个模型都选同一数字就可跳过来源冲突和权限。”不成立。

来源：[rag](https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview)；Azure AI Search RAG overview, Content preparation / token constraints; snapshot2026-09-10; response-sha256:4c632701639b52666b3dde2da702350a0143cd50c52cad2272559ed157242ba6；Azure AI Search RAG overview, Content preparation / token constraints; snapshot2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：RAG以检索内容支持回答，内容准备和真正相关片段决定可用依据；引用标识可追溯来源但不自动证明主张符合片段。检索需服从权限，不能把未获准资料发给模型。具体产品承诺、适用版本及例外仍需核原文；本题政策片段全部为教学假设。

本判断短引定位：must only retrieve authorized content

**实质变式候选**

有权负责人已发布适用优先级且用户可访问；但答案仍引用被废止旧段，当前新段已可检索。

可接受：按已确认版本更新检索和引用，核主张绑定有效段，不继续称冲突未决。

明确错误：两个模型都选同一数字就可跳过来源冲突和权限。

依据候选：优先级已有来源后应更新实际依据，保历史不等于沿用已废止结论。

反例：反例：有权负责人已发布适用优先级且用户可访问；但答案仍引用被废止旧段，当前新段已可检索。 因此“两个模型都选同一数字就可跳过来源冲突和权限。”不成立。

来源：[rag](https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview)；Azure AI Search RAG overview, Content preparation / token constraints; snapshot2026-09-10; response-sha256:4c632701639b52666b3dde2da702350a0143cd50c52cad2272559ed157242ba6；Azure AI Search RAG overview, Content preparation / token constraints; snapshot2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：RAG以检索内容支持回答，内容准备和真正相关片段决定可用依据；引用标识可追溯来源但不自动证明主张符合片段。检索需服从权限，不能把未获准资料发给模型。具体产品承诺、适用版本及例外仍需核原文；本题政策片段全部为教学假设。

本判断短引定位：Built-in citation tracking shows provenance

变化依据：由“合成两份同版本政策给不同保留期，均无优先级；另有无权限内部文件可能澄清，系统尚未读取。”变为“有权负责人已发布适用优先级且用户可访问；但答案仍引用被废止旧段，当前新段已可检索。”，故“标明冲突并请求可授权的权威澄清，禁止为补证越权读取内部文件。”改为“按已确认版本更新检索和引用，核主张绑定有效段，不继续称冲突未决。”。

仅改名反例：多来源冲突与越权补证（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：未决冲突不能由模型一致解决，补证仍受实际授权范围约束。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## ai.tools-1 — 生成工具参数不代表执行获准

状态：pending_human_review；技术背景：ai-evidence-v1；档位：基础

**原题**

用户只请AI比较两份报告；模型输出删除报告的合法JSON参数，工具将产生不可逆写入，没有删除授权。

可接受：保比较任务，拒绝执行删除并按原意校验工具动作，合法JSON不授予权限。

明确错误：参数符合schema就直接执行删除。

依据候选：工具可调用性与用户授权是不同条件，结构正确不能扩展任务范围。

反例：反例：用户只请AI比较两份报告；模型输出删除报告的合法JSON参数，工具将产生不可逆写入，没有删除授权。 因此“参数符合schema就直接执行删除。”不成立。

来源：[injection](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:581a9bb96bc934fa277fde7610b6e05fdd485d79ff617851de99fc1262f56f74；OWASP Prompt Injection Prevention, Agent-Specific Defenses / HITL / Action screening。规范摘要（AI中文改写，待人工核验，非逐字引句）：模型建议/外部文本不能授予工具权限；服务端按用户意图、会话、具体动作与参数校验，限制权限并对高风险动作保持人工监督。提示分隔、过滤或另一模型检查都是多层防护，不能单独保证无注入；不把示例关键词过滤当完整防线。

本判断短引定位：Validate tool calls against user permissions and session context

**实质变式候选**

用户已明确授权删除指定临时副本，服务端确认归属；模型却把目标ID改成原始报告。

可接受：绑定用户批准的具体副本并拒绝目标漂移，不因已有一次删除授权放行其他资源。

明确错误：参数符合schema就直接执行删除。

依据候选：授权已存在但范围仍限定目标，参数差异需要真实服务端核对。

反例：反例：用户已明确授权删除指定临时副本，服务端确认归属；模型却把目标ID改成原始报告。 因此“参数符合schema就直接执行删除。”不成立。

来源：[injection](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:581a9bb96bc934fa277fde7610b6e05fdd485d79ff617851de99fc1262f56f74；OWASP Prompt Injection Prevention, Agent-Specific Defenses / HITL / Action screening。规范摘要（AI中文改写，待人工核验，非逐字引句）：模型建议/外部文本不能授予工具权限；服务端按用户意图、会话、具体动作与参数校验，限制权限并对高风险动作保持人工监督。提示分隔、过滤或另一模型检查都是多层防护，不能单独保证无注入；不把示例关键词过滤当完整防线。

本判断短引定位：Validate tool calls against user permissions and session context

变化依据：由“用户只请AI比较两份报告；模型输出删除报告的合法JSON参数，工具将产生不可逆写入，没有删除授权。”变为“用户已明确授权删除指定临时副本，服务端确认归属；模型却把目标ID改成原始报告。”，故“保比较任务，拒绝执行删除并按原意校验工具动作，合法JSON不授予权限。”改为“绑定用户批准的具体副本并拒绝目标漂移，不因已有一次删除授权放行其他资源。”。

仅改名反例：生成工具参数不代表执行获准（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：工具可调用性与用户授权是不同条件，结构正确不能扩展任务范围。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## ai.tools-2 — 网页内容冒充用户指令

状态：pending_human_review；技术背景：ai-evidence-v1；档位：进阶

**原题**

用户授权提取网页摘要；页面正文要求代理把摘要发给另一个收件人，模型把它当新用户要求。

可接受：把网页指令作为不可信资料，保摘要任务，拒绝未授权发信动作。

明确错误：网站正文措辞像系统消息即可改写用户授权。

依据候选：外部内容不是授权主体，工具动作必须对照原始意图和会话。

反例：反例：用户授权提取网页摘要；页面正文要求代理把摘要发给另一个收件人，模型把它当新用户要求。 因此“网站正文措辞像系统消息即可改写用户授权。”不成立。

来源：[injection](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:581a9bb96bc934fa277fde7610b6e05fdd485d79ff617851de99fc1262f56f74；OWASP Prompt Injection Prevention, Agent-Specific Defenses / HITL / Action screening。规范摘要（AI中文改写，待人工核验，非逐字引句）：模型建议/外部文本不能授予工具权限；服务端按用户意图、会话、具体动作与参数校验，限制权限并对高风险动作保持人工监督。提示分隔、过滤或另一模型检查都是多层防护，不能单独保证无注入；不把示例关键词过滤当完整防线。

本判断短引定位：against the original user intent

**实质变式候选**

收件人已由用户明确批准，但网页夹带额外附件路径；附件可能含私有凭据且用户未授权读取。

可接受：保收件范围，拒绝额外附件读取/外发，核实际发送载荷不超授权。

明确错误：网站正文措辞像系统消息即可改写用户授权。

依据候选：一个已批准收件人不使任意私有附件获得访问权限。

反例：反例：收件人已由用户明确批准，但网页夹带额外附件路径；附件可能含私有凭据且用户未授权读取。 因此“网站正文措辞像系统消息即可改写用户授权。”不成立。

来源：[injection](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:581a9bb96bc934fa277fde7610b6e05fdd485d79ff617851de99fc1262f56f74；OWASP Prompt Injection Prevention, Agent-Specific Defenses / HITL / Action screening。规范摘要（AI中文改写，待人工核验，非逐字引句）：模型建议/外部文本不能授予工具权限；服务端按用户意图、会话、具体动作与参数校验，限制权限并对高风险动作保持人工监督。提示分隔、过滤或另一模型检查都是多层防护，不能单独保证无注入；不把示例关键词过滤当完整防线。

本判断短引定位：Validate tool calls against user permissions and session context

变化依据：由“用户授权提取网页摘要；页面正文要求代理把摘要发给另一个收件人，模型把它当新用户要求。”变为“收件人已由用户明确批准，但网页夹带额外附件路径；附件可能含私有凭据且用户未授权读取。”，故“把网页指令作为不可信资料，保摘要任务，拒绝未授权发信动作。”改为“保收件范围，拒绝额外附件读取/外发，核实际发送载荷不超授权。”。

仅改名反例：网页内容冒充用户指令（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：外部内容不是授权主体，工具动作必须对照原始意图和会话。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## ai.tools-3 — 第二模型赞同仍缺真实权限

状态：pending_human_review；技术背景：ai-evidence-v1；档位：综合

**原题**

高风险批量修改工具仅由生成模型和检查模型投票决定；两者同意，服务端未核每条资源权限且没有本次批量修改确认。

可接受：保候选方案，补逐资源授权和具体高风险确认后才允许执行，不凭投票放行。

明确错误：两个模型一致即可代替服务端授权和高风险确认。

依据候选：模型检查不是权限真值，批量动作需要实际意图、资源及参数约束。

反例：反例：高风险批量修改工具仅由生成模型和检查模型投票决定；两者同意，服务端未核每条资源权限且没有本次批量修改确认。 因此“两个模型一致即可代替服务端授权和高风险确认。”不成立。

来源：[injection](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:581a9bb96bc934fa277fde7610b6e05fdd485d79ff617851de99fc1262f56f74；OWASP Prompt Injection Prevention, Agent-Specific Defenses / HITL / Action screening。规范摘要（AI中文改写，待人工核验，非逐字引句）：模型建议/外部文本不能授予工具权限；服务端按用户意图、会话、具体动作与参数校验，限制权限并对高风险动作保持人工监督。提示分隔、过滤或另一模型检查都是多层防护，不能单独保证无注入；不把示例关键词过滤当完整防线。

本判断短引定位：Implement human oversight for high-risk operations

来源：[auth](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/Authorization_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:dd56db698a11513111fc0a8e99e4f0e2492c86a5d82528c5a1db35434ca18cfc；OWASP Authorization, Validate the Permissions on Every Request / Static Resources。规范摘要（AI中文改写，待人工核验，非逐字引句）：认证身份不等于所有资源权限；服务端按每个实际请求的主体、动作、资源归属检查，默认拒绝未许可访问。难猜ID/前端隐藏/只保护主路由都不能代替授权，静态导出和批量入口同样受约束。

本判断短引定位：Authorization is distinct from authentication

**实质变式候选**

逐资源权限和本次确认已核；执行期间角色被撤销，后续动作尚未派发，服务端仍用旧缓存权限。

可接受：停止未派发动作并按当前会话权限重查，保已完成事实，不用旧确认恢复已撤销权限。

明确错误：两个模型一致即可代替服务端授权和高风险确认。

依据候选：先前合法授权不能覆盖后续撤销，确认也不是永久权限。

反例：反例：逐资源权限和本次确认已核；执行期间角色被撤销，后续动作尚未派发，服务端仍用旧缓存权限。 因此“两个模型一致即可代替服务端授权和高风险确认。”不成立。

来源：[injection](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:581a9bb96bc934fa277fde7610b6e05fdd485d79ff617851de99fc1262f56f74；OWASP Prompt Injection Prevention, Agent-Specific Defenses / HITL / Action screening。规范摘要（AI中文改写，待人工核验，非逐字引句）：模型建议/外部文本不能授予工具权限；服务端按用户意图、会话、具体动作与参数校验，限制权限并对高风险动作保持人工监督。提示分隔、过滤或另一模型检查都是多层防护，不能单独保证无注入；不把示例关键词过滤当完整防线。

本判断短引定位：Validate tool calls against user permissions and session context

来源：[auth](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/Authorization_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:dd56db698a11513111fc0a8e99e4f0e2492c86a5d82528c5a1db35434ca18cfc；OWASP Authorization, Validate the Permissions on Every Request / Static Resources。规范摘要（AI中文改写，待人工核验，非逐字引句）：认证身份不等于所有资源权限；服务端按每个实际请求的主体、动作、资源归属检查，默认拒绝未许可访问。难猜ID/前端隐藏/只保护主路由都不能代替授权，静态导出和批量入口同样受约束。

本判断短引定位：Authorization is distinct from authentication

变化依据：由“高风险批量修改工具仅由生成模型和检查模型投票决定；两者同意，服务端未核每条资源权限且没有本次批量修改确认。”变为“逐资源权限和本次确认已核；执行期间角色被撤销，后续动作尚未派发，服务端仍用旧缓存权限。”，故“保候选方案，补逐资源授权和具体高风险确认后才允许执行，不凭投票放行。”改为“停止未派发动作并按当前会话权限重查，保已完成事实，不用旧确认恢复已撤销权限。”。

仅改名反例：第二模型赞同仍缺真实权限（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：模型检查不是权限真值，批量动作需要实际意图、资源及参数约束。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## security.authorization-1 — 登录不等于拥有订单

状态：pending_human_review；技术背景：security-evidence-v1；档位：基础

**原题**

A已登录，API按传入订单ID直接返回B的订单；页面只隐藏B订单链接，服务端未核归属。

可接受：按认证A与订单归属拒绝读取，增加直接API跨账号回归。

明确错误：登录成功且页面看不到链接就表示资源安全。

依据候选：真实读取路径缺少资源授权，UI隐藏不能保护直接请求。

反例：反例：A已登录，API按传入订单ID直接返回B的订单；页面只隐藏B订单链接，服务端未核归属。 因此“登录成功且页面看不到链接就表示资源安全。”不成立。

来源：[auth](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/Authorization_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:dd56db698a11513111fc0a8e99e4f0e2492c86a5d82528c5a1db35434ca18cfc；OWASP Authorization, Validate the Permissions on Every Request / Static Resources。规范摘要（AI中文改写，待人工核验，非逐字引句）：认证身份不等于所有资源权限；服务端按每个实际请求的主体、动作、资源归属检查，默认拒绝未许可访问。难猜ID/前端隐藏/只保护主路由都不能代替授权，静态导出和批量入口同样受约束。

本判断短引定位：Authorization is distinct from authentication

**实质变式候选**

订单详情已核归属拒绝；导出下载URL仍按文件ID公开返回B订单内容。

可接受：保详情修复，给导出实际读取路径补同样授权并核跨账号拒绝。

明确错误：登录成功且页面看不到链接就表示资源安全。

依据候选：主路由已安全不代表另一资源出口安全，授权必须覆盖实际下载。

反例：反例：订单详情已核归属拒绝；导出下载URL仍按文件ID公开返回B订单内容。 因此“登录成功且页面看不到链接就表示资源安全。”不成立。

来源：[auth](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/Authorization_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:dd56db698a11513111fc0a8e99e4f0e2492c86a5d82528c5a1db35434ca18cfc；OWASP Authorization, Validate the Permissions on Every Request / Static Resources。规范摘要（AI中文改写，待人工核验，非逐字引句）：认证身份不等于所有资源权限；服务端按每个实际请求的主体、动作、资源归属检查，默认拒绝未许可访问。难猜ID/前端隐藏/只保护主路由都不能代替授权，静态导出和批量入口同样受约束。

本判断短引定位：static resources must also be appropriately secured

变化依据：由“A已登录，API按传入订单ID直接返回B的订单；页面只隐藏B订单链接，服务端未核归属。”变为“订单详情已核归属拒绝；导出下载URL仍按文件ID公开返回B订单内容。”，故“按认证A与订单归属拒绝读取，增加直接API跨账号回归。”改为“保详情修复，给导出实际读取路径补同样授权并核跨账号拒绝。”。

仅改名反例：登录不等于拥有订单（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：真实读取路径缺少资源授权，UI隐藏不能保护直接请求。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## security.authorization-2 — 批量接口遗漏逐项归属

状态：pending_human_review；技术背景：security-evidence-v1；档位：进阶

**原题**

单条修改核归属，但批量请求仅核第一条；列表包含A订单与B订单，后者也被更新。

可接受：逐资源检查或拒绝整批混合越权请求，并验证B记录不变。

明确错误：第一条合法就代表同一批所有订单合法。

依据候选：每个实际被操作资源都需要授权，批量封装不能跳过归属。

反例：反例：单条修改核归属，但批量请求仅核第一条；列表包含A订单与B订单，后者也被更新。 因此“第一条合法就代表同一批所有订单合法。”不成立。

来源：[auth](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/Authorization_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:dd56db698a11513111fc0a8e99e4f0e2492c86a5d82528c5a1db35434ca18cfc；OWASP Authorization, Validate the Permissions on Every Request / Static Resources。规范摘要（AI中文改写，待人工核验，非逐字引句）：认证身份不等于所有资源权限；服务端按每个实际请求的主体、动作、资源归属检查，默认拒绝未许可访问。难猜ID/前端隐藏/只保护主路由都不能代替授权，静态导出和批量入口同样受约束。

本判断短引定位：Permission should be validated correctly on every request

**实质变式候选**

全部归属已逐条核；用户角色只允许读，批量写仍沿用读权限判断。

可接受：保归属检查，再按实际写动作核权限，不把可读当可改。

明确错误：第一条合法就代表同一批所有订单合法。

依据候选：主体与资源匹配还不足够，授权必须覆盖具体动作。

反例：反例：全部归属已逐条核；用户角色只允许读，批量写仍沿用读权限判断。 因此“第一条合法就代表同一批所有订单合法。”不成立。

来源：[auth](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/Authorization_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:dd56db698a11513111fc0a8e99e4f0e2492c86a5d82528c5a1db35434ca18cfc；OWASP Authorization, Validate the Permissions on Every Request / Static Resources。规范摘要（AI中文改写，待人工核验，非逐字引句）：认证身份不等于所有资源权限；服务端按每个实际请求的主体、动作、资源归属检查，默认拒绝未许可访问。难猜ID/前端隐藏/只保护主路由都不能代替授权，静态导出和批量入口同样受约束。

本判断短引定位：Permission should be validated correctly on every request

变化依据：由“单条修改核归属，但批量请求仅核第一条；列表包含A订单与B订单，后者也被更新。”变为“全部归属已逐条核；用户角色只允许读，批量写仍沿用读权限判断。”，故“逐资源检查或拒绝整批混合越权请求，并验证B记录不变。”改为“保归属检查，再按实际写动作核权限，不把可读当可改。”。

仅改名反例：批量接口遗漏逐项归属（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：每个实际被操作资源都需要授权，批量封装不能跳过归属。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## security.authorization-3 — 撤销后导出任务还读私有数据

状态：pending_human_review；技术背景：security-evidence-v1；档位：综合

**原题**

异步导出创建时有权限；任务执行前权限撤销，worker仍以创建时布尔快照读取整租户数据，尚未完成任何导出。

可接受：在实际执行读路径核当前授权，拒绝越界读取并保任务失败事实。

明确错误：创建时曾合法就能永久读取所有后来私有记录。

依据候选：旧授权快照不自动授予当前读取权，后台路径也不能遗漏权限检查。

反例：反例：异步导出创建时有权限；任务执行前权限撤销，worker仍以创建时布尔快照读取整租户数据，尚未完成任何导出。 因此“创建时曾合法就能永久读取所有后来私有记录。”不成立。

来源：[auth](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/Authorization_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:dd56db698a11513111fc0a8e99e4f0e2492c86a5d82528c5a1db35434ca18cfc；OWASP Authorization, Validate the Permissions on Every Request / Static Resources。规范摘要（AI中文改写，待人工核验，非逐字引句）：认证身份不等于所有资源权限；服务端按每个实际请求的主体、动作、资源归属检查，默认拒绝未许可访问。难猜ID/前端隐藏/只保护主路由都不能代替授权，静态导出和批量入口同样受约束。

本判断短引定位：Permission should be validated correctly on every request

**实质变式候选**

worker当前授权已核且只生成允许数据；下载链接却无身份绑定并长期公开。

可接受：保导出范围检查，约束实际下载授权和有效范围，不能把生成安全外推到交付。

明确错误：创建时曾合法就能永久读取所有后来私有记录。

依据候选：数据生成和下载是不同访问边界，后者仍须实际保护。

反例：反例：worker当前授权已核且只生成允许数据；下载链接却无身份绑定并长期公开。 因此“创建时曾合法就能永久读取所有后来私有记录。”不成立。

来源：[auth](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/Authorization_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:dd56db698a11513111fc0a8e99e4f0e2492c86a5d82528c5a1db35434ca18cfc；OWASP Authorization, Validate the Permissions on Every Request / Static Resources。规范摘要（AI中文改写，待人工核验，非逐字引句）：认证身份不等于所有资源权限；服务端按每个实际请求的主体、动作、资源归属检查，默认拒绝未许可访问。难猜ID/前端隐藏/只保护主路由都不能代替授权，静态导出和批量入口同样受约束。

本判断短引定位：static resources must also be appropriately secured

变化依据：由“异步导出创建时有权限；任务执行前权限撤销，worker仍以创建时布尔快照读取整租户数据，尚未完成任何导出。”变为“worker当前授权已核且只生成允许数据；下载链接却无身份绑定并长期公开。”，故“在实际执行读路径核当前授权，拒绝越界读取并保任务失败事实。”改为“保导出范围检查，约束实际下载授权和有效范围，不能把生成安全外推到交付。”。

仅改名反例：撤销后导出任务还读私有数据（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：旧授权快照不自动授予当前读取权，后台路径也不能遗漏权限检查。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## security.boundary-1 — 把模型文字当HTML

状态：pending_human_review；技术背景：security-evidence-v1；档位：基础

**原题**

产品只需显示模型的纯文字解释；页面却直接解析其原始HTML，受控恶意标签被浏览器当结构处理。

可接受：使用纯文本安全输出边界并保字面内容，不把模型文本当可信HTML。

明确错误：模型回答过安全问题所以其HTML可以直接执行。

依据候选：输入来源不改变浏览器解析语义，纯文本需求无需开放HTML执行。

反例：反例：产品只需显示模型的纯文字解释；页面却直接解析其原始HTML，受控恶意标签被浏览器当结构处理。 因此“模型回答过安全问题所以其HTML可以直接执行。”不成立。

来源：[xss](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:b6cfca5d70ccb0906372af03ca8473728aa1749a7efbb02f8fcdc70a68f0947e；OWASP XSS Prevention, HTML Contexts / Safe Sinks / URL defense。规范摘要（AI中文改写，待人工核验，非逐字引句）：纯文本可写入textContent而非当HTML解析；不同HTML/属性/URL上下文需要对应处理，HTML转义不能代替URL协议校验。需要富文本时另用适当维护的sanitizer并避免后续变换破坏结果；本题不要求或执行任何攻击脚本。

本判断短引定位：It is a **Safe Sink**

**实质变式候选**

解释已纯文本显示；另一个链接字段被直接放入href，输入协议不在允许的http/https内。

可接受：保文本输出，按链接上下文校验协议及目标，不能只做HTML转义。

明确错误：模型回答过安全问题所以其HTML可以直接执行。

依据候选：新sink是URL属性，安全文本输出不会自动验证可导航协议。

反例：反例：解释已纯文本显示；另一个链接字段被直接放入href，输入协议不在允许的http/https内。 因此“模型回答过安全问题所以其HTML可以直接执行。”不成立。

来源：[xss](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:b6cfca5d70ccb0906372af03ca8473728aa1749a7efbb02f8fcdc70a68f0947e；OWASP XSS Prevention, HTML Contexts / Safe Sinks / URL defense。规范摘要（AI中文改写，待人工核验，非逐字引句）：纯文本可写入textContent而非当HTML解析；不同HTML/属性/URL上下文需要对应处理，HTML转义不能代替URL协议校验。需要富文本时另用适当维护的sanitizer并避免后续变换破坏结果；本题不要求或执行任何攻击脚本。

本判断短引定位：Allow-list http and HTTPS URLs only

变化依据：由“产品只需显示模型的纯文字解释；页面却直接解析其原始HTML，受控恶意标签被浏览器当结构处理。”变为“解释已纯文本显示；另一个链接字段被直接放入href，输入协议不在允许的http/https内。”，故“使用纯文本安全输出边界并保字面内容，不把模型文本当可信HTML。”改为“保文本输出，按链接上下文校验协议及目标，不能只做HTML转义。”。

仅改名反例：把模型文字当HTML（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：输入来源不改变浏览器解析语义，纯文本需求无需开放HTML执行。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## security.boundary-2 — 只验首个URL挡不住重定向

状态：pending_human_review；技术背景：security-evidence-v1；档位：进阶

**原题**

服务只允许抓取外部公开网页；初始HTTPS地址解析为公网，但HTTP客户端自动跟随到内网目标，未二次检查。

可接受：禁止未核重定向并按实际目标限制出站，不能只验证初始字符串。

明确错误：HTTPS前缀存在就保证后续连接永不进入内网。

依据候选：协议名不证明最终网络目标，自动重定向能跨越最初校验边界。

反例：反例：服务只允许抓取外部公开网页；初始HTTPS地址解析为公网，但HTTP客户端自动跟随到内网目标，未二次检查。 因此“HTTPS前缀存在就保证后续连接永不进入内网。”不成立。

来源：[ssrf](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:d9323c8d09e4259ea597524fb1513422b8c82f96b287b79405f424b599e74da2；OWASP SSRF Prevention, Application layer / Domain name / redirection。规范摘要（AI中文改写，待人工核验，非逐字引句）：仅检查初始字符串或HTTPS不能证明目标安全；按实际出站策略核解析后的目标，防止DNS变化和重定向绕过。固定可信目标可用allowlist；任意外部目标场景不能假设同样固定清单。建议禁用自动重定向，并结合应用/网络层限制；不得把解析时合法自动当连接时合法。

本判断短引定位：Disable the support for the following

**实质变式候选**

已禁重定向；同域验证时是公网，连接前重新解析为内网，客户端未绑定已核目标。

可接受：核实际连接地址与解析变化，保域名TLS校验并阻止内网连接，不只重复字符串检查。

明确错误：HTTPS前缀存在就保证后续连接永不进入内网。

依据候选：重定向路径已关闭但DNS变化仍改变目标，需要保护真正连接边界。

反例：反例：已禁重定向；同域验证时是公网，连接前重新解析为内网，客户端未绑定已核目标。 因此“HTTPS前缀存在就保证后续连接永不进入内网。”不成立。

来源：[ssrf](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:d9323c8d09e4259ea597524fb1513422b8c82f96b287b79405f424b599e74da2；OWASP SSRF Prevention, Application layer / Domain name / redirection。规范摘要（AI中文改写，待人工核验，非逐字引句）：仅检查初始字符串或HTTPS不能证明目标安全；按实际出站策略核解析后的目标，防止DNS变化和重定向绕过。固定可信目标可用allowlist；任意外部目标场景不能假设同样固定清单。建议禁用自动重定向，并结合应用/网络层限制；不得把解析时合法自动当连接时合法。

本判断短引定位：bind a legit domain name to an internal IP address

变化依据：由“服务只允许抓取外部公开网页；初始HTTPS地址解析为公网，但HTTP客户端自动跟随到内网目标，未二次检查。”变为“已禁重定向；同域验证时是公网，连接前重新解析为内网，客户端未绑定已核目标。”，故“禁止未核重定向并按实际目标限制出站，不能只验证初始字符串。”改为“核实际连接地址与解析变化，保域名TLS校验并阻止内网连接，不只重复字符串检查。”。

仅改名反例：只验首个URL挡不住重定向（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：协议名不证明最终网络目标，自动重定向能跨越最初校验边界。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## security.boundary-3 — 删日志不能撤销已泄凭据

状态：pending_human_review；技术背景：security-evidence-v1；档位：综合

**原题**

受控假Key曾写入可公开读取日志，权限仍有效；团队只删除日志文件就宣布泄露恢复完成。

可接受：撤销受影响凭据、更新消费者并核异常使用，保脱敏审计证据，不把删文件当撤销。

明确错误：日志删除成功说明别人保存的Key也自动失效。

依据候选：已外泄秘密可被复制，只有删除本地载体不会限制其继续访问。

反例：反例：受控假Key曾写入可公开读取日志，权限仍有效；团队只删除日志文件就宣布泄露恢复完成。 因此“日志删除成功说明别人保存的Key也自动失效。”不成立。

来源：[secrets](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/Secrets_Management_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:302a2e4cb2153616a3c41d8a79d7407f24c03207fe60752892b71ec2776bc60c；OWASP Secrets Management, Revocation / lifecycle detection。规范摘要（AI中文改写，待人工核验，非逐字引句）：泄露或可能泄露的秘密需撤销并限制访问，再按恢复流程配置新凭据、核消费者与异常使用；只删日志不撤销可用凭据。秘密不以明文进入日志，应遮蔽/保护；有审计记录不等于已验证无滥用，保必要脱敏证据并核访问范围。

本判断短引定位：When secrets are no longer required or potentially compromised

**实质变式候选**

受影响Key已撤销且新Key只存秘密管理系统；应用调试路径仍把新Key明文写入日志。

可接受：保旧Key撤销事实，修新日志泄漏并再次处理已暴露的新Key，验证日志不含明文。

明确错误：日志删除成功说明别人保存的Key也自动失效。

依据候选：旧凭据恢复不保护后来再次泄出的秘密，需修产生泄漏的实际路径。

反例：反例：受影响Key已撤销且新Key只存秘密管理系统；应用调试路径仍把新Key明文写入日志。 因此“日志删除成功说明别人保存的Key也自动失效。”不成立。

来源：[secrets](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/382113ba1fbd7e99ffa21bcf90d7fd8a19be546b/cheatsheets/Secrets_Management_Cheat_Sheet.md)；OWASP/CheatSheetSeries commit 382113ba1fbd7e99ffa21bcf90d7fd8a19be546b; response-sha256:302a2e4cb2153616a3c41d8a79d7407f24c03207fe60752892b71ec2776bc60c；OWASP Secrets Management, Revocation / lifecycle detection。规范摘要（AI中文改写，待人工核验，非逐字引句）：泄露或可能泄露的秘密需撤销并限制访问，再按恢复流程配置新凭据、核消费者与异常使用；只删日志不撤销可用凭据。秘密不以明文进入日志，应遮蔽/保护；有审计记录不等于已验证无滥用，保必要脱敏证据并核访问范围。

本判断短引定位：Never be logged (must implement

变化依据：由“受控假Key曾写入可公开读取日志，权限仍有效；团队只删除日志文件就宣布泄露恢复完成。”变为“受影响Key已撤销且新Key只存秘密管理系统；应用调试路径仍把新Key明文写入日志。”，故“撤销受影响凭据、更新消费者并核异常使用，保脱敏审计证据，不把删文件当撤销。”改为“保旧Key撤销事实，修新日志泄漏并再次处理已暴露的新Key，验证日志不含明文。”。

仅改名反例：删日志不能撤销已泄凭据（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：已外泄秘密可被复制，只有删除本地载体不会限制其继续访问。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。
