import { useEffect, useRef, useState } from "react"
import { RecordsService, type PreviewPublic, type DeletionPublic, type Record as LearningRecord } from "../client"
import { Button } from "../components/ui/button"
import { Input } from "../components/ui/input"

const objectNames: { [key: string]: string } = { training: "学习轮次", topic: "路线与来源", project: "固定项目来源", quality: "关联质量材料报告" }
const button = "h-auto min-h-9 max-w-full whitespace-normal"

export function Records() {
  const owner = useRef(sessionStorage.getItem("token"))
  const alive = useRef(true)
  const generation = useRef(0)
  const [records, setRecords] = useState<LearningRecord[]>([])
  const [selected, setSelected] = useState("")
  const [password, setPassword] = useState("")
  const [preview, setPreview] = useState<PreviewPublic | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [receipt, setReceipt] = useState<DeletionPublic | null>(null)
  const [receiptId, setReceiptId] = useState(() => new URLSearchParams(location.search).get("deletion_receipt") ?? "")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [loaded, setLoaded] = useState(false)
  const current = (attempt: number) => alive.current && generation.current === attempt && owner.current === sessionStorage.getItem("token")
  useEffect(() => { alive.current = true; return () => { alive.current = false; generation.current++ } }, [])
  const record = records.find(r => `${r.kind}:${r.id}` === selected)
  function change(value: string) {
    generation.current++
    setSelected(value); setPassword(""); setPreview(null); setConfirmed(false); setBusy(false); setError("")
  }
  async function act(operation: (attempt: number) => Promise<void>) {
    const attempt = ++generation.current
    setBusy(true); setError("")
    try { await operation(attempt) }
    catch (error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      if (current(attempt)) setError(typeof detail === "string" ? detail : "操作结果尚未确认。输入和删除请求编号保留，请读取实际状态；不要据此判断已经删除。")
    } finally { if (current(attempt)) { setBusy(false); setPassword("") } }
  }
  async function load() {
    await act(async attempt => { const { data } = await RecordsService.records(); if (current(attempt)) { setRecords(data); setLoaded(true) } })
  }
  async function inspect() {
    if (!record) return
    await act(async attempt => {
      const { data } = await RecordsService.deletionPreview({ body: { kind: record.kind, target_id: record.id, password } })
      if (!current(attempt)) return
      setPreview(data); setConfirmed(false); setReceipt(null); setReceiptId(data.id)
      const url = new URL(location.href); url.searchParams.set("deletion_receipt", data.id); history.replaceState(null, "", url)
    })
  }
  function completed(data: DeletionPublic) {
    // Completion is an account fact, not a response for the currently selected
    // row. A -> B must not discard A's accepted permanent deletion result.
    if (!data.completed_at || !alive.current || owner.current !== sessionStorage.getItem("token")) return
    const cleared = `deletion-cleared:${data.id}`
    if (sessionStorage.getItem(cleared) === "1") return
    try { sessionStorage.setItem(cleared, "1") } catch { /* Reload still clears private projections if storage is full. */ }
    location.assign(`/?deletion_receipt=${encodeURIComponent(data.id)}`)
  }
  async function checkReceipt() {
    if (!receiptId) return
    await act(async attempt => {
      const { data } = await RecordsService.deletionReceipt({ path: { identity: receiptId } })
      completed(data)
      if (current(attempt)) { setReceipt(data); if (data.completed_at) { setPreview(null); setConfirmed(false) } }
    })
  }
  async function remove() {
    if (!preview || !confirmed || !record || preview.target_id !== record.id || preview.kind !== record.kind) return
    await act(async () => {
      const { data } = await RecordsService.confirmDeletion({ path: { identity: preview.id }, body: { confirmation: "永久删除所列资料及副本" } })
      completed(data)
    })
  }
  async function archive() {
    if (!record) return
    await act(async attempt => {
      await RecordsService.archive({ body: { kind: record.kind, target_id: record.id, archived: !record.archived } })
      if (current(attempt)) { setRecords(old => old.map(r => r.kind === record.kind && r.id === record.id ? { ...r, archived: !r.archived } : r)); setPreview(null); setConfirmed(false) }
    })
  }
  return <section aria-labelledby="records-title" className="space-y-3 rounded border p-4 break-words">
    <h2 id="records-title" className="text-xl font-semibold">我的记录与资料管理</h2>
    <p>从当前列表移除只归档，原文、证据和奖励保留。永久删除清除所列资料及私有副本，需重新认证、核对影响范围，再最终确认。练习中的“删当前草稿”仍只处理那一份草稿。</p>
    <Button className={button} disabled={busy} onClick={() => void load()}>读取本人记录</Button>
    {loaded && !records.length && <p>尚无已保存的学习记录或来源。</p>}
    {!!records.length && <label className="block">选择准确的记录或来源
      <select aria-label="选择管理记录" value={selected} onChange={e => change(e.target.value)} className="block w-full min-w-0 rounded border p-2">
        <option value="">请选择</option>
        {records.map(r => <option key={`${r.kind}:${r.id}`} value={`${r.kind}:${r.id}`}>{r.label} · {new Date(r.created_at).toLocaleString()} · {r.id}{r.deleted ? "（已永久删除）" : r.archived ? "（已归档）" : ""}</option>)}
      </select>
    </label>}
    {record && <div className="space-y-3">
      <p className="break-all">所选：{record.label} · {record.id}</p>
      {record.deleted ? <p>已永久删除。这里保留不含原文的标记；奖励、等级和已开放学习权仍保留。</p> : <>
        <Button className={button} variant="outline" disabled={busy} onClick={() => void archive()}>{record.archived ? "取消归档" : "只归档，不删除资料"}</Button>
        <label className="block">重新输入当前密码以预览永久删除范围<Input aria-label="删除重新认证密码" type="password" autoComplete="current-password" value={password} onChange={e => { setPassword(e.target.value); setPreview(null); setConfirmed(false) }} /></label>
        <Button className={button} disabled={busy || !password} onClick={() => void inspect()}>重新认证并预览影响，不执行删除</Button>
      </>}
    </div>}
    {preview && <div className="space-y-3 rounded border p-3" aria-label="最终删除影响范围">
      <h3 className="font-semibold">核对本次准确范围</h3>
      {Object.entries(preview.objects).filter(([, ids]) => ids.length).map(([kind, ids]) => <div key={kind}><p>{objectNames[kind] ?? "关联记录"}：{ids.length} 项</p><ul>{ids.map(id => <li className="break-all" key={id}>{id}</li>)}</ul></div>)}
      <p>原文与私有副本记录：{Object.values(preview.private_rows).reduce((a, b) => a + b, 0)} 项。</p>
      {!!preview.shared_attachment_candidates && <p>所选记录关联 {preview.shared_attachment_candidates} 份附件；私有引用会清除，共享字节仅在没有其他有效引用时清除。</p>}
      {!!preview.project_current_pointers_cleared.length && <p>所删版本当前被 {preview.project_current_pointers_cleared.length} 条项目路线选中；该选择会清空，不自动改选旧版本。</p>}
      {!!preview.comparison_only_runs.length && <div><p>以下后续轮次只清历史比较副本，保留它们自己的题面和原答：</p><ul>{preview.comparison_only_runs.map(id => <li className="break-all" key={id}>{id}</li>)}</ul></div>}
      {preview.consequences.map(text => <p key={text}>{text}</p>)}
      <p>若资料或关联范围变化，本次确认将被拒绝，需要重新预览。预览有效至 {new Date(preview.expires_at).toLocaleTimeString()}。</p>
      <label className="flex items-start gap-2"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />我已核对以上范围和后果，确认永久删除所列资料及副本</label>
      <Button className={button} disabled={busy || !confirmed} onClick={() => void remove()}>最终确认永久删除，无法撤销</Button>
    </div>}
    {receiptId && <div className="space-y-2"><p className="break-all">删除请求编号：{receiptId}</p><Button className={button} variant="outline" disabled={busy} onClick={() => void checkReceipt()}>读取删除实际状态</Button></div>}
    {receipt && <p role="status">{receipt.completed_at ? `已于 ${new Date(receipt.completed_at).toLocaleString()} 完成永久删除。保留无原文的删除标记、奖励、等级、已开放学习权和用量事实。` : "该请求尚未完成永久删除。需要重新读取记录、认证和预览后再明确确认。"}</p>}
    {error && <p role="alert">{error}</p>}
  </section>
}
