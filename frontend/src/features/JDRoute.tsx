import { useEffect, useRef, useState } from "react"
import { JdsService, TopicsService, ModelconfigService, type JDPublic, type ModelConfigPublic, type Goal, type EvidenceView, type UnitAccess, type EvidenceKey } from "../client"
import { Button } from "../components/ui/button"

const cls = "h-auto min-h-9 max-w-full whitespace-normal"
function Evidence({ value }: { value?: EvidenceView }) {
  const status = value?.status ?? "unknown"
  return <div><p>{({ unknown: "证据未知，不能据此判断你不会", unverified: "尚未验证，不表示不会", verified: "此能力、难度与背景已有独立证据", needs_consolidation: "此能力需巩固，历史证据保留" })[status]}</p>{value?.original_ids?.map(id => <p key={id} className="break-all">证据原答：{id}</p>)}</div>
}
export function JDRoute() {
  const [open, setOpen] = useState(() => new URLSearchParams(location.search).has("jd"))
  return <section aria-label="JD 定向路线" className="space-y-3 border p-3 break-words"><h2>按招聘要求安排练习</h2><p>先看原文与能力映射，再选择岗位、调整重点并确认。推演案例是教学模拟。</p><Button className={cls} variant="outline" onClick={() => setOpen(v => !v)}>{open ? "收起 JD 路线" : "输入 JD 或恢复路线"}</Button>{open && <Editor />}</section>
}
function Editor() {
  const [items, setItems] = useState<JDPublic[]>([]), [selected, setSelected] = useState(() => new URLSearchParams(location.search).get("jd") ?? "")
  const [text, setText] = useState(""), [config, setConfig] = useState<ModelConfigPublic | null>(null)
  const [accepted, setAccepted] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("")
  const [drafts, setDrafts] = useState<Record<string, { topic: string; goal: Goal }>>({}), [access, setAccess] = useState<UnitAccess | null>(null)
  const alive = useRef(true), owner = useRef(sessionStorage.getItem("token")), serial = useRef(0)
  const pending = useRef<{ key: string; id: string; topic: string } | null>(null), pendingStart = useRef<{ key: string; id: string } | null>(null)
  const current = () => alive.current && owner.current === sessionStorage.getItem("token")
  const item = items.find(v => v.topic.id === selected), version = item?.current?.route.id ? item.current.route : null
  const dirty = Object.entries(drafts).some(([id, draft]) => {
    if (draft.topic !== selected) return false
    const node = version?.nodes.find(n => n.id === id)
    return !node || draft.goal.text !== node.text || draft.goal.focus !== node.focus || draft.goal.target.capability_id !== node.target.capability_id || draft.goal.target.background_id !== node.target.background_id || draft.goal.target.difficulty !== node.target.difficulty
  })
  const unsavedMessage = "本机修改尚未保存，请先保存再确认路线和开题；保留的冲突输入须明确处理。"
  const running = item?.topic.jobs.some(j => ["queued", "running", "stopping"].includes(j.status))
  function install(value: JDPublic) { if (value?.topic?.id) setItems(old => [value, ...old.filter(v => v.topic.id !== value.topic.id)]) }
  function choose(id: string) { setSelected(id); setAccess(null); const url = new URL(location.href); if (id) url.searchParams.set("jd", id); else url.searchParams.delete("jd"); history.replaceState(null, "", url) }
  async function read() {
    const turn = ++serial.current
    try {
      const [routes, model] = await Promise.all([JdsService.listJds(), ModelconfigService.readConfig()])
      if (current() && turn === serial.current) { setItems(routes.data); setConfig(model.data?.version ? model.data : null); setAccepted(false); setError("") }
    } catch { if (current() && turn === serial.current) setError("读取失败；保留已有路线与本机输入，请重读。证据读取失败不能解释成不会。") }
  }
  useEffect(() => { alive.current = true; void read(); return () => { alive.current = false; serial.current++ } }, [])
  useEffect(() => {
    if (!running || !selected) return
    let active = true
    const timer = window.setInterval(() => { const turn = serial.current; void JdsService.readJd({ path: { topic_id: selected } }).then(({ data }) => { if (active && current() && turn === serial.current) install(data) }).catch(() => { if (active && current()) setError("连接中断，任务可能仍在继续；重读同一记录，输入保留。") }) }, 1200)
    return () => { active = false; clearInterval(timer) }
  }, [selected, running])
  async function act(operation: () => Promise<void>) {
    if (busy) return
    serial.current++; setBusy(true); setError(""); setAccess(null)
    try { await operation() } catch (e) {
      const detail = (e as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      if (current()) { const blocked = detail as { message?: string; access?: UnitAccess } | null; if (blocked?.access?.target?.capability_id) setAccess(blocked.access); setError(typeof detail === "string" ? detail : blocked?.message ?? "操作尚未确认成功，输入保留；请读取记录，不必重复创建。") }
    } finally { if (current()) setBusy(false) }
  }
  async function refresh(id: string) { const { data } = await JdsService.readJd({ path: { topic_id: id } }); if (current()) install(data) }
  async function analyze() {
    if (!text.trim() || !config?.version || config.revoked || !accepted) return
    const key = JSON.stringify({ text, selected, version: version?.id, config: config.version })
    if (pending.current?.key !== key) pending.current = { key, id: crypto.randomUUID(), topic: item?.topic.id ?? crypto.randomUUID() }
    const { data } = await JdsService.analyzeJd({ body: { request_id: pending.current.id, topic_id: pending.current.topic, input_text: text, expected_version: version?.id ?? null, expected_config_version: config.version, disclosure_accepted: true } })
    if (current() && data?.topic?.id) { install(data); choose(data.topic.id) }
  }
  async function start(nodeId: string) {
    if (dirty) { setError(unsavedMessage); return }
    if (!item || !version || !config?.version || config.revoked || !accepted) return
    const key = JSON.stringify({ version: version.id, node: nodeId, config: config.version })
    if (pendingStart.current?.key !== key) pendingStart.current = { key, id: crypto.randomUUID() }
    const { data } = await TopicsService.startTopic({ path: { topic_id: item.topic.id }, body: { request_id: pendingStart.current.id, expected_version: version.id, node_id: nodeId, expected_config_version: config.version, disclosure_accepted: true } })
    if (current() && data?.id) location.assign(`/?training_run=${data.id}&jd=${item.topic.id}`)
  }
  function missing(key: EvidenceKey) { const query = new URLSearchParams({ capability: key.capability_id, difficulty: key.difficulty, jd: selected }); return <li key={JSON.stringify(key)}><a className="underline" href={`/?${query}`}>{key.capability_id} · {key.difficulty} · {key.background_id}：补基础或主动检验，再返回原路线</a></li> }
  return <div className="space-y-3">
    <Button className={cls} variant="outline" disabled={busy} onClick={() => void read()}>重新读取 JD 与目的地</Button>
    <label className="block">已有 JD<select aria-label="已有 JD" className="block w-full border p-2" value={selected} disabled={busy} onChange={e => choose(e.target.value)}><option value="">新 JD</option>{items.map(v => <option key={v.topic.id} value={v.topic.id}>{v.current?.role_name ?? "待选择岗位"} · {v.topic.id}</option>)}</select></label>
    <label className="block">招聘原文<textarea aria-label="招聘原文" className="block w-full border p-2" value={text} onChange={e => setText(e.target.value)} /></label>
    <p>不要粘贴秘密或未获授权的公司、个人资料。原文按版本保留；修改不会清空旧题与证据。自动秘密检查不保证零漏报。</p>
    {config?.version && !config.revoked ? <><p className="break-all">接收方：{config.service_url} · {config.model_id}</p><label className="flex items-start gap-2"><input type="checkbox" aria-label="允许发送本次 JD" checked={accepted} onChange={e => setAccepted(e.target.checked)} /><span>分析与核对发送本次 JD 和能力目录；开题仅发送确认的目标、重点、所选要求引用及必要公开来源。各步骤最多六次模型调用，重试可能计费。</span></label></> : <p>请保存可用配置并重读后启动新调用。旧 JD 与成果仍可查看。</p>}
    <Button className={cls} disabled={busy || running || !accepted || !text.trim()} onClick={() => void act(analyze)}>分析 JD（先展示要求，不开题）</Button>
    {error && <p role="alert">{error}</p>}
    {dirty && <p role="status">{unsavedMessage}</p>}
    {item?.topic.jobs.map(job => <div key={job.id}><p role="status">{job.message} · 已记录 {job.attempts} 次调用</p>{["queued", "running", "stopping", "failed", "stopped"].includes(job.status) && <Button className={cls} disabled={busy} onClick={() => void act(async () => { await TopicsService.jobAction({ path: { topic_id: selected, job_id: job.id, action: ["failed", "stopped"].includes(job.status) ? "retry" : "stop" } }); await refresh(selected) })}>{["failed", "stopped"].includes(job.status) ? "主动恢复原分析剩余预算" : "停止 JD 分析"}</Button>}</div>)}
    {item?.documents.map(doc => <section key={doc.document.id} className="space-y-2 border p-3"><details><summary>不可变招聘原文 · {doc.document.id}</summary><p className="whitespace-pre-wrap">{doc.document.text}</p></details><p>{doc.analysis?.message ?? "分析尚未核对完成"}</p>{doc.analysis?.roles?.map((role, index) => <article key={index} className="space-y-2 border p-2"><h3>{role.name}</h3><blockquote>{role.quote.text}</blockquote>{role.requirements.map((requirement, ri) => <div key={ri}><blockquote>{requirement.quote.text}</blockquote><p>{requirement.basis === "inferred" ? "推断" : "JD 明示要求"}：{requirement.explanation}</p><p>{requirement.goal ? `${requirement.goal.target.capability_id} · ${requirement.goal.target.difficulty} · ${requirement.goal.target.background_id}` : "背景或能力映射未知，需要补充"}</p><Evidence value={doc.evidence[index]?.[ri]} /></div>)}<Button className={cls} disabled={busy || running} onClick={() => void act(async () => { const { data } = await JdsService.selectRole({ path: { topic_id: selected }, body: { document_id: doc.document.id, role_index: index, expected_version: version?.id ?? null } }); if (current()) install(data) })}>选择岗位：{role.name}</Button></article>)}</section>)}
    {version && <section aria-label="确认前 JD 路线" className="space-y-3"><h3>所选岗位：{item?.current?.role_name}</h3><p>教学模拟路线，不是该公司真实架构或面试题。未验证不表示不会；模型核对尚不是人工质量认证。</p><p>{item?.topic.active_id === version.id ? "当前版本已确认" : "当前版本尚未确认，新题不会自动开始"}</p>{version.nodes.map((node, index) => { const goal = drafts[node.id]?.goal ?? { target: node.target, text: node.text, focus: node.focus }; return <article key={node.id} className="space-y-2 border p-3"><p>{node.target.capability_id} · {node.target.background_id} · {item?.topic.completed_node_ids.includes(node.id) ? "此节点已正式作答，历史保留" : "此节点尚无完整正式作答"}</p><Evidence value={item?.node_evidence[node.id]} />{(["text", "focus"] as const).map(field => <label key={field} className="block">{field === "text" ? "训练目标" : "训练重点"}<textarea aria-label={field === "text" ? "JD 训练目标" : "JD 训练重点"} className="block w-full border p-2" value={goal[field]} disabled={busy} onChange={e => setDrafts(old => ({ ...old, [node.id]: { topic: selected, goal: { ...goal, [field]: e.target.value } } }))} /></label>)}<label className="block">训练难度<select aria-label="JD 训练难度" className="block w-full border p-2" disabled={busy} value={goal.target.difficulty} onChange={e => setDrafts(old => ({ ...old, [node.id]: { topic: selected, goal: { ...goal, target: { ...goal.target, difficulty: e.target.value as Goal["target"]["difficulty"] } } } }))}>{["基础", "进阶", "综合"].map(value => <option key={value}>{value}</option>)}</select></label><p>修改的是个人训练重点，不改写原文招聘事实。</p><Button className={cls} disabled={busy || running} onClick={() => void act(async () => { await TopicsService.editTopic({ path: { topic_id: selected }, body: { expected_version: version.id, operation: "edit", node_id: node.id, goal } }); await refresh(selected); if (current()) setDrafts(old => { const next = { ...old }; delete next[node.id]; return next }) })}>保存 JD 训练重点为新版本</Button>{index > 0 && <Button className={cls} variant="outline" disabled={busy || running} onClick={() => void act(async () => { const order = version.nodes.map(n => n.id); [order[index - 1], order[index]] = [order[index], order[index - 1]]; await TopicsService.editTopic({ path: { topic_id: selected }, body: { expected_version: version.id, operation: "reorder", order } }); await refresh(selected) })}>上移 JD 节点</Button>}<Button className={cls} disabled={busy || running || dirty || !accepted || item?.topic.active_id !== version.id} onClick={() => void act(() => start(node.id))}>开始此 JD 教学模拟</Button></article> })}{version.nodes.length > 0 && <Button className={cls} disabled={busy || running || dirty || item?.topic.active_id === version.id} onClick={() => void act(async () => { if (dirty) { setError(unsavedMessage); return } await TopicsService.confirmTopic({ path: { topic_id: selected }, body: { expected_version: version.id } }); await refresh(selected) })}>确认当前 JD 路线（不生成题目）</Button>}</section>}
    {Object.entries(drafts).filter(([id, draft]) => draft.topic === selected && !version?.nodes.some(n => n.id === id)).map(([id, draft]) => <div key={id}><p>服务器已换版本；这份本机修改尚未保存：</p><p>{draft.goal.text} · {draft.goal.focus}</p><Button className={cls} variant="outline" onClick={() => setDrafts(old => { const next = { ...old }; delete next[id]; return next })}>明确放弃这份本机修改</Button></div>)}
    {access && <section aria-label="JD 前置缺项"><p>原目标保留，不会自动降级；以下是实际前置缺项。</p><ul>{access.missing_required.map(missing)}</ul>{access.missing_alternatives.map((group, i) => <div key={i}><p>替代组 {i + 1}：本组任选一项，各组分别满足。</p><ul>{group.map(missing)}</ul></div>)}</section>}
    {item && <details><summary>保留的 JD 路线与原轮记录</summary>{item.topic.versions.map(v => <p key={v.id} className="break-all">{v.id} · {v.nodes.map(n => n.text).join(" → ")}</p>)}{item.topic.runs.map(run => <a key={run.id} className="block underline" href={`/?training_run=${run.id}&jd=${selected}`}>{run.goal} · {run.message} · 查看作答、反馈与记录</a>)}</details>}
  </div>
}
