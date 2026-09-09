import { useEffect, useState } from "react"
import { ModelconfigService, ProjectsService, type Finding, type ModelConfigPublic, type ProjectPublic } from "../client"
import { Button } from "../components/ui/button"
import { ProjectTraining } from "./ProjectTraining"
import { Input } from "../components/ui/input"

const activeStatuses = ["queued", "running", "stopping"]
const labels = { module: "模块", entry: "入口", call: "调用", state: "状态", storage: "存储" }

export function Project() {
  const [config, setConfig] = useState<ModelConfigPublic | null>(null)
  const [runs, setRuns] = useState<ProjectPublic[]>([])
  const [selected, setSelected] = useState(() => new URLSearchParams(location.search).get("project_run") ?? "")
  const [url, setUrl] = useState("")
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [refresh, setRefresh] = useState(0)
  const run = runs.find(item => item.id === selected) ?? runs[0]
  const running = runs.some(item => activeStatuses.includes(item.status))
  const snapshot = run?.snapshot
  const repository = snapshot?.repository
  const entries = snapshot?.entries ?? []
  const fragments = snapshot?.fragments ?? []
  const excluded = snapshot?.excluded ?? {}
  const buttonClass = "h-auto min-h-9 max-w-full whitespace-normal"
  useEffect(() => {
    let active = true
    void Promise.all([ModelconfigService.readConfig(), ProjectsService.latestProjects()]).then(([model, tasks]) => {
      if (!active) return
      setConfig(model.data?.version ? model.data : null)
      setRuns(tasks.data)
      setAccepted(false)
      setError("")
      const requested = new URLSearchParams(location.search).get("project_run")
      if (requested && !tasks.data.some(t => t.id === requested)) void ProjectsService.readProject({ path: { run_id: requested } }).then(({ data }) => { if (active) { setRuns(old => [data, ...old.filter(r => r.id !== data.id)]); setSelected(data.id) } }).catch(() => { if (active) { setSelected(""); setError("原项目记录暂不可读取；已保留可用项目列表，请核对返回链接后重读。") } })
    }).catch(() => { if (active) setError("项目读取失败，已展示成果保留；请重新读取实际状态。") })
    return () => { active = false }
  }, [refresh])
  useEffect(() => {
    if (!running) return
    let active = true
    const timer = window.setInterval(() => {
      void ProjectsService.latestProjects().then(({ data }) => {
        if (active) setRuns(data)
      }).catch(() => { if (active) setError("连接中断，后台分析可能仍在继续；重新读取不会重新启动分析。") })
    }, 1500)
    return () => { active = false; window.clearInterval(timer) }
  }, [running])
  async function act(operation: () => Promise<ProjectPublic>) {
    setBusy(true)
    setError("")
    try {
      const data = await operation()
      setRuns(items => [data, ...items.filter(item => item.id !== data.id)])
      setSelected(data.id)
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      setError(typeof detail === "string" ? detail : "操作结果未确认，输入与已有成果保留；请重新读取状态。")
    } finally { setBusy(false) }
  }
  async function start(sourceUrl: string, reanalyze: boolean) {
    if (!config) return
    await act(async () => (await ProjectsService.startProject({ body: { url: sourceUrl, disclosure_accepted: accepted, expected_config_version: config.version, reanalyze } })).data)
  }
  function sourceLink(path: string, first: number, last: number) {
    if (!repository) return undefined
    return `https://github.com/${encodeURIComponent(repository.owner)}/${encodeURIComponent(repository.name)}/blob/${repository.commit}/${path.split("/").map(encodeURIComponent).join("/")}#L${first}-L${last}`
  }
  function findingList(findings: Finding[]) {
    return findings.map((finding, index) => <details key={`${finding.kind}:${index}`} className="rounded border p-2">
      <summary>{labels[finding.kind]} · {finding.subject} → {finding.target}</summary>
      <p>{finding.relation}</p>
      {finding.evidence.map((location, number) => <div key={`${location.path}:${location.start}:${number}`} className="space-y-1">
        <a className="underline break-all" href={sourceLink(location.path, location.start, location.end)} target="_blank" rel="noreferrer">{location.path} · 行 {location.start}–{location.end}</a>
        <pre className="whitespace-pre-wrap break-all font-sans">{location.quote}</pre>
      </div>)}
    </details>)
  }
  const fixedUrl = repository && `https://github.com/${encodeURIComponent(repository.owner)}/${encodeURIComponent(repository.name)}/${repository.focus && entries.find(entry => entry.path === repository.focus)?.kind !== "tree" ? "blob" : "tree"}/${repository.commit}${repository.focus ? `/${repository.focus.split("/").map(encodeURIComponent).join("/")}` : ""}${repository.end_line ? `#L${repository.start_line}-L${repository.end_line}` : ""}`
  return <section aria-labelledby="project-title" className="space-y-4 break-words">
    <h2 id="project-title" className="text-xl font-semibold">公开 GitHub 项目地图</h2>
    <p>支持仓库、.git、分支、commit 和文件链接。固定本次版本，分批只读；不执行代码或安装项目依赖。</p>
    <label className="block space-y-1">公开 GitHub HTTPS 链接<Input type="url" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://github.com/owner/repository" /></label>
    <Button className={buttonClass} variant="outline" disabled={busy} onClick={() => setRefresh(n => n + 1)}>重新读取项目与模型目的地</Button>
    {config ? <>
      <p className="break-all">本次资料接收方：{config.service_url} · {config.model_id}</p>
      <label className="flex items-start gap-2"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} /><span>允许将当前公开源码必要片段及上下文发给已保存的模型服务，重试可能计费。不要输入未授权或含秘密的资料；自动秘密检测可能漏报，模型语义质量未验收。</span></label>
      <Button className={buttonClass} disabled={busy || running || !accepted || !url.trim()} onClick={() => start(url, false)}>按链接读取或主动更新版本</Button>
    </> : <p>请先保存模型配置，再重新读取目的地；已有项目仍可查看。</p>}
    {error && <p role="alert">{error}</p>}
    {runs.length > 1 && <label className="block">查看已有项目任务<select className="block w-full min-w-0 rounded border p-2" value={run?.id ?? ""} onChange={e => setSelected(e.target.value)}>{runs.map(item => <option key={item.id} value={item.id}>{item.url} · {item.message}</option>)}</select></label>}
    {run && <article className="space-y-4 rounded border p-3">
      <p role="status">{run.message}</p>
      <p className="break-all">任务来源：{run.url}</p>
      <p className="break-all">本任务模型目的地：{run.destination} · {run.model_id}</p>
      {activeStatuses.includes(run.status) && <>
        <p>关页后仅继续本次分析，返回显示进度或成果；不会自动启动训练或追踪新版本。</p>
        <Button className={buttonClass} variant="outline" disabled={busy} onClick={() => act(async () => (await ProjectsService.stopProject({ path: { run_id: run.id } })).data)}>停止分析</Button>
        <p>服务端确认后阻止新请求，并尝试中断在途请求；不能保证撤销执行或退费。</p>
      </>}
      {run.status === "failed" && <Button className={buttonClass} variant="outline" disabled={busy || running} onClick={() => act(async () => (await ProjectsService.retryProject({ path: { run_id: run.id } })).data)}>重试同一任务（预算不重置）</Button>}
      {!activeStatuses.includes(run.status) && config && <Button className={buttonClass} variant="outline" disabled={busy || running || !accepted} onClick={() => start(fixedUrl || run.url, true)}>主动重分析当前固定版本（可能计费）</Button>}
      {run.reused_from_id && <p>本版本复用了已有分析，本次没有模型调用；需要补读时请主动重分析。</p>}
      <details><summary>模型调用与用量（{run.attempts.length} 次）</summary>{run.attempts.map(attempt => <p key={attempt.number}>第 {attempt.number} 次 · {attempt.code} · 输入 {attempt.prompt_tokens ?? "未知"} / 输出 {attempt.completion_tokens ?? "未知"} / 总 token {attempt.total_tokens ?? "未知"}</p>)}<p>缺失用量不是零或免费；费用以供应商账单为准。</p></details>
      {repository && snapshot && <>
        <p className="break-all">固定 commit：{repository.commit} · ref：{repository.ref}</p>
        <p>已列 {entries.length} 个目录项、保留 {fragments.length} 个片段；GitHub 请求 {snapshot.requests} 次、响应 {snapshot.bytes} 字节。不是整库分析完成。</p>
        <details><summary>目录与未读范围</summary><p>{snapshot.listing_complete ? "本次目录枚举已结束；文件和语义仍可能未核实。" : "仍有目录未读取，不代表完整目录。"}</p>{entries.map(entry => <p key={entry.path} className="break-all">{entry.path} · {excluded[entry.path] ?? (fragments.some(fragment => fragment.path === entry.path) ? "已读部分片段，其他范围未核实" : "未读／未核实")}</p>)}</details>
        <details><summary>固定版本来源片段</summary>{fragments.map(fragment => <details key={`${fragment.path}:${fragment.start}`}><summary>{fragment.path} · 行 {fragment.start}–{fragment.end} / 共 {fragment.total_lines} 行</summary><a className="underline" href={sourceLink(fragment.path, fragment.start, fragment.end)} target="_blank" rel="noreferrer">核对 GitHub 固定行范围</a><pre className="whitespace-pre-wrap break-all font-sans">{fragment.text}</pre></details>)}</details>
      </>}
      {!run.snapshot && ["failed", "stopped"].includes(run.status) && <p>本次来源未能继续读取。已有固定题目、原答与来源不会被删除；可从已有项目任务返回保留快照复盘。上游不可读不等于用户永久删除。</p>}
      {run.project_map && <div className="grid gap-4 md:grid-cols-2">
        <section aria-label="已确认源码事实" className="min-w-0 space-y-2"><h3 className="font-semibold">已确认源码事实</h3><p>仅确认已读语法和清单声明，实际运行时关系仍需验证。</p>{findingList(run.project_map.confirmed ?? [])}</section>
        <section aria-label="未核实候选与缺失材料" className="min-w-0 space-y-2"><h3 className="font-semibold">未核实候选与缺失材料</h3><p>模型关系即使引用合法，也不等于结论已被证实。</p>{findingList(run.project_map.unverified ?? [])}{(run.project_map.missing ?? []).map((missing, index) => <p key={index}>{missing}</p>)}</section>
      </div>}
    </article>}
    {run?.project_map && <ProjectTraining projectRunId={run.id} repository={repository ?? undefined} config={config} />}
  </section>
}
