import { useEffect, useState } from "react"
import { EvaluationsService, type Answer, type EvaluationPublic, type ModelConfigPublic, type PublicCase } from "../client"
import { ScoreReview } from "./ScoreReview"
import { Button } from "../components/ui/button"

export function Evaluation({ runId, caseData, config, submitted, onFrozen, boss = false }: { boss?: boolean; runId: string; caseData: PublicCase; config: ModelConfigPublic | null; submitted: boolean; onFrozen: (frozen: boolean) => void }) {
  const [state, setState] = useState<EvaluationPublic | null>(null)
  const [answers, setAnswers] = useState<Answer[]>([])
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const buttonClass = "h-auto min-h-9 max-w-full whitespace-normal"
  const inputClass = "block w-full min-w-0 rounded border p-2 focus-visible:outline-2"
  const checking = state && ["checking", "stopping"].includes(state.status)
  useEffect(() => { onFrozen(state?.frozen_sequence != null) }, [state?.frozen_sequence, onFrozen])
  useEffect(() => { setAccepted(false) }, [config?.version])
  useEffect(() => {
    if (!submitted) return
    let active = true
    void EvaluationsService.readEvaluation({ path: { run_id: runId } }).then(({ data: received }) => {
      const data = received?.run_id ? received : null
      if (active) { setState(data); if (data) setAnswers(data.inputs.original.answers) }
    }).catch(() => { if (active) setError("评分记录读取失败，请重新读取；不会自动重新调用。") })
    return () => { active = false }
  }, [runId, submitted])
  useEffect(() => {
    if (!checking) return
    let active = true
    const timer = window.setInterval(() => {
      void EvaluationsService.readEvaluation({ path: { run_id: runId } }).then(({ data: received }) => {
      const data = received?.run_id ? received : null
        if (active) { setState(data); if (data?.status === "needs_clarification") setAnswers(data.inputs.original.answers) }
      }).catch(() => { if (active) setError("评分连接中断，原答仍保留；请重读实际结果。") })
    }, 1000)
    return () => { active = false; window.clearInterval(timer) }
  }, [runId, checking])
  async function act(operation: () => Promise<{ data: EvaluationPublic | null }>) {
    setBusy(true); setError("")
    try { const { data: received } = await operation(); const data = received?.run_id ? received : null; setState(data); if (data?.status === "needs_clarification") setAnswers(data.inputs.original.answers) }
    catch (error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      setError(typeof detail === "string" ? detail : "未确认评分操作成功，请读取已有状态。")
    } finally { setBusy(false) }
  }
  function edit(id: string, update: Partial<Answer>) { setAnswers(items => items.map(a => a.judgment_id === id ? { ...a, ...update } : a)) }
  if (!submitted) return null
  return <section aria-label="本次反馈" className="space-y-3 min-w-0 border-t pt-3">
    <h4 className="font-semibold">本次反馈</h4>
    <p>{boss ? "完整作答与晋升分开；已获得的10点不因答错或评分失败追回，晋升另核对本轮全部必考项与独立资格。" : "结论与普通完成分开；已获得的 10 点不因答错或评分失败追回，不直接更新等级或独立证明。"}</p>
    <Button className={buttonClass} variant="outline" disabled={busy} onClick={() => act(() => EvaluationsService.readEvaluation({ path: { run_id: runId } }))}>重新读取评分</Button>
    {!state && config && <>
      <p className="break-all">评分接收方：{config.service_url} · {config.model_id}</p>
      <label className="flex items-start gap-2"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} /><span>允许把当前冻结题、来源、原答与一次许可补答发送给此模型逐项评分；重试可能计费，语义质量尚未验收。</span></label>
      <Button className={buttonClass} disabled={busy || !accepted} onClick={() => act(() => EvaluationsService.startEvaluation({ path: { run_id: runId }, body: { disclosure_accepted: true, expected_config_version: config.version } }))}>核对本次作答</Button>
    </>}
    {error && <p role="alert">{error}</p>}
    {state && <>
      <p role="status">{state.message}</p>
      {state.independent_outcome && <p role="status">原评分独立检验记录（复核当前结果见下方）：{({ independent_pass_candidate: boss ? "符合独立通过条件的证据候选（模型语义质量未验证；等级请核对本轮Boss结算）" : "符合独立通过条件的证据候选（模型语义质量未验证，不直接更新等级）", pending_delivery: "帮助交付尚未核实，独立结算等待回执；可核实说明或主动另开新题", practice: "按练习记录，已有修为保留", unclear: "尚未证明掌握", evidenced_fail: "本次独立作答有据未通过", invalid_case: "案例无效，不记能力失败", system_failure: "系统未能完成，不记能力失败", no_qualified_case: "当前案例未通过陌生性核验" } as Record<string, string>)[state.independent_outcome] ?? state.independent_outcome}</p>}
      <p className="break-all">本评估接收方：{state.destination} · {state.model_id}</p>
      {state.frozen_sequence !== null && <p>评估输入已冻结 · 服务端事件 {state.frozen_sequence}。此后查看反馈不会改写原答。</p>}
      {checking && <Button className={buttonClass} variant="outline" disabled={busy} onClick={() => act(() => EvaluationsService.stopEvaluation({ path: { run_id: runId } }))}>停止本次评分</Button>}
      {state.can_retry && <Button className={buttonClass} disabled={busy} onClick={() => act(() => EvaluationsService.retryEvaluation({ path: { run_id: runId } }))}>继续原评分（预算不重置）</Button>}
      {state.status === "needs_clarification" && <form className="space-y-3" onSubmit={e => { e.preventDefault(); void act(() => EvaluationsService.clarifyEvaluation({ path: { run_id: runId }, body: { answers } })) }}>
        {caseData.judgments.map(j => { const answer = answers.find(a => a.judgment_id === j.id); return answer && <fieldset key={j.id} disabled={busy} className="space-y-2 min-w-0"><legend>{j.prompt}</legend>
          {j.kind === "choice" && j.options.map((o, i) => <label key={i} className="flex gap-2"><input type="radio" name={`clarify-${runId}-${j.id}`} checked={answer.value === i} onChange={() => edit(j.id, { value: i })} />{o}</label>)}
          {j.kind === "order" && j.options.map((_, step) => <label key={step}>第 {step + 1} 步<select className={inputClass} value={(answer.value as number[])[step]} onChange={e => edit(j.id, { value: (answer.value as number[]).map((v, i) => i === step ? Number(e.target.value) : v) })}>{j.options.map((o, i) => <option key={i} value={i}>{o}</option>)}</select></label>)}
          {j.kind === "prediction" && <label>补充预测<textarea required className={inputClass} maxLength={6000} value={String(answer.value)} onChange={e => edit(j.id, { value: e.target.value })} /></label>}
          <label>补充原答的意思和依据<textarea required className={inputClass} maxLength={6000} value={answer.reason} onChange={e => edit(j.id, { reason: e.target.value })} /></label>
        </fieldset> })}
        <Button type="submit" className={buttonClass} disabled={busy}>提交一次中性补答并冻结</Button>
        <Button type="button" variant="outline" className={buttonClass} disabled={busy} onClick={() => act(() => EvaluationsService.clarifyEvaluation({ path: { run_id: runId }, body: { answers: null } }))}>结束澄清，保留尚未证明掌握</Button>
      </form>}
      {state.frozen_sequence != null && <p>以下为原评分记录；已申请复核时，当前有效结论请看下方评分复核与能力地图。</p>}
      {state.result?.items.map(item => <article key={item.judgment_id} className="space-y-2 border p-2">
        <h5>{caseData.judgments.find(j => j.id === item.judgment_id)?.prompt}</h5>
        <p>{({ pass: "通过", evidenced_fail: "有据未通过", unclear: "尚未证明掌握" })[item.conclusion]}</p>
        <p className="whitespace-pre-wrap">依据：{item.explanation}</p>
        {item.gap && <p className="whitespace-pre-wrap">缺口：{item.gap}</p>}
        <details><summary>核对原答与冻结证据</summary>{item.answer_quotes.map((q, i) => <blockquote key={i} className="whitespace-pre-wrap">{q.input === "original" ? "原答" : "许可补答"}：{q.quote}</blockquote>)}{item.grounding.map((g, i) => <blockquote key={i} className="whitespace-pre-wrap">{g.citation.source_id}：{g.citation.quote} · {g.fact} = {g.value}</blockquote>)}{item.rule_quote && <p>{item.rule_quote}</p>}{item.counterexample_quote && <p>{item.counterexample_quote}</p>}</details>
      </article>)}
      <details><summary>评分调用与用量（{state.attempts.length} 次）</summary>{state.attempts.map(a => <p key={a.number}>第 {a.number} 次 · {a.code} · 输入 {a.prompt_tokens ?? "未知"} / 输出 {a.completion_tokens ?? "未知"} / 总 token {a.total_tokens ?? "未知"}</p>)}</details>
      {state.status === "completed" && state.frozen_sequence != null && <ScoreReview key={runId} runId={runId} config={config} />}
    </>}
  </section>
}
