import { useEffect, useState } from "react"
import { ModelconfigService, TrainingService, type ModelConfigPublic, type TaskPublic } from "../client"
import { Button } from "../components/ui/button"

export function Training() {
  const [config, setConfig] = useState<ModelConfigPublic | null>(null)
  const [runs, setRuns] = useState<TaskPublic[]>([])
  const [selected, setSelected] = useState("")
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [refresh, setRefresh] = useState(0)
  const [panel, setPanel] = useState("materials")
  const run = runs.find(item => item.id === selected) ?? runs[0]
  const running = run && ["queued", "running", "stopping"].includes(run.status)
  useEffect(() => {
    let active = true
    void Promise.all([ModelconfigService.readConfig(), TrainingService.latest()]).then(([model, tasks]) => {
      if (!active) return
      setConfig(model.data)
      setRuns(tasks.data)
      setAccepted(false)
      setError("")
    }).catch(() => { if (active) setError("任务读取失败，已有内容保留。请重新读取实际状态。") })
    return () => { active = false }
  }, [refresh])
  useEffect(() => {
    if (!running) return
    let active = true
    const timer = window.setInterval(() => {
      void TrainingService.read({ path: { run_id: run.id } }).then(({ data }) => {
        if (active) setRuns(items => items.map(item => item.id === data.id ? data : item))
      }).catch(() => { if (active) setError("连接中断，后台任务可能仍在继续；请重新读取状态。") })
    }, 1500)
    return () => { active = false; window.clearInterval(timer) }
  }, [run?.id, running])
  async function act(operation: () => Promise<void>) {
    setBusy(true)
    setError("")
    try { await operation() } catch (error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      setError(typeof detail === "string" ? detail : "操作未确认成功；请重新读取状态，不必重复启动。")
    } finally { setBusy(false) }
  }
  const buttonClass = "h-auto min-h-9 max-w-full whitespace-normal"
  return <section aria-labelledby="training-title" className="space-y-4 break-words">
    <h2 id="training-title" className="text-xl font-semibold">随机第一关</h2>
    <p>没有正式作答时，从基础、无前置能力要求的方向选一关。不需要主题卡或入门测验。</p>
    <Button className={buttonClass} variant="outline" disabled={busy} onClick={() => setRefresh(n => n + 1)}>重新读取任务与模型目的地</Button>
    {config ? <>
      <p className="break-all">本次资料接收方：{config.service_url} · {config.model_id}</p>
      <label className="flex items-start gap-2"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} />
        <span>允许把本次目标和必要公开资料发给此模型服务。模型会生成新案例；重试可能计费，评分可靠性未验证。</span>
      </label>
      <Button className={buttonClass} disabled={busy || !accepted || Boolean(running)} onClick={() => act(async () => {
        const { data } = await TrainingService.start({ body: { disclosure_accepted: true, expected_config_version: config.version, previous_run_id: run?.id } })
        setRuns(items => [data, ...items.filter(item => item.id !== data.id)])
        setSelected(data.id)
        setPanel("materials")
      })}>{run ? "换个方向，主动开始新一关" : "帮我选一关"}</Button>
    </> : <p>请在账号与模型区域保存配置，再重新读取目的地。</p>}
    {error && <p role="alert">{error}</p>}
    {runs.length > 1 && <label className="block">查看已有任务<select className="block w-full min-w-0 rounded border p-2" value={run?.id ?? ""} onChange={e => setSelected(e.target.value)}>{runs.map(item => <option key={item.id} value={item.id}>{item.goal} · {item.message}</option>)}</select></label>}
    {run && <article className="space-y-4 rounded border p-3">
      <p role="status">{run.message}</p>
      <p>{run.target.difficulty} · 目标：{run.goal}</p>
      <p className="break-all">本任务目的地：{run.destination} · 模型：{run.model_id}</p>
      {running && <>
        <p>关页后本次任务继续；返回可读取进度。不会自动开始后续训练。</p>
        <Button className={buttonClass} variant="outline" disabled={busy} onClick={() => act(async () => {
          const { data } = await TrainingService.stop({ path: { run_id: run.id } })
          setRuns(items => items.map(item => item.id === data.id ? data : item))
        })}>停止本次生成</Button>
        <p>停止会尝试中断在途请求，不能保证撤销执行或退费。等待服务端确认后才算生效。</p>
      </>}
      <details><summary>调用记录与用量（{run.attempts.length} 次）</summary>
        {run.attempts.map(attempt => <p key={attempt.number}>第 {attempt.number} 次 · {attempt.code} · 输入 {attempt.prompt_tokens ?? "未知"} / 输出 {attempt.completion_tokens ?? "未知"} / 总 token {attempt.total_tokens ?? "未知"}</p>)}
        <p>实际费用请查看模型服务商账单。缺失用量为未知，不表示免费；崩溃前请求可能已计费。</p>
      </details>
      {run.case && <div key={run.id} className="space-y-4">
        <h3 className="text-lg font-semibold">{run.case.title}</h3>
        <p className="whitespace-pre-wrap">{run.case.task}</p>
        <p>{run.case.quality}</p>
        <div className="flex gap-2 md:hidden"><Button variant="outline" onClick={() => setPanel("materials")}>材料</Button><Button variant="outline" onClick={() => setPanel("judgments")}>判断</Button></div>
        <div className="grid gap-4 md:grid-cols-2">
          <section aria-label="案例材料" className={`${panel === "materials" ? "block" : "hidden"} min-w-0 space-y-3 md:block`}>
            <h4 className="font-semibold">材料与假设</h4>
            {run.case.assumptions.map((item, index) => <p key={index}>{item}</p>)}
            {run.case.evidence.map(item => <div key={item.id} className="space-y-2"><p>{item.label}</p><pre className="whitespace-pre-wrap break-all font-sans">{item.text}</pre>{item.citations.map((citation, index) => <blockquote key={index} className="border-l-2 pl-2">{citation.quote}（{citation.source_id}）</blockquote>)}</div>)}
            {run.case.sources.map(source => <details key={source.id}><summary>核对来源：{source.id}</summary><a className="underline break-all" href={source.url} target="_blank" rel="noreferrer">{source.url}</a><p className="break-all">{source.version}</p><p>{source.locator}</p><pre className="whitespace-pre-wrap break-all font-sans">{source.text}</pre></details>)}
          </section>
          <section aria-label="必答判断" className={`${panel === "judgments" ? "block" : "hidden"} min-w-0 space-y-3 md:block`}>
            <h4 className="font-semibold">作判断</h4>
            <p>下方输入仅用于当前页面思考，尚未保存或正式交卷。正式作答与反馈将在后续功能接入。</p>
            {run.case.judgments.map(judgment => <fieldset key={judgment.id} className="space-y-2 border p-2"><legend>{judgment.prompt}</legend>
              {judgment.kind === "choice" && judgment.options.map((option, index) => <label className="flex items-start gap-2" key={index}><input type="radio" name={`${run.id}-${judgment.id}`} value={index} /><span>{option}</span></label>)}
              {judgment.kind === "order" && judgment.options.map((option, index) => <label key={index} className="block">第 {index + 1} 步<select className="block w-full min-w-0 rounded border p-2" defaultValue=""><option value="">请选择顺序</option>{judgment.options.map((item, position) => <option key={position} value={position}>{item}</option>)}</select><span className="sr-only">{option}</span></label>)}
              {judgment.kind === "prediction" && <label className="block">你的预测<textarea className="block w-full rounded border p-2" /></label>}
              <label className="block">这一判断的理由<textarea className="block w-full rounded border p-2" /></label>
            </fieldset>)}
          </section>
        </div>
      </div>}
    </article>}
  </section>
}
