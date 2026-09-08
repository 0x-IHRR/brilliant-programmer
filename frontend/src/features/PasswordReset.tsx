import { type FormEvent, useEffect, useState } from "react"
import { AccountsService } from "../client"
import { Button } from "../components/ui/button"
import { Input } from "../components/ui/input"
import { Label } from "../components/ui/label"

function readResetToken() {
  const token = new URLSearchParams(location.hash.slice(1)).get("reset") ?? ""
  if (token) history.replaceState(null, "", location.pathname + location.search)
  return token
}

export function PasswordReset({ onReset }: { onReset: (message: string) => void }) {
  const [token, setToken] = useState(readResetToken)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  useEffect(() => {
    const capture = () => {
      const next = readResetToken()
      if (next) { setToken(next); setMessage("") }
    }
    window.addEventListener("hashchange", capture)
    return () => window.removeEventListener("hashchange", capture)
  }, [])
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    setBusy(true)
    setMessage("")
    try {
      if (token) {
        const { data: result } = await AccountsService.resetPassword({ body: { token, password: String(data.get("new_password")) } })
        setToken("")
        setOpen(false)
        onReset(result.message)
      } else {
        const { data: result } = await AccountsService.passwordResetEmail({ body: { email: String(data.get("reset_email")) } })
        setMessage(result.message)
      }
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      setMessage(typeof detail === "string" ? detail : "操作未确认成功。请重试；若链接已用，请先用新密码登录或重新申请。")
    } finally {
      // Keep the recovery email, but do not retain the new password after submission.
      const password = form.elements.namedItem("new_password") as HTMLInputElement | null
      if (password) password.value = ""
      setBusy(false)
    }
  }
  return <section aria-label="密码找回" className="space-y-3">
    <Button variant="outline" disabled={busy} onClick={() => { setOpen(!open); setMessage("") }}>忘记密码</Button>
    {(open || token) && <>
      <h2>{token ? "设置新密码" : "申请密码重置"}</h2>
      <p>仅通过原已验证邮箱找回。链接成功使用一次后失效；重置成功后所有设备需重新登录，学习记录与模型配置保留。</p>
      <form onSubmit={submit} className="space-y-3">
        {token ? <div>
          <Label htmlFor="new_password">新密码（12–128 字符）</Label>
          <Input id="new_password" name="new_password" type="password" autoComplete="new-password" required minLength={12} maxLength={128} />
        </div> : <div>
          <Label htmlFor="reset_email">原已验证邮箱</Label>
          <Input id="reset_email" name="reset_email" type="email" autoComplete="email" required maxLength={255} />
        </div>}
        <Button type="submit" disabled={busy}>{token ? "重置密码并退出所有设备" : "申请重置邮件"}</Button>
      </form>
      {token && <Button variant="outline" disabled={busy} onClick={() => { setToken(""); setOpen(true); setMessage("") }}>重新申请链接</Button>}
      <p role="alert">{message}</p>
    </>}
  </section>
}
