import { useEffect, useRef, useState } from "react"
import { ReviewsService, type ModelConfigPublic, type ReviewPublic } from "../client"
import { Button } from "../components/ui/button"

export function ScoreReview({ runId, config }: { runId: string; config: ModelConfigPublic | null }) {
  const [state, setState] = useState<ReviewPublic | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [accepted, setAccepted] = useState(false)
  const [error, setError] = useState("")
  const requestId = useRef<string>(crypto.randomUUID())
  const mounted = useRef(true)
  const readGeneration = useRef(0)
  const button = "h-auto min-h-9 max-w-full whitespace-normal"
  const active = !!state && ["queued", "running", "stopping"].includes(state.status)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; readGeneration.current++ } }, [])
  useEffect(() => { setAccepted(false) }, [config?.version])
  async function read() {
    const generation = ++readGeneration.current
    try {
      const { data } = await ReviewsService.readReview({ path: { run_id: runId } })
      if (!mounted.current || generation !== readGeneration.current) return
      const current = data?.run_id === runId ? data : null
      setState(current); setLoaded(true); setError("")
      if (current) requestId.current = current.request_id
    } catch {
      if (mounted.current && generation === readGeneration.current) setError("复核记录读取失败；已有结果保留，请重新读取，不会自动重发。")
    }
  }
  useEffect(() => { void read() }, [runId])
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => { void read() }, 1000)
    return () => window.clearInterval(timer)
  }, [active, runId])
  async function act(operation: () => Promise<{ data: ReviewPublic }>) {
    setBusy(true); setError(""); readGeneration.current++
    try {
      const { data } = await operation()
      if (mounted.current && data?.run_id === runId) { readGeneration.current++; setState(data); setLoaded(true); requestId.current = data.request_id }
    } catch (failure) {
      const detail = (failure as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      if (mounted.current) setError(typeof detail === "string" ? detail : "未确认操作结果；请读取已有复核。请求身份保留，重试不会另开一次复核。")
    } finally { if (mounted.current) setBusy(false) }
  }
  const resume = state?.decision === "pending" && ["failed", "stopped"].includes(state.status) && state.remaining_attempts > 0
  return <section aria-label="评分复核" className="space-y-3 min-w-0 border-t pt-3">
    <h4 className="font-semibold">评分复核</h4>
    <p>每次评分可受理一次复核，仅核对冻结原题、原来源、原答及许可的中性澄清。解析后的改答不进入复核；提出异议本身不会改变结论。</p>
    <Button className={button} variant="outline" disabled={busy} onClick={() => void read()}>读取已有复核</Button>
    {!loaded && <p role="status">复核记录尚未读取，不能确认是否已受理。</p>}
    {loaded && (!state || resume) && config && <>
      <p className="break-all">复核接收方：{config.service_url} · {config.model_id}</p>
      <label className="flex items-start gap-2"><input type="checkbox" aria-label="确认评分复核目的地" checked={accepted} onChange={e => setAccepted(e.target.checked)} /><span>允许发送冻结原题、来源、原答及许可澄清、原评分至此模型。每次调用可能计费；恢复沿用同一复核的剩余预算，旧调用的目的地与用量保留。模型语义质量尚未验收。</span></label>
      <Button className={button} disabled={busy || !accepted} onClick={() => void act(() => state ? ReviewsService.retryReview({ path: { run_id: runId }, body: { disclosure_accepted: true, expected_config_version: config.version } }) : ReviewsService.startReview({ path: { run_id: runId }, body: { request_id: requestId.current, disclosure_accepted: true, expected_config_version: config.version } }))}>{state ? "恢复本次复核" : "申请一次评分复核"}</Button>
    </>}
    {loaded && (!state || resume) && !config && <p>配置已删除或尚未保存。历史仍可读；保存并确认模型目的地后才能申请或恢复。</p>}
    {state && <>
      <p role="status">{({ pending: "待复核：本次评分暂不参与能力证明与新的解锁判断，其他练习可继续。", upheld: "复核维持原判", corrected: "原判已更正，已按原作答位置回算当前完整历史", disputed: "复核后仍有争议：本次不作为掌握、失败或连续记录的依据，可另做独立新案例" } as Record<string, string>)[state.decision]}</p>
      <p>{state.message}</p>
      <p>已有开放单元、等级与积分保留。复核不会直接晋升或扣分；更正只补原轮累计应得积分的差额。</p>
      {active && <Button className={button} variant="outline" disabled={busy} onClick={() => void act(() => ReviewsService.stopReview({ path: { run_id: runId } }))}>停止复核（在途费用不保证撤回）</Button>}
      {state.opinion?.explanation && <p className="whitespace-pre-wrap">复核依据：{state.opinion.explanation}</p>}
      {state.opinion?.grading?.items.map(item => <article key={item.judgment_id} className="space-y-2 border p-2">
        <h5>{item.judgment_id}：{({ pass: "通过", evidenced_fail: "有据未通过", unclear: "尚未证明掌握" })[item.conclusion]}</h5>
        <p className="whitespace-pre-wrap">{item.explanation}</p>
        <details><summary>查看复核引用的原答与来源</summary>{item.answer_quotes.map((quote, i) => <blockquote key={i} className="whitespace-pre-wrap">{quote.input === "original" ? "原答" : "许可澄清"}：{quote.quote}</blockquote>)}{item.grounding.map((fact, i) => <blockquote key={i} className="whitespace-pre-wrap">{fact.citation.source_id}：{fact.citation.quote}</blockquote>)}</details>
      </article>)}
      <details><summary>复核调用与用量（{state.attempts.length} 次，剩余最多 {state.remaining_attempts} 次）</summary>{state.attempts.map(attempt => <p key={attempt.number} className="break-all">第 {attempt.number} 次 · {attempt.destination} · {attempt.model_id} · {attempt.code} · 输入 {attempt.prompt_tokens ?? "未知"} / 输出 {attempt.completion_tokens ?? "未知"} / 总 token {attempt.total_tokens ?? "未知"}</p>)}</details>
    </>}
    {error && <p role="alert">{error}</p>}
  </section>
}
