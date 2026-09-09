import { type FormEvent, useCallback, useEffect, useRef, useState } from "react"
import { ModelconfigService, type ModelConfigPublic, type ProbeResult, type UsageReport } from "../client"
import { Button } from "../components/ui/button"
import { Input } from "../components/ui/input"
import { Label } from "../components/ui/label"

type Props = { action: (fn: () => Promise<void>) => Promise<void>; busy: boolean }

export function ModelConfig({ action, busy }: Props) {
  const [saved, setSaved] = useState<ModelConfigPublic | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [url, setUrl] = useState("")
  const [model, setModel] = useState("")
  const [notice, setNotice] = useState("")
  const [accepted, setAccepted] = useState(false)
  const [probe, setProbe] = useState<ProbeResult | null>(null)
  const [hasDraftKey, setHasDraftKey] = useState(false)
  const [usage, setUsage] = useState<UsageReport | null>(null)
  const active = useRef(true)
  const sessionToken = useRef(sessionStorage.getItem("token"))
  const current = () => active.current && sessionToken.current === sessionStorage.getItem("token")
  useEffect(() => { active.current = true; return () => { active.current = false; editVersion.current++ } }, [])
  const editVersion = useRef(0)
  const keyVersion = useRef(0)
  const keyInput = useRef<HTMLInputElement>(null)
  function changed() {
    editVersion.current++
    setProbe(null)
    setNotice("")
  }
  const load = useCallback(async () => {
    const version = ++editVersion.current
    setProbe(null)
    const { data } = await ModelconfigService.readConfig()
    if (!current() || version !== editVersion.current) return
    // Generated Axios client normalizes a JSON null response to {}.
    const config = data?.version ? data : null
    setSaved(config)
    setUrl(config?.service_url ?? "")
    setModel(config?.model_id ?? "")
    setAccepted(false)
    if (keyInput.current) keyInput.current.value = ""
    setHasDraftKey(false)
    setLoaded(true)
  }, [])
  useEffect(() => { void load().catch(error => action(async () => { throw error })) }, [action, load])
  async function recoverRevocation(version: number) {
    try {
      const { data } = await ModelconfigService.readConfig()
      if (current() && version === editVersion.current && data?.version === saved?.version && data?.revoked) {
        setSaved(data)
        setNotice("旧配置已撤销，本次变更未确认完成。当前输入保留，请主动重新保存或删除。")
      }
    } catch { /* The original failure remains visible through action. */ }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    changed()
    const version = editVersion.current
    const submittedKeyVersion = keyVersion.current
    if (saved) setNotice("正在终止旧配置后续调用并尝试取消在途请求；尚未确认保存成功。")
    await action(async () => {
      const key = keyInput.current?.value ?? ""
      try {
        const { data } = await ModelconfigService.saveConfig({ body: {
          service_url: url, model_id: model, api_key: key || null,
          expected_version: saved?.version ?? null, disclosure_accepted: accepted,
        } })
        if (!current()) return
        setSaved(data)
        if (version === editVersion.current) {
          setUrl(data.service_url)
          setModel(data.model_id)
          setNotice("配置已保存。未调用模型服务，连接和教学质量尚未验证。")
        }
      } catch (error) {
        await recoverRevocation(version)
        throw error
      } finally {
        if (current() && submittedKeyVersion === keyVersion.current) {
          if (keyInput.current) keyInput.current.value = ""
          setHasDraftKey(false)
        }
      }
    })
  }
  async function runProbe(kind: "test" | "models") {
    changed()
    const version = editVersion.current
    const submittedKeyVersion = keyVersion.current
    const key = keyInput.current?.value ?? ""
    if (!url || !key || !accepted || (kind === "test" && !model)) return
    await action(async () => {
      try {
        const { data } = await ModelconfigService.probe({ path: { kind }, body: {
          service_url: url, model_id: model, api_key: key, disclosure_accepted: accepted,
        } })
        if (current() && version === editVersion.current) setProbe(data)
      } catch (error) {
        if (current() && version === editVersion.current) throw error
      } finally {
        if (current() && submittedKeyVersion === keyVersion.current) {
          if (keyInput.current) keyInput.current.value = ""
          setHasDraftKey(false)
        }
      }
    })
  }
  return <section className="space-y-4" aria-labelledby="model-config-title">
    <h2 id="model-config-title" className="text-xl font-semibold">个人模型配置</h2>
    <p>{loaded ? saved ? saved.revoked ? "旧配置已撤销，不会继续调用。" : "已保存一套配置，Key 已加密保存且不可回读。" : "尚未配置，不会分配默认 Key。" : "正在读取配置…"}</p>
    {saved && <section aria-label="评分质量" className="space-y-2 break-words">
      <h3 className="font-semibold">评分质量</h3>
      <p>{saved.quality?.status === "failed" ? "已知评分未达标：仅可普通练习与复盘，服务端阻止新增独立证明和 Boss 晋升。" : saved.quality?.status === "passed" ? "已有达标评测依据：仅适用于报告中的配置、评分规则与来源版本；实际题目仍逐次核对适用范围。" : saved.quality?.status === "version_mismatch" ? "旧评测版本不匹配，当前评分可靠性未验证。" : "评分可靠性未验证。连接成功和输出结构正确均不代表教学或判分合格。"}</p>
      <p>不会自动调用付费评测。修复后需新的受信任复测依据，并主动开启新轮；历史记录保留，旧轮不会因恢复而补发证明或晋升。</p>
      {saved.quality?.report_id && <details><summary>查看评测版本与依据</summary>
        <p>报告 {saved.quality.report_id}；评分规则 {saved.quality.evaluation_rule}；素材 {saved.quality.corpus_version}；标注 {saved.quality.annotation_version}</p>
        <p>样本 {saved.quality.sample_count}，一致 {saved.quality.correct_count}，关键安全错误放行 {saved.quality.safety_false_accepts}。这些是报告样本结果，不代表总体错误率或学习效果。</p>
        <p className="break-all">报告 SHA-256：{saved.quality.artifact_sha256}</p>
        {saved.quality.source_versions?.map(source => <p className="break-all" key={source}>{source}</p>)}
      </details>}
    </section>}
    {saved?.revoked && <p role="alert">旧配置已撤销，不可再调用。上次切换可能未完成；请主动重新保存或删除，系统不会恢复旧调用。</p>}
    {saved && <p>保存新地址、Key 或模型 ID，或删除配置，将结束旧配置关联任务的后续调用并尝试取消在途请求；在途可能收费，不保证撤回或退款。已核对成果与用量保留，新配置须主动启动任务。</p>}
    <p>运营者能够在服务端解密 Key；Key 仅用于向你指定的模型服务认证。训练时，当前案例材料、作答和必要学习上下文会发送至该服务，不发送其他用户记录。请勿粘贴未授权公司或个人资料。</p>
    <p className="break-all">本次保存指定接收方：{url || "请填写服务地址"}</p>
    <form onSubmit={submit} className="space-y-4" autoComplete="off">
      <div><Label htmlFor="model-url">模型服务地址（公网 HTTPS）</Label>
        <Input id="model-url" type="url" required maxLength={2048} value={url} onChange={e => { changed(); setUrl(e.target.value); setAccepted(false) }} placeholder="https://api.example.com/v1" /></div>
      <div><Label htmlFor="model-id">模型 ID</Label>
        <Input id="model-id" required maxLength={255} value={model} onChange={e => { changed(); setModel(e.target.value) }} /></div>
      <div><Label htmlFor="model-key">API Key{saved ? "（留空保留，变更地址必须重填）" : ""}</Label>
        <Input id="model-key" ref={keyInput} type="password" autoComplete="new-password" required={!saved || url.replace(/\/+$/, "") !== saved.service_url} maxLength={4096} onChange={e => { keyVersion.current++; changed(); setHasDraftKey(Boolean(e.target.value)) }} />
        <p>Key 仅在输入期间暂存；每次提交后清空，失败时请重新输入。</p></div>
      <label className="flex gap-2 items-start"><input type="checkbox" checked={accepted} onChange={e => { changed(); setAccepted(e.target.checked) }} required />我已知晓运营者可解密，以及上述指定服务和必要学习材料接收范围。</label>
      <Button type="submit" disabled={busy || !loaded}>保存配置</Button>
    </form>
    <p>测试连接、获取模型 ID 及自动重试都可能收费。每次操作最多尝试 3 次，每次最长 120 秒；不会估算金额或限制累计用量。测试只发送「请仅回复 OK」，不发送学习记录；列表不会逐个测试模型。</p>
    <p>测试和列表使用当前编辑内容，必须重新填写 Key，不会读取已保存 Key，也不会自动保存；训练使用已保存配置。</p>
    <Button variant="outline" disabled={busy || !url || !model || !hasDraftKey || !accepted} onClick={() => void runProbe("test")}>测试连接</Button>
    <Button variant="outline" disabled={busy || !url || !hasDraftKey || !accepted} onClick={() => void runProbe("models")}>获取模型 ID</Button>
    {probe && <div aria-live="polite" className="space-y-2">
      <p>{probe.message}</p>
      {(probe.models ?? []).length > 0 && <div><Label htmlFor="returned-model">服务返回的模型 ID（选择只回填）</Label>
        <select id="returned-model" className="w-full min-w-0 border rounded p-2" value="" onChange={e => { if (e.target.value) { setModel(e.target.value); changed() } }}>
          <option value="">请选择，不自动替换当前模型</option>
          {(probe.models ?? []).map(id => <option key={id} value={id}>{id}</option>)}
        </select></div>}
      <p>本次操作共 {(probe.attempts ?? []).length} 次尝试；以下为服务商返回的 token，不是完整账单。实际费用请查看模型服务商账单。</p>
      {(probe.attempts ?? []).map(a => <p key={a.number}>第 {a.number} 次：{a.code}；输入 {a.prompt_tokens ?? "未知"}，输出 {a.completion_tokens ?? "未知"}，合计 {a.total_tokens ?? "未知"}。</p>)}
    </div>}
    <Button variant="outline" disabled={busy} onClick={() => action(async () => { await load(); setNotice("已读取服务端配置，未保存输入已丢弃。") })}>刷新配置</Button>
    {saved && <Button variant="outline" disabled={busy} onClick={() => {
      if (!window.confirm("删除这套配置和 Key？将终止旧配置后续调用并尝试取消在途请求；在途可能收费，不保证撤回或退款。已核对成果与用量保留。")) return
      changed()
      const version = editVersion.current
      void action(async () => {
        try {
          await ModelconfigService.deleteConfig({ query: { expected_version: saved.version } })
          if (!current() || version !== editVersion.current) return
          await load()
          if (current()) setNotice("配置及 Key 已删除，旧版本不能发起新调用。")
        } catch (error) { await recoverRevocation(version); throw error }
      })
    }}>删除配置及 Key</Button>}
    <Button variant="outline" className="max-w-full h-auto min-h-9 whitespace-normal" disabled={busy} onClick={() => action(async () => {
      const { data } = await ModelconfigService.readUsage()
      if (current()) setUsage(data)
    })}>读取逐次与汇总用量</Button>
    {usage && <div aria-label="模型用量" className="space-y-2 min-w-0">
      <p>已记录 {usage.calls.length} 次尝试，按服务器调用标识去重。实际费用请查看模型服务商账单；没有返回用量的调用不表示免费。</p>
      {Object.entries(usage.totals).map(([field, total]) => <p key={field}>{field === "prompt_tokens" ? "输入" : field === "completion_tokens" ? "输出" : "总 token"}：已知部分 {total.known}；{total.unknown_calls ? `另有 ${total.unknown_calls} 次未知，不能视为完整合计` : "无缺失字段"}。</p>)}
      <details><summary>逐调用归属与真实用量</summary>{usage.calls.map(call => <p key={`${call.kind}:${call.id}`} className="break-all">{call.kind} · {call.task_id} · 第 {call.number} 次 · 配置版本 {call.config_version ?? "测试/列表编辑快照"} · {call.destination} · {call.model_id} · {call.code}；输入 {call.prompt_tokens ?? "未知"} / 输出 {call.completion_tokens ?? "未知"} / 总 token {call.total_tokens ?? "未知"}</p>)}</details>
    </div>}
    <p aria-live="polite">{notice}</p>
  </section>
}
