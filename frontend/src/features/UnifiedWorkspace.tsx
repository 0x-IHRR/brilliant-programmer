import { type ReactNode, useEffect, useRef, useState } from "react"
import { type ContinuePublic, TrainingService } from "../client"
import { Button } from "../components/ui/button"
import { Boss } from "./Boss"
import { CapabilityMap } from "./CapabilityMap"
import { FreeTopic } from "./FreeTopic"
import { JDRoute } from "./JDRoute"
import { PersonalReview } from "./PersonalReview"
import { Project } from "./Project"
import { Records } from "./Records"
import { Training } from "./Training"

type Area =
  | "home"
  | "routes"
  | "training"
  | "capabilities"
  | "review"
  | "account"

const areas: { id: Area; label: string }[] = [
  { id: "home", label: "首页" },
  { id: "routes", label: "路线与项目" },
  { id: "training", label: "练习工作台" },
  { id: "capabilities", label: "能力与突破" },
  { id: "review", label: "复盘记录" },
  { id: "account", label: "账号与模型" },
]
const buttonClass = "h-auto min-h-9 max-w-full whitespace-normal"
const entryTargetClass = "focus-visible:outline-2 focus-visible:outline-offset-2"

function initialArea(): Area {
  const query = new URLSearchParams(location.search)
  if (query.has("training_run")) return "training"
  if (query.has("capability") || query.has("difficulty")) return "capabilities"
  if (query.has("jd") || query.has("project_run") || query.has("project_route"))
    return "routes"
  if (query.has("deletion_receipt")) return "review"
  return "home"
}

function Prologue({ userId }: { userId: string }) {
  const key = `prologue-seen:${userId}`
  const [available, setAvailable] = useState(
    () => localStorage.getItem(key) !== "1",
  )
  const dialog = useRef<HTMLDialogElement>(null)
  const skip = useRef<HTMLButtonElement>(null)
  function close() {
    dialog.current?.close()
  }
  function open() {
    localStorage.setItem(key, "1")
    setAvailable(false)
    dialog.current?.showModal()
    window.setTimeout(close, 15_000)
    window.setTimeout(() => skip.current?.focus(), 0)
  }
  if (!available && !dialog.current?.open) return null
  return (
    <>
      {available && (
        <Button className={buttonClass} variant="outline" onClick={open}>
          观看重回巅峰序章
        </Button>
      )}
      <dialog
        ref={dialog}
        aria-labelledby="prologue-title"
        onCancel={close}
        className="m-auto max-w-lg space-y-4 rounded border bg-background p-5 text-foreground backdrop:bg-black/40"
      >
        <h3 id="prologue-title" className="text-xl font-semibold">重回巅峰</h3>
        <p>
          故事里的能力暂时沉寂；你已经完成的练习、证据、修为和等级始终保留。
        </p>
        <p>从一次真实判断继续：看任务、查证据、作判断、看反馈、记录结果。</p>
        <p className="motion-reduce:block">
          减少动态效果时，本序章始终使用这组静态文字。
        </p>
        <Button className={buttonClass} ref={skip} onClick={close}>
          跳过并进入首页
        </Button>
      </dialog>
    </>
  )
}

