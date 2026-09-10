import { type FormEvent, useCallback, useEffect, useState } from "react"
import { createRoot } from "react-dom/client"
import {
  AccountsService,
  type InvitationPublic,
  type UserPublic,
} from "./client"
import { client } from "./client/client.gen"
import { Button } from "./components/ui/button"
import { Input } from "./components/ui/input"
import { Label } from "./components/ui/label"
import { AccountErasure } from "./features/AccountErasure"
import { PasswordReset } from "./features/PasswordReset"
import { ModelConfig } from "./features/ModelConfig"
import "./index.css"
import { FreeTopic } from "./features/FreeTopic"
import { JDRoute } from "./features/JDRoute"
import { Training } from "./features/Training"
import { PersonalReview } from "./features/PersonalReview"
import { Records } from "./features/Records"
import { Project } from "./features/Project"
import { Boss } from "./features/Boss"
import { CapabilityMap } from "./features/CapabilityMap"

client.setConfig({ auth: () => sessionStorage.getItem("token") ?? undefined })

function readVerificationToken() {
  const token = new URLSearchParams(location.hash.slice(1)).get("verify") ?? ""
  if (token) history.replaceState(null, "", location.pathname + location.search)
  return token
}

function App() {
  const [verificationToken, setVerificationToken] = useState(readVerificationToken)
  useEffect(() => {
    const capture = () => setVerificationToken(readVerificationToken())
    window.addEventListener("hashchange", capture)
    return () => window.removeEventListener("hashchange", capture)
  }, [])
  const [user, setUser] = useState<UserPublic | null>(null)
  const reflectLevel = useCallback((level: string) => setUser(current => current && current.level !== level ? { ...current, level } : current), [])
  const [signup, setSignup] = useState(false)
  const resetSession = useCallback((notice: string) => {
    sessionStorage.removeItem("token")
    setUser(null)
    setInvitations([])
    setMessage(notice)
  }, [])
  useEffect(() => {
    const id = client.instance.interceptors.response.use(undefined, error => {
      const token = sessionStorage.getItem("token")
      if (error.response?.status === 401 && token && error.config?.headers?.Authorization === `Bearer ${token}`) {
        resetSession("登录状态已失效，请重新登录。")
      }
      return Promise.reject(error)
    })
    return () => client.instance.interceptors.response.eject(id)
  }, [resetSession])
  const [message, setMessage] = useState("")
  const [busy, setBusy] = useState(false)
  const [invitations, setInvitations] = useState<InvitationPublic[]>([])
  const [offset, setOffset] = useState(0)
  const loadInvites = useCallback(async (next: number) => {
    const token = sessionStorage.getItem("token")
    const { data } = await AccountsService.invitations({
      query: { offset: next },
    })
    if (sessionStorage.getItem("token") !== token) return
    setInvitations(data)
    setOffset(next)
  }, [])
  const restore = useCallback(async () => {
    const token = sessionStorage.getItem("token")
    if (!token) return
    const { data } = await AccountsService.me()
    if (sessionStorage.getItem("token") !== token) return
    setUser(data)
    if (data.is_superuser) await loadInvites(0)
  }, [loadInvites])
  const action = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true)
    setMessage("")
    try {
      await fn()
    } catch (error: unknown) {
      const e = error as {
        response?: { status?: number; data?: { detail?: unknown } }
        config?: { url?: string }
      }
      // Authenticated 401s are handled once by the session-bound interceptor.
      // A delayed failure from a previous account must not affect the current one.
      if (e.response?.status === 401 && e.config?.url !== "/api/v1/login/access-token") return
      const detail = e.response?.data?.detail
      setMessage(
        typeof detail === "string"
          ? detail
          : "操作未确认成功，请重试或刷新查看实际状态。",
      )
    } finally {
      setBusy(false)
    }
  }, [])
  useEffect(() => {
    void action(restore)
  }, [restore, action])
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const email = String(form.get("email")),
      password = String(form.get("password"))
    await action(async () => {
      if (signup) {
        const { data } = await AccountsService.register({
          body: {
            email,
            password,
            invitation_code: String(form.get("invitation_code")),
          },
        })
        setSignup(false)
        setMessage(data.verification_sent
          ? "注册成功，验证邮件已交给本地收件服务。请登录并打开邮箱中的链接。"
          : "注册成功，但验证邮件发送失败。请登录后重发验证邮件。")
      } else {
        const { data } = await AccountsService.login({
          body: { username: email, password },
        })
        sessionStorage.setItem("token", data.access_token)
        await restore()
      }
    })
  }
  return (
    <main className="mx-auto max-w-xl p-6 space-y-6 break-words">
      <h1 className="text-2xl font-bold">我是天才程序员</h1>
      <p role="status" className="break-words">
        {message}
      </p>
      <PasswordReset onReset={resetSession} />
      <AccountErasure userId={user?.id ?? null} onAccepted={token => {
        const current = sessionStorage.getItem("token")
        if (current && current !== token) return
        resetSession("注销已受理，账号私有页面与旧会话已清除；请通过回执核对资料清除进度。")
        setVerificationToken("")
        history.replaceState(null, "", location.pathname)
      }} />
      {verificationToken && <p>已读取验证链接，请登录对应邮箱账号后确认验证。</p>}
      {!user ? (
        <>
          <h2>{signup ? "受邀注册" : "邮箱登录"}</h2>
          <form onSubmit={submit} className="space-y-4">
            <div>
              <Label htmlFor="email">邮箱</Label>
              <Input
                id="email"
                name="email"
                type="email"
                autoComplete="username"
                required
                maxLength={255}
              />
            </div>
            <div>
              <Label htmlFor="password">密码（12–128 字符）</Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete={signup ? "new-password" : "current-password"}
                required
                minLength={signup ? 12 : undefined}
                maxLength={128}
              />
            </div>
            {signup && (
              <div>
                <Label htmlFor="invitation_code">邀请码</Label>
                <Input
                  id="invitation_code"
                  name="invitation_code"
                  required
                  minLength={20}
                  maxLength={128}
                  autoComplete="off"
                />
              </div>
            )}
            <Button disabled={busy} type="submit">
              {signup ? "注册" : "登录"}
            </Button>
          </form>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => {
              setSignup(!signup)
              setMessage("")
            }}
          >
            {signup ? "已有账号，登录" : "使用邀请码注册"}
          </Button>
        </>
      ) : (
        <>
          <h2 className="text-xl font-semibold">我的训练首页</h2>
          <p>
            {user.email} · {user.level}
          </p>
          <p>
            {user.email_verified
              ? "邮箱已验证"
              : "邮箱未验证，暂不能进入训练。请查看验证邮件或重发。"}
          </p>
          {verificationToken && <Button disabled={busy} onClick={() => action(async () => {
            const token = sessionStorage.getItem("token")
            const { data } = await AccountsService.verifyEmail({ body: { token: verificationToken } })
            if (sessionStorage.getItem("token") !== token) return
            setUser(data)
            setVerificationToken("")
            setMessage("邮箱验证成功。训练不会自动启动。")
          })}>确认验证邮箱</Button>}
          {!user.email_verified && <Button disabled={busy} variant="outline" onClick={() => action(async () => {
            const { data } = await AccountsService.resendVerification()
            setMessage(data.message)
          })}>重发验证邮件</Button>}
          <Button
            disabled={busy}
            onClick={() =>
              action(async () => {
                await AccountsService.trainingAccess()
                setMessage("邮箱准入检查通过")
              })
            }
          >
            检查训练准入
          </Button>
          <Button
            disabled={busy}
            variant="outline"
            onClick={() => action(async () => {
              await AccountsService.logout()
              sessionStorage.removeItem("token")
              setUser(null)
              setInvitations([])
              setMessage("已退出当前设备")
            })}
          >
            退出登录
          </Button>
          {user.email_verified && <Boss key={`boss:${user.id}`} />}
          {user.email_verified && <FreeTopic key={`topic:${user.id}`} />}
          {user.email_verified && <JDRoute key={`jd:${user.id}`} />}
          {user.email_verified && <Training key={`training:${user.id}`} onLevel={reflectLevel} />}
          {user.email_verified && <Project key={`project:${user.id}`} />}
          {user.email_verified && <PersonalReview key={`personalreview:${user.id}`} />}
          {user.email_verified && <Records key={`records:${user.id}`} />}
          {user.email_verified && <CapabilityMap key={`capabilitymap:${user.id}`} />}
          {user.email_verified && <ModelConfig key={`modelconfig:${user.id}`} action={action} busy={busy} />}
          {user.is_superuser && (
            <section className="space-y-4">
              <h2 className="text-xl font-semibold">邀请管理</h2>
              <p>未使用码永久有效，不绑定收件人；请自行复制发放。</p>
              <Button
                disabled={busy}
                onClick={() =>
                  action(async () => {
                    await AccountsService.generateInvitation()
                    await loadInvites(0)
                  })
                }
              >
                生成邀请码
              </Button>
              <Button
                disabled={busy}
                variant="outline"
                onClick={() => action(() => loadInvites(offset))}
              >
                刷新状态
              </Button>
              {invitations.map((invite) => (
                <article
                  key={invite.id}
                  className="border rounded p-3 space-y-2"
                >
                  <code className="block break-all">{invite.code}</code>
                  <p>
                    {
                      { unused: "未使用", used: "已使用", revoked: "已作废" }[
                        invite.status
                      ]
                    }
                  </p>
                  <Button
                    disabled={busy}
                    variant="outline"
                    onClick={() =>
                      action(async () => {
                        await navigator.clipboard.writeText(invite.code)
                        setMessage("邀请码已复制")
                      })
                    }
                  >
                    复制
                  </Button>
                  {invite.status === "unused" && (
                    <Button
                      disabled={busy}
                      variant="outline"
                      onClick={() =>
                        action(async () => {
                          await AccountsService.revoke({
                            path: { invitation_id: invite.id },
                          })
                          await loadInvites(offset)
                        })
                      }
                    >
                      作废
                    </Button>
                  )}
                </article>
              ))}
              <Button
                disabled={busy || offset === 0}
                variant="outline"
                onClick={() => action(() => loadInvites(offset - 100))}
              >
                上一页
              </Button>
              <Button
                disabled={busy || invitations.length < 100}
                variant="outline"
                onClick={() => action(() => loadInvites(offset + 100))}
              >
                下一页
              </Button>
            </section>
          )}
        </>
      )}
    </main>
  )
}

createRoot(document.getElementById("root")!).render(<App />)
