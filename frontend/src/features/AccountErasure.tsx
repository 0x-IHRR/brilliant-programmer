import { useEffect, useRef, useState } from "react"
import { AccountErasureService, type Preview, type Status } from "../client"
import { Button } from "../components/ui/button"
import { Input } from "../components/ui/input"

type Capability = { owner: string; request: string; key: string }
const storage = "account-erasure-receipt"
const button = "h-auto min-h-9 max-w-full whitespace-normal"
function read(): Capability | null {
  try {
    const data = JSON.parse(sessionStorage.getItem(storage) ?? "null")
    return data && typeof data.owner === "string" && typeof data.request === "string" && typeof data.key === "string" ? data : null
  } catch { return null }
}

export function AccountErasure({ userId, onAccepted }: { userId: string | null; onAccepted: (token: string | null) => void }) {
  const [capability, setCapability] = useState<Capability | null>(read)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [status, setStatus] = useState<Status | null>(null)
  const [password, setPassword] = useState("")
  const [confirmation, setConfirmation] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const currentOwner = useRef(userId)
  currentOwner.current = userId
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => { setPassword(""); setPreview(null); setConfirmation(false); setError(""); setBusy(false) }, [userId])
  const visible = capability && (!userId || capability.owner === userId)
  function same(token: string | null) { return alive.current && sessionStorage.getItem("token") === token }
  function received(data: Status, cap: Capability, token: string | null) {
    // Completion is an account fact, independent of local form changes. A late
    // A result must never clear B; an intercepted A 401 may already have logged out.
    if (!alive.current || (currentOwner.current && currentOwner.current !== cap.owner)) return
    const now = sessionStorage.getItem("token")
    if (now !== token && now !== null) return
    setStatus(data)
    if (data.accepted_at) { setPreview(null); setConfirmation(false); onAccepted(token) }
  }
  async function inspect() {
    const token = sessionStorage.getItem("token"), owner = userId
    if (!owner || !token) return
    setBusy(true); setError("")
    try {
      const { data } = await AccountErasureService.erasurePreview({ body: { password } })
      if (!same(token) || currentOwner.current !== owner) return
      const cap = { owner, request: data.request_id, key: data.receipt_key }
      // Save recovery capability before enabling the final destructive action.
      sessionStorage.setItem(storage, JSON.stringify(cap))
      setCapability(cap); setPreview(data); setStatus(null); setConfirmation(false)
    } catch { if (same(token)) setError("重新认证或预览未完成。请检查密码；恢复凭据未能保存时不会启用最终确认。") }
    finally { if (same(token)) { setBusy(false); setPassword("") } }
  }
  async function request(confirm: boolean) {
    const cap = capability, token = sessionStorage.getItem("token")
    if (!cap || (userId && cap.owner !== userId) || (confirm && (!confirmation || !preview))) return
    setBusy(true); setError("")
    try {
      const options = { path: { request_id: cap.request }, body: { receipt_key: cap.key } }
      const { data } = confirm
        ? await AccountErasureService.erasureConfirm({ ...options, body: { ...options.body, confirmation: "注销本账号并永久删除全部私有资料" } })
        : await AccountErasureService.erasureStatus(options)
      received(data, cap, token)
    } catch {
      if (alive.current && (!currentOwner.current || currentOwner.current === cap.owner) && (!sessionStorage.getItem("token") || same(token))) {
        setError("尚未确认实际注销结果。凭据已保存在当前浏览器会话，可退出登录或刷新后继续读取回执；401 本身不代表注销完成。")
      }
    } finally { if (alive.current && (!currentOwner.current || currentOwner.current === cap.owner)) setBusy(false) }
  }
  if (!userId && !capability) return null
  return <section aria-label="注销账号" className="space-y-3 border-t pt-4 break-words">
    <h2 className="text-xl font-semibold">注销账号与删除回执</h2>
    {userId && <>
      <p>注销会清除本账号全部私有资料与成长档案，不能撤销。只删除某份资料请使用“学习记录”。</p>
      <label className="block">重新输入当前密码<Input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
      <Button className={button} disabled={busy || !password} onClick={inspect}>重新认证并查看注销范围</Button>
    </>}
    {preview && visible && <div className="space-y-3">
      {preview.consequences.map(line => <p key={line}>{line}</p>)}
      <p>本次预览涉及 {Object.values(preview.records).reduce((a, b) => a + b, 0)} 条记录，确认前新保存的本账号资料也会清除。</p>
      <label className="flex gap-2 items-start"><input type="checkbox" checked={confirmation} disabled={busy} onChange={e => setConfirmation(e.target.checked)} />我明确确认注销本账号并永久删除全部私有资料</label>
      <Button className={button} variant="destructive" disabled={busy || !confirmation} onClick={() => request(true)}>最终确认注销本账号</Button>
    </div>}
    {visible && <>
      <p>注销请求编号：{capability.request}</p>
      <p>恢复凭据仅保存在当前浏览器会话，不写入链接。注销后不需登录即可核对这项请求；关闭整个浏览器会话可能失去查询凭据。</p>
      <Button className={button} variant="outline" disabled={busy} onClick={() => request(false)}>读取实际注销回执</Button>
      {status && <p role="status">{status.completed_at ? "注销资料清除已完成" : status.accepted_at ? "注销已受理，在线资料清除尚未完成" : "尚未受理最终注销，账号未因本预览被删除"}</p>}
    </>}
    {error && <p role="alert">{error}</p>}
  </section>
}
