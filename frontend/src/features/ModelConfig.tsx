import { type FormEvent, useCallback, useEffect, useRef, useState } from "react"
import { ModelconfigService, type ModelConfigPublic } from "../client"
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
  const keyInput = useRef<HTMLInputElement>(null)
  const load = useCallback(async () => {
    const { data } = await ModelconfigService.readConfig()
    // Generated Axios client normalizes a JSON null response to {}.
    const config = data?.version ? data : null
    setSaved(config)
    setUrl(config?.service_url ?? "")
    setModel(config?.model_id ?? "")
    setAccepted(false)
    if (keyInput.current) keyInput.current.value = ""
    setLoaded(true)
  }, [])
  useEffect(() => { void load().catch(error => action(async () => { throw error })) }, [action, load])
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setNotice("")
    await action(async () => {
      const key = keyInput.current?.value ?? ""
      try {
        const { data } = await ModelconfigService.saveConfig({ body: {
          service_url: url, model_id: model, api_key: key || null,
          expected_version: saved?.version ?? null, disclosure_accepted: accepted,
        } })
        setSaved(data)
        setUrl(data.service_url)
        setModel(data.model_id)
        setNotice("配置已保存。未调用模型服务，连接和教学质量尚未验证。")
      } finally {
        if (keyInput.current) keyInput.current.value = ""
      }
    })
  }
  return <section className="space-y-4" aria-labelledby="model-config-title">
    <h2 id="model-config-title" className="text-xl font-semibold">个人模型配置</h2>
    <p>{loaded ? saved ? "已保存一套配置，Key 已加密保存且不可回读。" : "尚未配置，不会分配默认 Key。" : "正在读取配置…"}</p>
    <p>运营者能够在服务端解密 Key；Key 仅用于向你指定的模型服务认证。训练时，当前案例材料、作答和必要学习上下文会发送至该服务，不发送其他用户记录。请勿粘贴未授权公司或个人资料。</p>
    <p className="break-all">本次保存指定接收方：{url || "请填写服务地址"}</p>
    <form onSubmit={submit} className="space-y-4" autoComplete="off">
      <div><Label htmlFor="model-url">模型服务地址（公网 HTTPS）</Label>
        <Input id="model-url" type="url" required maxLength={2048} value={url} onChange={e => { setUrl(e.target.value); setAccepted(false) }} placeholder="https://api.example.com/v1" /></div>
      <div><Label htmlFor="model-id">模型 ID</Label>
        <Input id="model-id" required maxLength={255} value={model} onChange={e => setModel(e.target.value)} /></div>
      <div><Label htmlFor="model-key">API Key{saved ? "（留空保留，变更地址必须重填）" : ""}</Label>
        <Input id="model-key" ref={keyInput} type="password" autoComplete="new-password" required={!saved || url.replace(/\/+$/, "") !== saved.service_url} maxLength={4096} />
        <p>Key 仅在输入期间暂存；每次提交后清空，失败时请重新输入。</p></div>
      <label className="flex gap-2 items-start"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} required />我已知晓运营者可解密，以及上述指定服务和必要学习材料接收范围。</label>
      <Button type="submit" disabled={busy || !loaded}>保存配置</Button>
    </form>
    <Button variant="outline" disabled={busy} onClick={() => action(async () => { await load(); setNotice("已读取服务端配置，未保存输入已丢弃。") })}>刷新配置</Button>
    {saved && <Button variant="outline" disabled={busy} onClick={() => {
      if (!window.confirm("删除这套配置和 Key？成功后旧版本不能发起新调用。")) return
      void action(async () => {
        await ModelconfigService.deleteConfig({ query: { expected_version: saved.version } })
        await load()
        setNotice("配置及 Key 已删除，旧版本不能发起新调用。")
      })
    }}>删除配置及 Key</Button>}
    <p aria-live="polite">{notice}</p>
  </section>
}
