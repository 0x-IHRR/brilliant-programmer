import { useEffect, useRef, useState } from "react"
import { ModelconfigService, TopicsService, type ModelConfigPublic, type TopicPublic, type Node, type Goal } from "../client"
import { Button } from "../components/ui/button"
const cls = "h-auto min-h-9 max-w-full whitespace-normal"

export function FreeTopic() {
  const [opened, setOpened] = useState(() => new URLSearchParams(location.search).has("topic"))
  return <section aria-label="自由主题入口" className="space-y-3 border p-3 break-words"><h2>用自己的话说想练什么</h2><p>先核对系统理解，再由你确认目标并开始。宽泛主题先给起步路线，不自动生成全部题。</p><Button className={cls} variant="outline" onClick={() => setOpened(value => !value)}>{opened ? "收起自由主题" : "输入自由主题或恢复路线"}</Button>{opened && <TopicEditor />}</section>
}

function TopicEditor() {
  const [items, setItems] = useState<TopicPublic[]>([])
  const [selected, setSelected] = useState(() => new URLSearchParams(location.search).get("topic") ?? "")
  const [text, setText] = useState("")
  const [config, setConfig] = useState<ModelConfigPublic | null>(null)
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false), [error, setError] = useState("")
  const alive = useRef(true), owner = useRef(sessionStorage.getItem("token")), generation = useRef(0)
  const pending = useRef<{ key: string; id: string; topic: string } | null>(null)
  const pendingStart = useRef<{ key: string; id: string } | null>(null)
  const current = () => alive.current && owner.current === sessionStorage.getItem("token")
  const topic = items.find(item => item.id === selected)
  const version = topic?.current?.id ? topic.current : null
  function install(value: TopicPublic) { setItems(items => [value, ...items.filter(item => item.id !== value.id)]) }
  async function read() {
    const turn = ++generation.current
    try {
      const [topics, model] = await Promise.all([TopicsService.listTopics(), ModelconfigService.readConfig()])
      if (!current() || turn !== generation.current) return
      setItems(topics.data); setConfig(model.data?.version ? model.data : null); setAccepted(false); setError("")
    } catch { if (current() && turn === generation.current) setError("路线或模型配置读取失败，已有内容与本机输入保留；请重读。") }
  }
  useEffect(() => { alive.current = true; void read(); return () => { alive.current = false; generation.current++ } }, [])
  const running = topic?.jobs.some(job => ["queued", "running", "stopping"].includes(job.status))
  useEffect(() => {
    if (!running || !topic) return
    let active = true
    const timer = window.setInterval(() => {
      void TopicsService.readTopic({ path: { topic_id: topic.id } }).then(({ data }) => { if (active && current()) install(data) }).catch(() => { if (active && current()) setError("连接中断，分析可能仍在继续；本机输入保留，请读取真实状态。") })
    }, 1200)
    return () => { active = false; window.clearInterval(timer) }
  }, [topic?.id, running])
  async function act(operation: () => Promise<void>) {
    if (busy) return
    generation.current++; setBusy(true); setError("")
    try { await operation() } catch (failure) {
      const detail = (failure as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      if (current()) setError(typeof detail === "string" ? detail : "操作未确认成功；输入保留，请重读原记录，不必重复开题。")
    } finally { if (current()) setBusy(false) }
  }
  async function analyze(expand: boolean) {
    if (!text.trim() || !config?.version || !accepted) return
    const key = JSON.stringify({ text, selected, version: version?.id, expand, config: config.version })
    if (pending.current?.key !== key) pending.current = { key, id: crypto.randomUUID(), topic: topic?.id ?? crypto.randomUUID() }
    const { data } = await TopicsService.requestAnalysis({ body: { request_id: pending.current.id, topic_id: pending.current.topic, expected_version: version?.id ?? null, input_text: text, expand, expected_config_version: config.version, disclosure_accepted: true } })
    if (current()) { install(data); setSelected(data.id); const url = new URL(location.href); url.searchParams.set("topic", data.id); history.replaceState(null, "", url) }
  }
  async function start(node: Node) {
    if (!topic || !version || !config?.version || !accepted) return
    const key = JSON.stringify({ version: version.id, node: node.id, config: config.version })
    if (pendingStart.current?.key !== key) pendingStart.current = { key, id: crypto.randomUUID() }
    const { data } = await TopicsService.startTopic({ path: { topic_id: topic.id }, body: { request_id: pendingStart.current.id, expected_version: version.id, node_id: node.id, expected_config_version: config.version, disclosure_accepted: true } })
    if (current() && data?.id) location.assign(`/?training_run=${data.id}&topic=${topic.id}`)
  }
  return <div className="space-y-3">
    <Button className={cls} disabled={busy} variant="outline" onClick={() => void read()}>重新读取路线与模型目的地</Button>
    <label className="block">已有路线<select aria-label="已有路线" className="block w-full border p-2" value={selected} disabled={busy} onChange={e => { setSelected(e.target.value); const url = new URL(location.href); if (e.target.value) url.searchParams.set("topic", e.target.value); else url.searchParams.delete("topic"); history.replaceState(null, "", url) }}><option value="">新主题</option>{items.map(item => <option key={item.id} value={item.id}>{item.current?.input_text ?? item.jobs[0]?.input_text ?? "分析中"}</option>)}</select></label>
    <label className="block">想练什么<textarea aria-label="想练什么" className="block w-full border p-2" value={text} onChange={e => setText(e.target.value)} placeholder="例如：请求超时后，怎样判断能不能重试？" /></label>
    {!text.trim() && <a className="block underline" href="#training-title">还没想好：使用随机练习入口</a>}
    {config?.version && !config.revoked ? <><p className="break-all">接收方：{config.service_url} · {config.model_id}</p><label className="flex items-start gap-2"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} /><span>允许发送主题文本、必要旧路线和目录用于分析与核对；确认开题时发送所选目标、重点与公开来源。分析和出题各最多六次调用，重试可能计费。不要输入秘密。</span></label></> : <p>请保存可用模型配置后重读；旧路线与题目仍可查看。</p>}
    <Button className={cls} disabled={busy || running || !accepted || !text.trim()} onClick={() => void act(() => analyze(false))}>分析主题，先看目标卡</Button>
    {version?.kind === "broad" && <Button className={cls} variant="outline" disabled={busy || running || !accepted || !text.trim()} onClick={() => void act(() => analyze(true))}>按当前输入展开下一段（不生成题目）</Button>}
    {error && <p role="alert">{error}</p>}
    {topic?.jobs.map(job => <div key={job.id}><p role="status">{job.message} · 已记录 {job.attempts} 次调用</p>{["queued", "running", "stopping"].includes(job.status) && <Button className={cls} disabled={busy} onClick={() => void act(async () => { const { data } = await TopicsService.jobAction({ path: { topic_id: topic.id, job_id: job.id, action: "stop" } }); if (current()) install(data) })}>停止本次主题分析</Button>}{["failed", "stopped"].includes(job.status) && <Button className={cls} disabled={busy} onClick={() => void act(async () => { const { data } = await TopicsService.jobAction({ path: { topic_id: topic.id, job_id: job.id, action: "retry" } }); if (current()) install(data) })}>主动重试剩余分析预算</Button>}</div>)}
    {version && <><p>{version.message}</p><p>当前候选版本：{version.id}；{topic?.active_id === version.id ? "已确认，可主动开始所选目标" : "尚未确认；旧确认版本和题目仍保留"}</p>{version.nodes.map((node, index) => <GoalCard key={`${version.id}:${node.id}`} node={node} recommended={version.recommended_id === node.id} completed={Boolean(topic?.completed_node_ids.includes(node.id))} disabled={busy || Boolean(running)} onSave={goal => act(async () => { const { data } = await TopicsService.editTopic({ path: { topic_id: topic!.id }, body: { expected_version: version.id, operation: "edit", node_id: node.id, goal } }); if (current()) install(data) })} onUp={index ? () => act(async () => { const order = version.nodes.map(n => n.id); [order[index-1], order[index]] = [order[index], order[index-1]]; const { data } = await TopicsService.editTopic({ path: { topic_id: topic!.id }, body: { expected_version: version.id, operation: "reorder", order } }); if (current()) install(data) }) : undefined} onStart={() => act(() => start(node))} canStart={topic?.active_id === version.id && accepted && !busy && !running} />)}
      {version.nodes.length > 0 && <Button className={cls} disabled={busy || running || topic?.active_id === version.id} onClick={() => void act(async () => { const { data } = await TopicsService.confirmTopic({ path: { topic_id: topic!.id }, body: { expected_version: version.id } }); if (current()) install(data) })}>确认当前路线版本（不生成题目）</Button>}
    </>}
    {topic && <details><summary>历史路线与已开始的题目</summary>{topic.versions.map(old => <div key={old.id}><p>{old.id}：{old.nodes.map(node => node.text + (topic.completed_node_ids.includes(node.id) ? "（已完成）" : "")).join(" → ")}</p></div>)}{topic.runs.map(run => <a key={run.id} className="block underline" href={`/?training_run=${run.id}&topic=${topic.id}`}>{run.goal} · {run.message} · 查看原轮作答、反馈与保存进度</a>)}<p>路线编辑不改变旧题、正式作答、帮助记录或能力证明；未保存成功的本机输入不保证刷新恢复。</p></details>}
  </div>
}

