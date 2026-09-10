# 逐条审阅清单

所有条目：AI起草／待人工核验；以下标签均为候选。

## systems.cost-1 · 队首移除为何变慢 · 基础

目标：systems.cost；背景：systems-evidence-v1。

教学伪代码：队列用顺序列表；每次移除第0项都移动其余元素。队长由100增至10000；每批移除次数相同。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：先比较每次移动元素数，并考虑双端队列
依据：列表队首移除会移动后续元素；队长增加会放大这部分工作。双端队列适合两端操作，但此处未证明全程序必然更快。
错误候选：线程数决定每次移除移动多少元素。

正变式：相同规模，改为只从列表末尾移除；给定实现不移动其余元素。
新行动：不再以队首移动解释；测量其余耗时
变化依据：关键操作已变为末尾移除，原先队首搬移原因不成立；需新观测定位。
非变式：队首移除为何变慢（换名版），只改标题，不能作为陌生题。

方向帮助候选：列表队首移除会移动后续元素；队长增加会放大这部分工作。双端队列适合两端操作，但此处未证明全程序必然更快。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [queue](https://raw.githubusercontent.com/python/cpython/v3.14.5/Doc/tutorial/datastructures.rst)：CPython v3.14.5 / §5.1.2 Using Lists as Queues; whitespace-normalized exact excerpts。
- 变式 [queue](https://raw.githubusercontent.com/python/cpython/v3.14.5/Doc/tutorial/datastructures.rst)：CPython v3.14.5 / §5.1.2 Using Lists as Queues; whitespace-normalized exact excerpts。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## systems.cost-2 · 快队列仍会积压 · 进阶

目标：systems.cost；背景：systems-evidence-v1。

双端队列每秒进入2000项、移出1000项，持续60秒；每项固定占1KiB，忽略容器开销；初始为空。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：队列净增60000项；约58.6MiB，不把快速出队当容量保证
依据：净增率1000项每秒，60秒为60000KiB；两端操作快不改变生产快于消费造成的积压，应限制积压或提高消费并实测。
错误候选：换容器后生产消费差额自动消失。

正变式：保持每项1KiB与60秒，改为进入1000项/秒、移出能力2000项/秒，空队列时等待。
新行动：不预测持续净积压；仍测量瞬时峰值
变化依据：消费能力已高于进入率，原持续净增条件消失；排队峰值仍依到达波动而定。
非变式：快队列仍会积压（换名版），只改标题，不能作为陌生题。

方向帮助候选：净增率1000项每秒，60秒为60000KiB；两端操作快不改变生产快于消费造成的积压，应限制积压或提高消费并实测。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [queue](https://raw.githubusercontent.com/python/cpython/v3.14.5/Doc/tutorial/datastructures.rst)：CPython v3.14.5 / §5.1.2 Using Lists as Queues; whitespace-normalized exact excerpts。
- 变式 [queue](https://raw.githubusercontent.com/python/cpython/v3.14.5/Doc/tutorial/datastructures.rst)：CPython v3.14.5 / §5.1.2 Using Lists as Queues; whitespace-normalized exact excerpts。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## systems.cost-3 · 容器优化与容量上限 · 综合

目标：systems.cost；背景：systems-evidence-v1。

教学测量：需同时保留1000万项，每项64字节；可用内存512MiB；列表和双端队列都必须保留全部项。每批从头消费，禁止静默丢项。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：同时处理搬移和容量：限制在途或分批持久化，验证峰值及完整性
依据：仅有效载荷640000000字节已超过512MiB，换双端队列不能让全部数据装下。需在不丢项约束下控制在途，再测内存和首尾操作代价。
错误候选：出队更快等于所有数据不用占内存。

正变式：保持1000万项，但明确上游可等待且在内存中最多同时保留10000项，其余已在外部持久化；预算仍512MiB。
新行动：按10000项计算在途载荷并验证队列峰值与持久化完整性
变化依据：现在同时保留量受控，仅载荷640000字节；不能再按1000万同时驻留断定必超限，仍应测容器与处理开销。
非变式：容器优化与容量上限（换名版），只改标题，不能作为陌生题。

方向帮助候选：仅有效载荷640000000字节已超过512MiB，换双端队列不能让全部数据装下。需在不丢项约束下控制在途，再测内存和首尾操作代价。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [queue](https://raw.githubusercontent.com/python/cpython/v3.14.5/Doc/tutorial/datastructures.rst)：CPython v3.14.5 / §5.1.2 Using Lists as Queues; whitespace-normalized exact excerpts。
- 原题 [queue](https://raw.githubusercontent.com/python/cpython/v3.14.5/Doc/tutorial/datastructures.rst)：CPython v3.14.5 / §5.1.2 Using Lists as Queues; whitespace-normalized exact excerpts。
- 变式 [queue](https://raw.githubusercontent.com/python/cpython/v3.14.5/Doc/tutorial/datastructures.rst)：CPython v3.14.5 / §5.1.2 Using Lists as Queues; whitespace-normalized exact excerpts。
- 变式 [queue](https://raw.githubusercontent.com/python/cpython/v3.14.5/Doc/tutorial/datastructures.rst)：CPython v3.14.5 / §5.1.2 Using Lists as Queues; whitespace-normalized exact excerpts。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## systems.execution-1 · 线程名不同并不隔离内存 · 基础

目标：systems.execution；背景：systems-evidence-v1。

同一进程的两个线程引用同一个列表。线程A追加一个标记后发信号；线程B收到信号后读取该列表；没有其他写者。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：B可见共享列表新增标记
依据：题面已给出同一对象和先写后读的同步顺序。线程共享进程内存，线程名不同不构成对象隔离。
错误候选：两个线程名字不同，所以对象必然互不影响。

正变式：两个线程各引用独立创建的列表；A只追加自己的列表，B只读取自己的列表。
新行动：B的独立列表不因A的追加而变化
变化依据：实际对象归属已改变；共享进程地址空间不意味着两个独立列表是同一对象。
非变式：线程名不同并不隔离内存（换名版），只改标题，不能作为陌生题。

方向帮助候选：题面已给出同一对象和先写后读的同步顺序。线程共享进程内存，线程名不同不构成对象隔离。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [thread](https://raw.githubusercontent.com/python/cpython/v3.14.5/Doc/library/threading.rst)：CPython v3.14.5 / Introduction, Lock objects, Thread objects; whitespace-normalized exact excerpts。
- 变式 [thread](https://raw.githubusercontent.com/python/cpython/v3.14.5/Doc/library/threading.rst)：CPython v3.14.5 / Introduction, Lock objects, Thread objects; whitespace-normalized exact excerpts。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## systems.execution-2 · 锁住一半仍丢更新 · 进阶

目标：systems.execution；背景：systems-evidence-v1。

教学时序：共享计数初始0。A和B都在锁外读到0，再各自在同一锁内写回读值加1；最终为1。读与写是分开的动作。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：把整个读改写放进同一临界区，并验证并发最终值
依据：锁仅串行化写入，两个线程已拿到相同旧值。不能由单次写互斥推出整个读改写原子。
错误候选：写入有锁就保证所有此前读取都是最新。

正变式：读取、加1和写回都在同一锁内完成；两个线程各执行一次，初值0，无其他写者。
新行动：在给定模型下最终应为2；用并发屏障复验
变化依据：读取也受同一锁保护，后进入者读取前次写回的1，消除了丢更新时序。
非变式：锁住一半仍丢更新（换名版），只改标题，不能作为陌生题。

方向帮助候选：锁仅串行化写入，两个线程已拿到相同旧值。不能由单次写互斥推出整个读改写原子。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [thread](https://raw.githubusercontent.com/python/cpython/v3.14.5/Doc/library/threading.rst)：CPython v3.14.5 / Introduction, Lock objects, Thread objects; whitespace-normalized exact excerpts。
- 变式 [thread](https://raw.githubusercontent.com/python/cpython/v3.14.5/Doc/library/threading.rst)：CPython v3.14.5 / Introduction, Lock objects, Thread objects; whitespace-normalized exact excerpts。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## systems.execution-3 · 进程退出前的后台写入 · 综合

目标：systems.execution；背景：systems-evidence-v1。

主线程收到任务后仅放进内存队列即响应已接收。后台daemon线程尚未落盘，进程随主线程结束；无持久队列、无落盘回执。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：保留未确认状态；采用持久接收或受控非daemon收尾并验证断电边界
依据：daemon线程关闭时可能被直接停止；已接收不是已持久。非daemon加等待可改善正常退出，但也不能单独保证断电不丢。
错误候选：daemon线程一定会在进程退出前写完所有任务。

正变式：主线程只在持久存储提交成功回执后响应，后台daemon仅生成可重建索引；题面已核对提交记录。
新行动：保留已持久任务，另检查索引可重建性
变化依据：持久任务已有提交证据，daemon停止只影响派生索引；不应撤销已核实的持久成果。
非变式：进程退出前的后台写入（换名版），只改标题，不能作为陌生题。

方向帮助候选：daemon线程关闭时可能被直接停止；已接收不是已持久。非daemon加等待可改善正常退出，但也不能单独保证断电不丢。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [thread](https://raw.githubusercontent.com/python/cpython/v3.14.5/Doc/library/threading.rst)：CPython v3.14.5 / Introduction, Lock objects, Thread objects; whitespace-normalized exact excerpts。
- 变式 [thread](https://raw.githubusercontent.com/python/cpython/v3.14.5/Doc/library/threading.rst)：CPython v3.14.5 / Introduction, Lock objects, Thread objects; whitespace-normalized exact excerpts。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## frontend.state-1 · 旧搜索回包覆盖新词 · 基础

目标：frontend.state；背景：frontend-evidence-v1。

给定页面规则：每次回包直接写结果。输入甲发请求A，再输入乙发B；B先返回乙，A后返回甲；当前输入仍乙。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：回包写入前比较请求身份，拒绝A覆盖乙
依据：请求A已不对应当前输入，给定直接写入规则会产生过时结果。取消信号不是既有回调写入的身份校验。
错误候选：最后收到的回包天然属于最新输入。

正变式：用户仍输入甲，仅存在请求A；返回时身份仍与当前输入匹配，无本地新编辑。
新行动：可以接纳A结果，并保留身份检查
变化依据：原先过时条件不存在；一律拒绝晚到回包也会丢掉当前合法结果。
非变式：旧搜索回包覆盖新词（换名版），只改标题，不能作为陌生题。

方向帮助候选：请求A已不对应当前输入，给定直接写入规则会产生过时结果。取消信号不是既有回调写入的身份校验。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [dom](https://dom.spec.whatwg.org/)：DOM living standard retrieved 2026-09-09 / #aborting-ongoing-activities; whitespace-normalized exact excerpts。
- 变式 [dom](https://dom.spec.whatwg.org/)：DOM living standard retrieved 2026-09-09 / #aborting-ongoing-activities; whitespace-normalized exact excerpts。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## frontend.state-2 · 取消之后已排队的回调 · 进阶

目标：frontend.state；背景：frontend-evidence-v1。

给定适配器：请求A的成功回调已入应用队列；用户切换B后调用abort。适配器不会撤销已排队回调，回调仍会直接set结果。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：取消与结果身份检查同时做，旧A回调不能写B
依据：题面明确取消不会移除已排队回调；DOM的abort机制需要API配合，不能推断任意应用回调自动消失。
错误候选：所有Promise都有内建撤销已完成回调的能力。

正变式：适配器将A回调移出应用队列，并给出队列为空的确认；B仍有身份守卫。
新行动：按已确认取消事实处理A，继续接纳B当前结果
变化依据：现在有实际移除确认，不能再声称A回调一定执行；B身份守卫仍有必要处理其他竞争。
非变式：取消之后已排队的回调（换名版），只改标题，不能作为陌生题。

方向帮助候选：题面明确取消不会移除已排队回调；DOM的abort机制需要API配合，不能推断任意应用回调自动消失。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [dom](https://dom.spec.whatwg.org/)：DOM living standard retrieved 2026-09-09 / #aborting-ongoing-activities; whitespace-normalized exact excerpts。
- 变式 [dom](https://dom.spec.whatwg.org/)：DOM living standard retrieved 2026-09-09 / #aborting-ongoing-activities; whitespace-normalized exact excerpts。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## frontend.state-3 · 同一搜索词跨账号返回 · 综合

目标：frontend.state；背景：frontend-evidence-v1。

账号甲发搜索X后退出，账号乙登录也搜索X；甲的旧响应迟到。缓存键只有搜索词，组件未换实例，写入只核搜索词一致。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：把账号会话与请求代次纳入结果归属，禁止甲回包写乙缓存
依据：相同搜索词不等同相同授权主体；给定缓存和回调规则可跨会话污染。需要清理与归属守卫，不能声称abort擦除了所有旧数据。
错误候选：相同输入意味着不同账号可共用私有结果。

正变式：甲请求已结束；乙的新请求和响应均绑定乙会话及当前请求代次，缓存按账号隔离，无旧回调。
新行动：接纳乙当前响应，并验证跨账号缓存隔离
变化依据：真实归属已一致且隔离存在，不必因搜索词曾出现就拒绝所有乙结果。
非变式：同一搜索词跨账号返回（换名版），只改标题，不能作为陌生题。

方向帮助候选：相同搜索词不等同相同授权主体；给定缓存和回调规则可跨会话污染。需要清理与归属守卫，不能声称abort擦除了所有旧数据。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [dom](https://dom.spec.whatwg.org/)：DOM living standard retrieved 2026-09-09 / #aborting-ongoing-activities; whitespace-normalized exact excerpts。
- 变式 [dom](https://dom.spec.whatwg.org/)：DOM living standard retrieved 2026-09-09 / #aborting-ongoing-activities; whitespace-normalized exact excerpts。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## frontend.accessibility-1 · 只能鼠标点的提交 · 基础

目标：frontend.accessibility；背景：frontend-evidence-v1。

给定DOM教学记录：提交是无tabindex且无键盘事件的普通div；鼠标可点。Tab遍历完整页面未聚焦该元素，无替代提交入口。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：确认键盘提交被阻断，改用可键盘操作控件并实测
依据：提交不属于依赖运动路径的例外，当前唯一入口无法经键盘到达。应验证聚焦及激活，而不只看颜色。
错误候选：鼠标点击通过等同键盘路径已验证。

正变式：提交改为原生button，Tab能聚焦，Enter和Space实测均完成一次提交；其他条件不变。
新行动：确认本次键盘提交路径通过，但不宣称全站无障碍合格
变化依据：关键阻断已有实际聚焦与激活证据消除，局部通过不外推所有标准。
非变式：只能鼠标点的提交（换名版），只改标题，不能作为陌生题。

方向帮助候选：提交不属于依赖运动路径的例外，当前唯一入口无法经键盘到达。应验证聚焦及激活，而不只看颜色。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [keyboard](https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html)：WCAG 2.2 Understanding SC2.1.1 / Success Criterion; whitespace-normalized exact excerpts。
- 变式 [keyboard](https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html)：WCAG 2.2 Understanding SC2.1.1 / Success Criterion; whitespace-normalized exact excerpts。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## frontend.accessibility-2 · 红边框没有错误说明 · 进阶

目标：frontend.accessibility；背景：frontend-evidence-v1。

表单自动检测到邮编为空，提交被拒；仅输入框边框变红，没有文字提示，既有label只写邮编。已提供键盘焦点路径。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：增加与邮编关联的明确文字错误说明，保输入并复测
依据：键盘可达不证明错误可理解；自动发现的错误需要识别字段并用文字说明。只有颜色未提供这一信息。
错误候选：颜色明显就等同已经说明哪个字段为什么错误。

正变式：输入旁出现关联的文字“邮编不能为空”，辅助技术可读出关联；已有值保留，键盘可达。
新行动：确认该空值错误可识别，另测其他校验分支
变化依据：所缺文字和关联已有明确证据，不能把未测的其他错误分支也判通过。
非变式：红边框没有错误说明（换名版），只改标题，不能作为陌生题。

方向帮助候选：键盘可达不证明错误可理解；自动发现的错误需要识别字段并用文字说明。只有颜色未提供这一信息。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [errors](https://www.w3.org/WAI/WCAG22/Understanding/error-identification.html)：WCAG 2.2 Understanding SC3.3.1 / Success Criterion; whitespace-normalized exact excerpts。
- 变式 [errors](https://www.w3.org/WAI/WCAG22/Understanding/error-identification.html)：WCAG 2.2 Understanding SC3.3.1 / Success Criterion; whitespace-normalized exact excerpts。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## frontend.accessibility-3 · 放大后入口被固定层遮挡 · 综合

目标：frontend.accessibility；背景：frontend-evidence-v1。

垂直表单在320CSS像素宽度出现横向裁剪；无二维布局必要；底部固定层遮住提交，键盘聚焦后也不能看见或触发；缩小字号能暂时露出。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：修复重排及固定层遮挡，保文字缩放并复测键盘提交
依据：仅缩小字绕过了用户阅读需求。该普通表单没有二维例外，应保留信息和操作；同时验证焦点及唯一提交路径。
错误候选：320CSS像素的普通表单可以无条件丢失操作入口。

正变式：同表单在320CSS像素重排，无横向裁剪；固定层让出空间，键盘聚焦可见且可提交；长错误文本也已复测。
新行动：记录该矩阵通过，保留未测内容与设备限制
变化依据：此前两类阻断已有可观察结果消除；这不等同所有屏幕和内容都已验证。
非变式：放大后入口被固定层遮挡（换名版），只改标题，不能作为陌生题。

方向帮助候选：仅缩小字绕过了用户阅读需求。该普通表单没有二维例外，应保留信息和操作；同时验证焦点及唯一提交路径。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html)：WCAG 2.2 Understanding SC1.4.10 / Success Criterion; whitespace-normalized exact excerpts。
- 原题 [keyboard](https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html)：WCAG 2.2 Understanding SC2.1.1 / Success Criterion; whitespace-normalized exact excerpts。
- 变式 [reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html)：WCAG 2.2 Understanding SC1.4.10 / Success Criterion; whitespace-normalized exact excerpts。
- 变式 [keyboard](https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html)：WCAG 2.2 Understanding SC2.1.1 / Success Criterion; whitespace-normalized exact excerpts。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## network.trace-1 · TLS警报前没有HTTP · 基础

目标：network.trace；背景：network-evidence-v1。

客户端DNS解析成功并建立TCP；TLS收到unknown_ca后终止；本次没有发送HTTP请求，服务端应用无该请求ID记录。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：先核TLS信任链与服务身份，不修改应用JSON
依据：本次终止发生在HTTP发送之前；给定unknown_ca线索指向证书链信任检查，不能把它当应用500。
错误候选：TCP连通就代表TLS和HTTP都成功。

正变式：同目标TLS验证成功，HTTP已发，应用返回带请求ID的500与异常记录。
新行动：转向应用异常及对应请求记录
变化依据：失败阶段已跨过握手并有应用500证据，继续只查证书无法解释这个已确认错误。
非变式：TLS警报前没有HTTP（换名版），只改标题，不能作为陌生题。

方向帮助候选：本次终止发生在HTTP发送之前；给定unknown_ca线索指向证书链信任检查，不能把它当应用500。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [tls](https://www.rfc-editor.org/rfc/rfc8446.txt)：RFC8446 August2018 / §6.2 unknown_ca alert definition: CA not located or not matched to known trust anchor; whitespace-normalized exact excerpt.。
- 变式 [http](https://www.rfc-editor.org/rfc/rfc9110.txt)：RFC9110 June2022 / §9.2.2 first paragraph PUT list and third paragraph non-idempotent retry exceptions; §15.6.5 504 timely response; §15.6.1 500 unexpected condition. Whitespace-normalized exact fragments; read full cited paragraphs for qualifiers.。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## network.trace-2 · 代理504不等于事务回滚 · 进阶

目标：network.trace；背景：network-evidence-v1。

客户端收到代理504；代理记录等待上游超时；上游是否提交未知，没有对应提交日志。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：定位代理上游等待并补查请求ID提交证据
依据：504说明网关没有及时收到所需上游响应，不说明上游是否已执行或回滚；先补证而非宣判未执行。
错误候选：代理没及时收响应就是上游没有产生效果。

正变式：代理仍504，但补得同请求ID已提交成功记录，存储状态与业务结果一致。
新行动：保留已提交结果，继续查响应链路超时
变化依据：新增提交证据排除了未知执行状态；504仍可与上游成功同时发生。
非变式：代理504不等于事务回滚（换名版），只改标题，不能作为陌生题。

方向帮助候选：504说明网关没有及时收到所需上游响应，不说明上游是否已执行或回滚；先补证而非宣判未执行。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [http](https://www.rfc-editor.org/rfc/rfc9110.txt)：RFC9110 June2022 / §9.2.2 first paragraph PUT list and third paragraph non-idempotent retry exceptions; §15.6.5 504 timely response; §15.6.1 500 unexpected condition. Whitespace-normalized exact fragments; read full cited paragraphs for qualifiers.。
- 变式 [http](https://www.rfc-editor.org/rfc/rfc9110.txt)：RFC9110 June2022 / §9.2.2 first paragraph PUT list and third paragraph non-idempotent retry exceptions; §15.6.5 504 timely response; §15.6.1 500 unexpected condition. Whitespace-normalized exact fragments; read full cited paragraphs for qualifiers.。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## network.trace-3 · 两段TLS不能混为一段 · 综合

目标：network.trace；背景：network-evidence-v1。

浏览器到边缘代理TLS验证成功；边缘到上游为另一TLS连接，日志显示unknown_ca；无上游HTTP请求，边缘给浏览器502。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：分段查上游信任链，不关闭浏览器证书验证；用同请求ID验证恢复
依据：前段TLS成功不能证明后段成功。给定失败位于边缘到上游握手，关闭浏览器验证不修复它且破坏保护。
错误候选：浏览器到边缘的成功代表上游TLS也一定成功。

正变式：两段TLS均验证成功；上游记录同请求ID已经提交，但响应晚于代理超时，浏览器收到504。
新行动：保留已提交成果，定位代理等待与响应链路，保留两段TLS验证
变化依据：两段TLS已成功，且有上游提交证据；504只说明代理未及时收到响应，不证明未提交。应定位超时链路，不关闭证书校验。
非变式：两段TLS不能混为一段（换名版），只改标题，不能作为陌生题。

方向帮助候选：前段TLS成功不能证明后段成功。给定失败位于边缘到上游握手，关闭浏览器验证不修复它且破坏保护。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [tls](https://www.rfc-editor.org/rfc/rfc8446.txt)：RFC8446 August2018 / §6.2 unknown_ca alert definition: CA not located or not matched to known trust anchor; whitespace-normalized exact excerpt.。
- 变式 [http](https://www.rfc-editor.org/rfc/rfc9110.txt)：RFC9110 June2022 / §9.2.2 first paragraph PUT list and third paragraph non-idempotent retry exceptions; §15.6.5 504 timely response; §15.6.1 500 unexpected condition. Whitespace-normalized exact fragments; read full cited paragraphs for qualifiers.。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## network.delivery-1 · 无响应的请求能否直接重发 · 基础

目标：network.delivery；背景：network-evidence-v1。

一个POST创建订单请求已发送，响应连接断开；无幂等约定、无提交查询结果，不知道是否生成订单。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：先查提交状态或取得应用幂等保障，不盲目自动重发
依据：不能由无响应推出未执行；给定POST没有幂等保障，自动重发可能创建重复订单。补证是本题有效结论。
错误候选：响应丢失保证服务端没有执行。

正变式：方法改为PUT设定同一资源的目标状态；服务端符合HTTP幂等语义，无额外业务重复创建动作；连接在响应前断开。
新行动：可按幂等语义重试同一PUT，但不保证响应或计费相同
变化依据：同一请求的预期资源效果具幂等性；这不承诺每次日志、响应或供应商费用一致。
非变式：无响应的请求能否直接重发（换名版），只改标题，不能作为陌生题。

方向帮助候选：不能由无响应推出未执行；给定POST没有幂等保障，自动重发可能创建重复订单。补证是本题有效结论。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [http](https://www.rfc-editor.org/rfc/rfc9110.txt)：RFC9110 June2022 / §9.2.2 first paragraph PUT list and third paragraph non-idempotent retry exceptions; §15.6.5 504 timely response; §15.6.1 500 unexpected condition. Whitespace-normalized exact fragments; read full cited paragraphs for qualifiers.。
- 变式 [http](https://www.rfc-editor.org/rfc/rfc9110.txt)：RFC9110 June2022 / §9.2.2 first paragraph PUT list and third paragraph non-idempotent retry exceptions; §15.6.5 504 timely response; §15.6.1 500 unexpected condition. Whitespace-normalized exact fragments; read full cited paragraphs for qualifiers.。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## network.delivery-2 · 已经确认的写入不该再新建 · 进阶

目标：network.delivery；背景：network-evidence-v1。

客户端写请求超时，但状态查询已返回同一请求ID的已提交订单，订单内容核对一致；重发会生成新请求ID。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：保留既有订单，不另造新ID重复创建
依据：已取得对应提交证据，重复新ID创建不是恢复原结果。网络失败不能抹掉已核实业务成果。
错误候选：超时比已提交记录更能证明订单不存在。

正变式：查询仍无结论且查询系统可能延迟；重发仍生成新请求ID，没有幂等保证。
新行动：保留交付未知并补查，不称已成功或已失败
变化依据：原来的成功证据缺失；不能把查不到立即当没执行，也不能伪造已完成记录。
非变式：已经确认的写入不该再新建（换名版），只改标题，不能作为陌生题。

方向帮助候选：已取得对应提交证据，重复新ID创建不是恢复原结果。网络失败不能抹掉已核实业务成果。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [http](https://www.rfc-editor.org/rfc/rfc9110.txt)：RFC9110 June2022 / §9.2.2 first paragraph PUT list and third paragraph non-idempotent retry exceptions; §15.6.5 504 timely response; §15.6.1 500 unexpected condition. Whitespace-normalized exact fragments; read full cited paragraphs for qualifiers.。
- 变式 [http](https://www.rfc-editor.org/rfc/rfc9110.txt)：RFC9110 June2022 / §9.2.2 first paragraph PUT list and third paragraph non-idempotent retry exceptions; §15.6.5 504 timely response; §15.6.1 500 unexpected condition. Whitespace-normalized exact fragments; read full cited paragraphs for qualifiers.。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）

## network.delivery-3 · 三段响应不是完整交付 · 综合

目标：network.delivery；背景：network-evidence-v1。

应用协议声明四段加最终完整标记才算完整；客户端只持久化前三段，连接断开；服务端任务可能完成，续传必须用同任务ID和已持久偏移，协议支持幂等续传。 请选下一步，并说明依据、不能推出的结论和验证方式。

可接受候选：保留前三段与完整性未知，按同任务和偏移续传并校验最终标记
依据：部分内容已实际保存，不能归零，也没有第四段和最终标记来宣称完整；新建任务重跑可能重复成本，续传边界须核对。
错误候选：连接断开意味着已保存内容从未交付，而且任务一定失败。

正变式：客户端已持久化四段及经校验最终完整标记，随后连接断开；同任务ID与内容摘要匹配。
新行动：保留完整成果，不因之后断连撤销完成
变化依据：应用定义的完整证据已先持久化，后来的连接事件不能将原有完整交付改成未交付。
非变式：三段响应不是完整交付（换名版），只改标题，不能作为陌生题。

方向帮助候选：部分内容已实际保存，不能归零，也没有第四段和最终标记来宣称完整；新建任务重跑可能重复成本，续传边界须核对。
中性候选：证据是用来核对一项判断的材料；没有某条记录时，应区分未知和已经确认相反。
不确定候选：当前材料外的实现是否相同尚不明确，需要再核对适用边界。

逐命题来源定位（短引用见JSON；标准规则不冒充题面观测）：
- 原题 [http](https://www.rfc-editor.org/rfc/rfc9110.txt)：RFC9110 June2022 / §9.2.2 first paragraph PUT list and third paragraph non-idempotent retry exceptions; §15.6.5 504 timely response; §15.6.1 500 unexpected condition. Whitespace-normalized exact fragments; read full cited paragraphs for qualifiers.。
- 变式 [http](https://www.rfc-editor.org/rfc/rfc9110.txt)：RFC9110 June2022 / §9.2.2 first paragraph PUT list and third paragraph non-idempotent retry exceptions; §15.6.5 504 timely response; §15.6.1 500 unexpected condition. Whitespace-normalized exact fragments; read full cited paragraphs for qualifiers.。

人工待核：来源□ 标签□ 多解/补证□ 变式□ 帮助边界□（空框不是已签核）