function Home({
  userId,
  go,
  onContinue,
}: {
  userId: string
  go: (area: Area, target?: string) => void
  onContinue: (id: string) => void
}) {
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading")
  const [round, setRound] = useState<ContinuePublic | null>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    setState("loading")
    void TrainingService.continueTask()
      .then(({ data }) => {
        if (active) {
          setRound(data)
          setState("ready")
        }
      })
      .catch(() => {
        if (active) setState("failed")
      })
    return () => {
      active = false
    }
  }, [attempt])
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">今天从一个真实行动继续</h2>
      {state === "loading" && <p aria-live="polite">正在读取最近练习…</p>}
      {state === "failed" && (
        <div role="alert" className="space-y-2">
          <p>最近练习读取失败；没有自动开始随机练习，已有记录不变。</p>
          <Button
            className={buttonClass}
            variant="outline"
            onClick={() => setAttempt((n) => n + 1)}
          >
            重新读取首页行动
          </Button>
        </div>
      )}
      {state === "ready" &&
        (round ? (
          <div className="space-y-2 rounded border p-4">
            <p>最近未完成：{round.title}</p>
            <p>最近活动：{new Date(round.active_at).toLocaleString()}</p>
            <Button className={buttonClass} onClick={() => onContinue(round.run_id)}>
              继续最近未完成练习
            </Button>
          </div>
        ) : (
          <div className="space-y-2 rounded border p-4">
            <p>尚无未完成练习。</p>
            <Button className={buttonClass} onClick={() => go("training")}>
              从随机练习开始
            </Button>
          </div>
        ))}
      <section aria-label="四种训练入口" className="grid gap-3 sm:grid-cols-2">
        <Button
          className={buttonClass}
          variant="outline"
          onClick={() => go("training", "random-entry")}
        >
          随机练习
        </Button>
        <Button
          className={buttonClass}
          variant="outline"
          onClick={() => go("routes", "topic-entry")}
        >
          自由主题
        </Button>
        <Button
          className={buttonClass}
          variant="outline"
          onClick={() => go("routes", "jd-entry")}
        >
          JD 定向
        </Button>
        <Button
          className={buttonClass}
          variant="outline"
          onClick={() => go("routes", "project-entry")}
        >
          公开 GitHub 项目
        </Button>
      </section>
      <Prologue userId={userId} />
    </div>
  )
}

export function UnifiedWorkspace({
  userId,
  onLevel,
  account,
}: {
  userId: string
  onLevel: (level: string) => void
  account: ReactNode
}) {
  const [area, setArea] = useState<Area>(initialArea)
  const [requestedRun, setRequestedRun] = useState("")
  const focusFrame = useRef(0)
  const regions = useRef<Record<Area, HTMLElement | null>>({
    home: null,
    routes: null,
    training: null,
    capabilities: null,
    review: null,
    account: null,
  })
  useEffect(() => () => cancelAnimationFrame(focusFrame.current), [])
  function go(next: Area, target?: string) {
    setArea(next)
    cancelAnimationFrame(focusFrame.current)
    focusFrame.current = requestAnimationFrame(() => {
      const region = (target ? document.getElementById(target) : null) ?? regions.current[next]
      region?.focus({ preventScroll: true })
      region?.scrollIntoView()
    })
  }
  function continueRun(id: string) {
    setRequestedRun(id)
    go("training")
  }
  return (
    <div className="space-y-6">
      <nav
        aria-label="主要区域"
        className="sticky top-0 z-10 flex flex-wrap gap-2 border-y bg-background py-3"
      >
        {areas.map((item) => (
          <Button
            className={buttonClass}
            key={item.id}
            variant={area === item.id ? "default" : "outline"}
            aria-current={area === item.id ? "page" : undefined}
            onClick={() => go(item.id)}
          >
            {item.label}
          </Button>
        ))}
      </nav>
      {areas.map((item) => (
        <section
          key={item.id}
          ref={(node) => {
            regions.current[item.id] = node
          }}
          tabIndex={-1}
          aria-label={item.label}
          className="min-w-0 space-y-6 border-b pb-8 focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {item.id === "home" && (
            <Home userId={userId} go={go} onContinue={continueRun} />
          )}
          {item.id === "routes" && (
            <>
              <div id="topic-entry" role="group" aria-label="自由主题入口" className={entryTargetClass} tabIndex={-1}><FreeTopic /></div>
              <div id="jd-entry" role="group" aria-label="JD 定向入口" className={entryTargetClass} tabIndex={-1}><JDRoute /></div>
              <div id="project-entry" role="group" aria-label="公开 GitHub 项目入口" className={entryTargetClass} tabIndex={-1}><Project /></div>
            </>
          )}
          {item.id === "training" && (
            <>
              <Boss />
              <div id="random-entry" role="group" aria-label="随机练习入口" className={entryTargetClass} tabIndex={-1}><Training onLevel={onLevel} openRunId={requestedRun} /></div>
            </>
          )}
          {item.id === "capabilities" && <CapabilityMap />}
          {item.id === "review" && (
            <>
              <PersonalReview />
              <Records />
            </>
          )}
          {item.id === "account" && account}
        </section>
      ))}
    </div>
  )
}