function GoalCard({ node, recommended, completed, disabled, onSave, onUp, onStart, canStart }: { node: Node; recommended: boolean; completed: boolean; disabled: boolean; onSave: (goal: Goal) => Promise<void>; onUp?: () => Promise<void>; onStart: () => Promise<void>; canStart: boolean }) {
  const [text, setText] = useState(node.text), [focus, setFocus] = useState(node.focus), [difficulty, setDifficulty] = useState(node.target.difficulty)
  const edited = text !== node.text || focus !== node.focus || difficulty !== node.target.difficulty
  return <article className="space-y-2 border p-3"><p>{completed ? "此节点已有完整正式作答，原轮记录保留" : "此节点尚无完整正式作答记录"}</p><h3>{recommended ? "推荐首目标" : "路线目标"} · {node.target.capability_id}</h3><label className="block">目标<textarea aria-label="目标" disabled={disabled} className="block w-full border p-2" value={text} onChange={e => setText(e.target.value)} /></label><label className="block">重点<textarea aria-label="重点" disabled={disabled} className="block w-full border p-2" value={focus} onChange={e => setFocus(e.target.value)} /></label><label className="block">难度<select aria-label="目标难度" disabled={disabled} className="block w-full border p-2" value={difficulty} onChange={e => setDifficulty(e.target.value as typeof difficulty)}>{["基础", "进阶", "综合"].map(value => <option key={value}>{value}</option>)}</select></label><p>技术背景：{node.target.background_id}。文字修改不授证、不绕过真实前置；改变技术方向可重新分析。</p><Button className={cls} disabled={disabled || !edited || !text.trim() || !focus.trim()} onClick={() => void onSave({ text, focus, target: { ...node.target, difficulty } })}>保存为新候选版本</Button>{onUp && <Button className={cls} variant="outline" disabled={disabled || edited} onClick={() => void onUp()}>上移此节点</Button>}<Button className={cls} disabled={!canStart || edited} onClick={() => void onStart()}>开始这个目标（生成一题）</Button>{edited && <p>本机修改尚未保存，不能用旧卡片开题。</p>}</article>
}
