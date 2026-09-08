import { useEffect, useRef, useState } from "react"
import {
  ConceptsService,
  type Answer,
  type HelpCreate,
  type HelpPublication,
  type HelpPublic,
  type ModelConfigPublic,
} from "../client"
import { Button } from "../components/ui/button"

export function ConceptCoach({
  runId,
  answers,
  config,
}: {
  runId: string
  answers: Answer[]
  config: ModelConfigPublic | null
}) {
  const [items, setItems] = useState<HelpPublic[]>([])
  const [question, setQuestion] = useState("")
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [publication, setPublication] = useState<HelpPublication | null>(null)
  const [receiptFailed, setReceiptFailed] = useState(false)
  const alive = useRef(true)
  const ownerSession = useRef(sessionStorage.getItem("token"))
  const current = () =>
    alive.current && sessionStorage.getItem("token") === ownerSession.current
  const pending = useRef<HelpCreate | null>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const working = items.some((item) =>
    ["checking", "stopping"].includes(item.status),
  )
  const cls = "h-auto min-h-9 max-w-full whitespace-normal"
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  useEffect(() => {
    setAccepted(false)
  }, [config?.version])
  function update(data: HelpPublic | undefined) {
    if (!current() || !data?.id || data.run_id !== runId) return
    setItems((old) =>
      [...old.filter((item) => item.id !== data.id), data].sort(
        (a, b) => a.created_sequence - b.created_sequence,
      ),
    )
  }
  async function read() {
    try {
      const { data } = await ConceptsService.listHelp({
        path: { run_id: runId },
      })
      if (current()) {
        setItems(
          Array.isArray(data)
            ? data.filter((item) => item?.id && item.run_id === runId)
            : [],
        )
        setError("")
      }
    } catch {
      if (current()) setError("帮助记录读取失败，已显示内容保留；请重新读取。")
    }
  }
  useEffect(() => {
    void read()
  }, [runId])
  useEffect(() => {
    if (!working) return
    const timer = window.setInterval(() => {
      void read()
    }, 1000)
    return () => window.clearInterval(timer)
  }, [working, runId])
  useEffect(() => {
    if (!publication?.delivery_id) return
    const session = sessionStorage.getItem("token")
    let cancelled = false,
      second = 0
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => {
        if (
          cancelled ||
          !current() ||
          !contentRef.current?.isConnected ||
          !contentRef.current.getClientRects().length ||
          document.visibilityState !== "visible" ||
          sessionStorage.getItem("token") !== session
        )
          return
        void ConceptsService.confirmRendering({
          path: {
            run_id: runId,
            help_id: publication.help_id,
            delivery_id: publication.delivery_id,
          },
          body: { token: publication.receipt_token },
        })
          .then(({ data }) => {
            if (!cancelled && current()) {
              update(data)
              setReceiptFailed(false)
            }
          })
          .catch(() => {
            if (!cancelled && current()) setReceiptFailed(true)
          })
      })
    })
    return () => {
      cancelled = true
      cancelAnimationFrame(first)
      cancelAnimationFrame(second)
    }
  }, [publication, runId])
  async function act(operation: () => Promise<void>) {
    setBusy(true)
    setError("")
    try {
      await operation()
    } catch (error) {
      if (current()) {
        const detail = (error as { response?: { data?: { detail?: unknown } } })
          .response?.data?.detail
        setError(
          typeof detail === "string"
            ? detail
            : "帮助操作未确认成功；输入保留，请重读状态。",
        )
      }
    } finally {
      if (current()) setBusy(false)
    }
  }
  async function request(parent?: HelpPublic) {
    if (!config || !accepted) return
    const body: HelpCreate = {
      request_id: "",
      expected_config_version: config.version,
      disclosure_accepted: true,
      parent_id: parent?.id ?? null,
      input: {
        question: parent?.input.question ?? question,
        depth: parent ? "deep" : "basic",
        answers,
      },
    }
    const old = pending.current
    body.request_id =
      old && JSON.stringify({ ...old, request_id: "" }) === JSON.stringify(body)
        ? old.request_id
        : crypto.randomUUID()
    pending.current = body
    const { data } = await ConceptsService.requestHelp({
      path: { run_id: runId },
      body,
    })
    update(data)
  }
  return (
    <section
      aria-label="概念教练"
      className="min-w-0 space-y-3 border-t pt-3 break-words"
    >
      <h4 className="font-semibold">卡住了？先弄懂一个概念</h4>
      <p>
        无需先作答。默认白话说明、一个小例子和当前材料的对应关系；更深原理由你主动展开。
      </p>
      <label className="block">
        想弄懂的概念或材料
        <textarea
          className="block w-full min-w-0 rounded border p-2 focus-visible:outline-2"
          maxLength={6000}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
      </label>
      {config ? (
        <>
          <p className="break-all">
            帮助接收方：{config.service_url} · {config.model_id}
          </p>
          <label className="flex gap-2 items-start">
            <input
              type="checkbox"
              checked={accepted}
              onChange={(e) => setAccepted(e.target.checked)}
            />
            <span>
              允许发送当前案例、当前作答、求助及必要的本轮帮助记录，生成并检查说明；重试可能计费。不要粘贴秘密或未授权资料。
            </span>
          </label>
        </>
      ) : (
        <p>请重新读取已保存的模型配置后求助；已有帮助记录保留。</p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          className={cls}
          disabled={busy || working || !accepted || !config || !question.trim()}
          onClick={() => act(() => request())}
        >
          白话解释
        </Button>
        <Button
          className={cls}
          variant="outline"
          disabled={busy}
          onClick={() => read()}
        >
          重新读取帮助
        </Button>
      </div>
      {error && <p role="alert">{error}</p>}
      {publication?.delivery_id && (
        <div
          ref={contentRef}
          className="space-y-2 border p-3"
          aria-label="当前概念说明"
        >
          <p className="whitespace-pre-wrap">
            白话：{publication.content.plain}
          </p>
          <p className="whitespace-pre-wrap">
            小例子：{publication.content.example}
          </p>
          <p className="whitespace-pre-wrap">
            对应材料：{publication.content.relation}
          </p>
          {publication.content.principle && (
            <p className="whitespace-pre-wrap">
              进一步原理：{publication.content.principle}
            </p>
          )}
          <p>模型内容检查不等于人工核验，也不证明你已理解。</p>
        </div>
      )}
      {receiptFailed && (
        <p role="alert">
          页面已显示内容，但回执未确认。服务端保留原交付尝试为待核对；重新查看可再次确认，不会抹除原先顺序。
        </p>
      )}
      {items.map((item) => (
        <article key={item.id} className="space-y-2 border p-2">
          <p>
            {item.input.question} ·{" "}
            {item.input.depth === "deep" ? "深入原理" : "基础说明"}
          </p>
          <p role="status">{item.message}</p>
          {item.direction && (
            <p>
              内容检查：
              {
                (
                  {
                    neutral: "中性概念",
                    directional: "含本题方向",
                    uncertain: "方向或事实仍不确定",
                  } as Record<string, string>
                )[item.direction]
              }
              （模型推断）
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {["checking", "stopping"].includes(item.status) && (
              <Button
                className={cls}
                variant="outline"
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    const { data } = await ConceptsService.stopHelp({
                      path: { run_id: runId, help_id: item.id },
                    })
                    update(data)
                  })
                }
              >
                停止这次帮助
              </Button>
            )}
            {item.can_retry && (
              <Button
                className={cls}
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    const { data } = await ConceptsService.retryHelp({
                      path: { run_id: runId, help_id: item.id },
                    })
                    update(data)
                  })
                }
              >
                重试这次帮助（可能计费）
              </Button>
            )}
            {item.status === "ready" && (
              <Button
                className={cls}
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    const { data } = await ConceptsService.publishHelp({
                      path: { run_id: runId, help_id: item.id },
                    })
                    if (
                      current() &&
                      data?.help_id === item.id &&
                      data.delivery_id
                    ) {
                      setPublication(data)
                      setReceiptFailed(false)
                    }
                    await read()
                  })
                }
              >
                查看说明
              </Button>
            )}
            {item.input.depth === "basic" &&
              item.deliveries.some((d) => d.status === "delivered") && (
                <Button
                  className={cls}
                  variant="outline"
                  disabled={busy || working || !accepted || !config}
                  onClick={() => act(() => request(item))}
                >
                  展开更深原理
                </Button>
              )}
          </div>
          <details>
            <summary>交付事实与历史说明</summary>
            {item.deliveries.length === 0 && <p>尚未交付。</p>}
            {item.deliveries.map((event) => (
              <div key={event.id}>
                <p>
                  事件 {event.sequence} · 原交付尝试 {event.exposure_sequence} ·{" "}
                  {event.status === "delivered"
                    ? "页面完整渲染回执已保存，不代表人已阅读或理解"
                    : "交付待核对，不能确定是否看到；原事实保留"}
                </p>
                {event.delivered_text && (
                  <p className="whitespace-pre-wrap">{event.delivered_text}</p>
                )}
              </div>
            ))}
          </details>
          <details>
            <summary>调用与用量（{item.attempts.length} 次）</summary>
            {item.attempts.map((a) => (
              <p key={a.number}>
                第{a.number}次 · {a.code} · 输入{a.prompt_tokens ?? "未知"} /
                输出{a.completion_tokens ?? "未知"} / 总token
                {a.total_tokens ?? "未知"}
              </p>
            ))}
          </details>
        </article>
      ))}
    </section>
  )
}
