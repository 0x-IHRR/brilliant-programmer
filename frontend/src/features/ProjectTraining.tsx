import { useEffect, useRef, useState } from "react"
import { ProjecttrainingService, TopicsService, type Goal, type ModelConfigPublic, type ProjectTrainingPublic, type UnitAccess, type EvidenceKey, type Repository } from "../client"
import { Button } from "../components/ui/button"

const draftKey = (topic: string, node: string) => `${topic}:${node}`
const cls = "h-auto min-h-9 max-w-full whitespace-normal"
export function ProjectTraining({ projectRunId, repository, config }: { projectRunId: string; repository?: Repository; config: ModelConfigPublic | null }) {
  const [routes, setRoutes] = useState<ProjectTrainingPublic[]>([])
  const [selected, setSelected] = useState(() => new URLSearchParams(location.search).get("project_route") ?? "")
  const [drafts, setDrafts] = useState<Record<string, { topic: string; node: string; goal: Goal }>>({})
  const [accepted, setAccepted] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("")
  const [access, setAccess] = useState<UnitAccess | null>(null)
  const alive = useRef(true), owner = useRef(sessionStorage.getItem("token")), serial = useRef(0)
  const projectIdentity = useRef({ id: projectRunId })
  if (projectIdentity.current.id !== projectRunId) projectIdentity.current = { id: projectRunId }
  const projectGeneration = projectIdentity.current
  const pending = useRef<{ key: string; id: string; topic: string } | null>(null)
  const pendingStart = useRef<{ key: string; id: string } | null>(null)
  const relevant = routes.filter(r => r.project_run_id === projectRunId || (repository && r.source_repository &&
    r.source_repository.owner.toLowerCase() === repository.owner.toLowerCase() && r.source_repository.name.toLowerCase() === repository.name.toLowerCase() &&
    r.source_repository.focus === repository.focus && r.source_repository.start_line === repository.start_line && r.source_repository.end_line === repository.end_line))
  const item = relevant.find(r => r.topic.id === selected) ?? relevant[0]
  const activeRoute = item?.active?.route?.id ? item.active : null
  const version = item?.current?.route
  const running = item?.topic.jobs.some(j => ["queued", "running", "stopping"].includes(j.status))
  const current = () => alive.current && projectIdentity.current === projectGeneration && owner.current === sessionStorage.getItem("token")
  const dirty = Object.values(drafts).some(value => {
    if (value.topic !== item?.topic.id) return false
    const node = version?.nodes.find(n => n.id === value.node)
    return !node || JSON.stringify(value.goal) !== JSON.stringify({ target: node.target, text: node.text, focus: node.focus })
  })
  const unsaved = "本机修改尚未保存；先保存并确认新版本再开题，冲突输入保留。"
  function install(value: ProjectTrainingPublic) { setRoutes(old => [value, ...old.filter(r => r.topic.id !== value.topic.id)]) }
  async function read() {
    const turn = ++serial.current
    try { const { data } = await ProjecttrainingService.listRoutes(); if (current() && turn === serial.current) { setRoutes(data); setError("") } }
    catch { if (current() && turn === serial.current) setError("路线暂未读取，已有成果和本机输入保留；请重读。") }
  }
  useEffect(() => { alive.current = true; setBusy(false); setError(""); setAccess(null); void read(); return () => { alive.current = false; serial.current++ } }, [projectRunId])
  useEffect(() => { setAccepted(false) }, [config?.version, projectRunId])
  useEffect(() => {
    if (!running || !item) return
    let active = true
    const id = item.topic.id
    const timer = setInterval(() => { const turn = serial.current; void ProjecttrainingService.readRoute({ path: { topic_id: id } }).then(({ data }) => { if (active && current() && turn === serial.current) install(data) }).catch(() => { if (active && current()) setError("连接中断，任务可能仍在继续；重读同一记录，未保存输入保留。") }) }, 1200)
    return () => { active = false; clearInterval(timer) }
  }, [item?.topic.id, running])
  async function refresh(id: string) { const { data } = await ProjecttrainingService.readRoute({ path: { topic_id: id } }); if (current()) install(data) }
  async function act(operation: () => Promise<void>) {
    if (busy) return
    serial.current++; setBusy(true); setError(""); setAccess(null)
    try { await operation() } catch (e) {
      if (current()) {
        const detail = (e as { response?: { data?: { detail?: string | { message?: string; access?: UnitAccess } } } }).response?.data?.detail
        setError(typeof detail === "string" ? detail : detail?.message ?? "操作未确认成功；本机输入保留，请读取状态再恢复同一请求。")
        if (typeof detail === "object" && detail?.access) setAccess(detail.access)
      }
    } finally { if (current()) setBusy(false) }
  }
  async function analyze() {
    if (!config?.version || config.revoked || !accepted || dirty) return
    const updatedSource = !!item && item.project_run_id !== projectRunId
    const previous = updatedSource ? activeRoute?.route.id ?? null : null
    const expected = updatedSource ? null : version?.id ?? null
    const key = JSON.stringify([projectRunId, item?.topic.id, expected, previous, config.version])
    const stoppedRequest = item?.topic.jobs.some(j => j.id === pending.current?.id && ["stopped", "failed"].includes(j.status))
    if (pending.current?.key !== key || stoppedRequest) pending.current = { key, id: crypto.randomUUID(), topic: updatedSource ? crypto.randomUUID() : item?.topic.id ?? crypto.randomUUID() }
    const request = pending.current
    const { data } = await ProjecttrainingService.analyzeRoute({ body: { request_id: request.id, topic_id: request.topic, project_run_id: projectRunId, expected_version: expected, previous_version_id: previous, expected_active_version: activeRoute?.route.id ?? null, expected_config_version: config.version, disclosure_accepted: true } })
    if (current()) { install(data); setSelected(data.topic.id) }
  }
  async function start(nodeId: string, active = false) {
    if (dirty) { setError(unsaved); return }
    if (!item || !config?.version || config.revoked || !accepted) return
    const selectedVersion = active ? activeRoute?.route : version
    const selectedTopic = active ? item.active_topic_id : item.topic.id
    const selectedProject = active ? activeRoute?.project_run_id : item.project_run_id
    if (!selectedVersion || !selectedTopic || !selectedProject) return
    const key = JSON.stringify([selectedVersion.id, nodeId, config.version])
    if (pendingStart.current?.key !== key) pendingStart.current = { key, id: crypto.randomUUID() }
    const { data } = await TopicsService.startTopic({ path: { topic_id: selectedTopic }, body: { request_id: pendingStart.current.id, expected_version: selectedVersion.id, node_id: nodeId, expected_config_version: config.version, disclosure_accepted: true } })
    if (current()) location.assign(`/?training_run=${data.id}&project_route=${selectedTopic}&project_run=${selectedProject}`)
  }
  function prerequisite(key: EvidenceKey) { return <li key={JSON.stringify(key)}><a className="underline" href={`/?capability=${encodeURIComponent(key.capability_id)}&difficulty=${encodeURIComponent(key.difficulty)}&project_run=${encodeURIComponent(projectRunId)}&project_route=${encodeURIComponent(item?.topic.id ?? "")}`}>{key.capability_id} · {key.difficulty} · {key.background_id}：查看真实前置与补练</a></li> }
  return <section aria-label="项目模块学习路线" className="space-y-3 border p-3 break-words">
    <h3>从已读模块进入练习</h3><p>模块顺序是建议，真实能力前置决定新解锁。源码只能证明文本；运行行为仍需证据，推演与日志会标明教学模拟。</p>
    <Button className={cls} variant="outline" disabled={busy} onClick={() => void read()}>重新读取项目路线</Button>
    {relevant.length > 1 && <label className="block">已有路线<select className="block w-full min-w-0 max-w-full" value={item?.topic.id ?? ""} disabled={busy} onChange={e => setSelected(e.target.value)}>{relevant.map(r => <option key={r.topic.id} value={r.topic.id}>{r.current?.repository.commit ?? r.topic.id}</option>)}</select></label>}
    {config?.version && !config.revoked ? <><p className="break-all">模型接收方：{config.service_url} · {config.model_id}</p><label className="flex items-start gap-2"><input type="checkbox" aria-label="允许发送项目模块片段" checked={accepted} onChange={e => setAccepted(e.target.checked)} /><span>路线分析与核对发送已读模块片段和能力目录；开题只发送所选目标、模块与冻结必要来源。每项任务最多六次模型调用，重试可能计费。停止后须主动新建分析；仅复用已保存的固定片段，路线生成与核对可能再次调用，不恢复已停任务。</span></label></> : <p>旧路线和题目可继续查看；新调用需要保存可用配置。</p>}
    <Button className={cls} disabled={busy || running || dirty || !accepted} onClick={() => void act(analyze)}>分析模块学习路线（不开题）</Button>
    {error && <p role="alert">{error}</p>}{dirty && <p role="status">{unsaved}</p>}
    {item?.topic.jobs.map(job => <div key={job.id}><p role="status">{job.message} · 已记录 {job.attempts} 次调用</p>{["queued", "running", "stopping", "failed"].includes(job.status) && <Button className={cls} disabled={busy} onClick={() => void act(async () => { await TopicsService.jobAction({ path: { topic_id: item.topic.id, job_id: job.id, action: ["failed", "stopped"].includes(job.status) ? "retry" : "stop" } }); await refresh(item.topic.id) })}>{["failed", "stopped"].includes(job.status) ? "恢复原路线分析剩余预算" : "停止路线分析"}</Button>}</div>)}
    {activeRoute && activeRoute.route.id !== version?.id && <section aria-label="仍生效的已确认项目路线" className="space-y-2 border p-3">
      <h4>仍生效的已确认路线</h4><p className="break-all">{activeRoute.repository.commit} · 新候选尚未替换这条路线</p>
      {activeRoute.route.nodes.map(node => <div key={node.id}><p>{node.text} · {node.focus}</p><Button className={cls} disabled={busy || dirty || !accepted || !config?.version} onClick={() => void act(() => start(node.id, true))}>继续已确认模块：{node.text}</Button></div>)}
    </section>}
    {item?.current && <><p className="break-all">固定版本：{item.current.repository.owner}/{item.current.repository.name}@{item.current.repository.commit}</p><p>{version?.message}</p><p>{activeRoute?.route.id === version?.id ? "当前已确认路线" : "待确认候选；旧已确认路线与题目保留"}</p><details><summary>本次范围与缺项</summary>{item.current.map_missing.map((m, i) => <p key={i}>{m}</p>)}</details></>}
    {version?.nodes.map((node, index) => {
      const key = draftKey(item!.topic.id, node.id)
      const value = drafts[key]?.goal ?? { target: node.target, text: node.text, focus: node.focus }
      const binding = item?.current?.bindings.find(b => b.node_id === node.id)
      return <article key={node.id} className="space-y-2 border p-3"><h4>{binding?.proposal.module_path}</h4><p>{node.target.capability_id} · {node.target.difficulty} · {node.target.background_id}</p><p>{item?.topic.completed_node_ids.includes(node.id) ? "此节点已有正式作答，历史保留" : "此节点尚无完整正式作答；不表示不会"}</p>
        {(["text", "focus"] as const).map(field => <label key={field} className="block">{field === "text" ? "模块训练目标" : "模块训练重点"}<textarea className="block w-full border p-2" aria-label={field === "text" ? "模块训练目标" : "模块训练重点"} disabled={busy} value={value[field]} onChange={e => setDrafts(old => ({ ...old, [key]: { topic: item!.topic.id, node: node.id, goal: { ...value, [field]: e.target.value } } }))} /></label>)}
        <details><summary>冻结源码定位与必要片段</summary>{binding?.references.map(r => <div key={r.source.id}><a className="underline break-all" href={r.source.url} target="_blank" rel="noreferrer">{r.source.locator}</a><pre className="whitespace-pre-wrap break-all">{r.source.text}</pre></div>)}</details>
        {binding?.proposal.missing?.map(m => <p key={m}>缺失材料：{m}</p>)}
        <Button className={cls} disabled={busy || running} onClick={() => void act(async () => { await TopicsService.editTopic({ path: { topic_id: item!.topic.id }, body: { expected_version: version.id, operation: "edit", node_id: node.id, goal: value } }); await refresh(item!.topic.id); if (current()) setDrafts(old => { const next = { ...old }; delete next[key]; return next }) })}>保存模块目标为新版本</Button>
        {index > 0 && <Button className={cls} variant="outline" disabled={busy || running} onClick={() => void act(async () => { const order = version.nodes.map(n => n.id); [order[index - 1], order[index]] = [order[index], order[index - 1]]; await TopicsService.editTopic({ path: { topic_id: item!.topic.id }, body: { expected_version: version.id, operation: "reorder", order } }); await refresh(item!.topic.id) })}>上移模块建议</Button>}
        <Button className={cls} disabled={busy || running || dirty || !accepted || item?.topic.active_id !== version.id || !!binding?.proposal.missing?.length || !binding?.references.length} onClick={() => void act(() => start(node.id))}>开始模块教学练习</Button>
      </article>
    })}
    {version && version.nodes.length > 0 && <Button className={cls} disabled={busy || running || dirty || item?.topic.active_id === version.id} onClick={() => void act(async () => { if (dirty) { setError(unsaved); return } await TopicsService.confirmTopic({ path: { topic_id: item!.topic.id }, body: { expected_version: version.id, expected_active_version: activeRoute?.route.id ?? null } }); await refresh(item!.topic.id) })}>确认模块路线（不生成题目）</Button>}
    {Object.entries(drafts).filter(([, d]) => d.topic === item?.topic.id && !version?.nodes.some(n => n.id === d.node)).map(([id, d]) => <div key={id}><p>服务器已换版本，本机未保存修改：{d.goal.text} · {d.goal.focus}</p><Button className={cls} variant="outline" onClick={() => setDrafts(old => { const next = { ...old }; delete next[id]; return next })}>明确放弃这份模块修改</Button></div>)}
    {access && <section aria-label="项目实际前置缺项"><p>目标保留，不自动降级。</p><ul>{access.missing_required.map(prerequisite)}</ul>{access.missing_alternatives.map((group, i) => <div key={i}><p>替代组 {i + 1} 任选一项，各组分别满足</p><ul>{group.map(prerequisite)}</ul></div>)}</section>}
    {item && <details><summary>项目路线与原轮记录</summary>{item.topic.versions.map(v => <p key={v.id}>{v.id} · {v.nodes.map(n => n.text).join(" → ")}</p>)}{item.topic.runs.map(r => <a key={r.id} className="block underline" href={`/?training_run=${r.id}&project_route=${r.project_simulation?.topic_id ?? item.topic.id}&project_run=${r.project_simulation?.project_run_id ?? projectRunId}`}>{r.goal} · {r.message} · 查看作答与反馈</a>)}</details>}
  </section>
}
