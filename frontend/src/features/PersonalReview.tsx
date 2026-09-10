import { useEffect, useRef, useState } from "react"
import {
  PersonalreviewService,
  type RoundHistory,
  type PersonalReview as Snapshot,
} from "../client"
import { Button } from "../components/ui/button"

const entries: Record<string, string> = {
  random: "随机练习",
  capability: "能力练习",
  free_topic: "自由主题",
  jd: "JD 定向",
  project: "项目训练",
  boss: "Boss 挑战",
}
const kinds: Record<string, string> = {
  original: "原始作答",
  clarification: "冻结前许可中立澄清",
  supplement: "事后复盘补答",
}
const steps: Record<string, string> = {
  materials: "材料",
  judgments: "作答",
  coach: "求助",
}
const states: Record<string, string> = {
  verified: "已验证",
  unverified: "未验证",
  needs_consolidation: "待巩固",
  required: "待补验",
  resolved: "已补足",
  pending: "复核未决",
  disputed: "仍有争议",
  completed: "已完成",
  failed: "未完成／失败",
  stopped: "已停止",
  queued: "等待处理",
  checking: "正在核对",
  running: "正在处理",
  ready: "已核对",
  delivery_unknown: "交付不明",
  delivered: "已交付",
  partial: "部分交付",
}
const label = (value: string | undefined) =>
  value ? (states[value] ?? value) : "未验证"
const time = (value: string) => new Date(value).toLocaleString()
const button = "h-auto min-h-9 max-w-full whitespace-normal"

// Text only: exported source/answer content is never interpreted as HTML.
function Detail({ title, value }: { title: string; value: unknown }) {
  return (
    <details className="min-w-0 rounded border p-2">
      <summary>{title}</summary>
      <pre className="mt-2 whitespace-pre-wrap break-all text-sm">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  )
}

function Round({ item }: { item: RoundHistory }) {
  return (
    <details
      className="min-w-0 space-y-3 rounded border p-3"
      data-run-id={item.task.id}
    >
      <summary>
        {entries[item.entry] ?? item.entry} ·{" "}
        {item.task.case?.title ?? item.task.goal} · {time(item.created_at)}
        {item.archived ? "（已归档）" : ""}
      </summary>
      <p>
        {label(item.task.status)} ·{" "}
        {item.task.current_mode === "practice"
          ? "普通练习，不增加或打断独立连续次数"
          : "独立检验，资格以冻结证据为准"}
      </p>
      <p>
        {item.task.target.capability_id} · {item.task.target.difficulty} ·{" "}
        {item.task.target.background_id}
      </p>
      <p>
        {item.submissions.completed_at
          ? `正式完整完成：${time(item.submissions.completed_at)}`
          : "尚无正式完整完成事实；已保存原答仍保留"}{" "}
        · 本轮累计修为 {item.submissions.awarded_points}
      </p>
      <p>{item.task.message}</p>
      {item.task.case && (
        <>
          <h3 className="font-semibold">原题与冻结来源</h3>
          <p>{item.task.case.task}</p>
          <Detail title="查看原材料、判断与引用" value={item.task.case} />
        </>
      )}
      <h3 className="font-semibold">原始作答与后续补答</h3>
      {item.submissions.submissions.length === 0 && (
        <p>尚无已保存的正式作答。</p>
      )}
      {item.submissions.submissions.map((s) => (
        <div className="rounded border p-2" key={s.id}>
          <p>
            {kinds[s.kind] ?? s.kind} · 第 {s.sequence} 个轮内事件 ·{" "}
            {label(s.status)}
          </p>
          {s.answers.map((a) => (
            <p key={a.judgment_id}>
              {a.judgment_id}：{JSON.stringify(a.value)}；理由：{a.reason}
            </p>
          ))}
          <p>{s.message}</p>
        </div>
      ))}
      {item.evaluation && (
        <>
          <h3 className="font-semibold">原评分与冻结资格</h3>
          <p>
            {label(item.evaluation.status)} · {item.evaluation.message} ·
            评分可靠性：{label(item.evaluation.grading_quality)}
          </p>
          <Detail title="评分、许可澄清与冻结序号" value={item.evaluation} />
        </>
      )}
      {item.review && (
        <>
          <h3 className="font-semibold">评分复核</h3>
          <p>
            {label(item.review.decision)} · {item.review.message}
          </p>
          <Detail title="复核结论和实际调用归属" value={item.review} />
        </>
      )}
      <h3 className="font-semibold">帮助与实际交付</h3>
      <p>生成不等于交付；交付不明不补出正文。后续查看不会改写原始资格。</p>
      {item.help.map((h) => (
        <div className="rounded border p-2" key={h.id}>
          <p>
            {h.kind} · {label(h.status)} · {h.message}
          </p>
          <p>提问：{h.input.question}</p>
          {h.deliveries.map((d) => (
            <div key={d.id}>
              <p>
                {label(d.status)} · 暴露事件 {d.exposure_sequence} · 回执事件{" "}
                {d.sequence} · {d.direction ?? "方向未知"}
              </p>
              {d.delivered_text && (
                <p className="whitespace-pre-wrap">{d.delivered_text}</p>
              )}
            </div>
          ))}
        </div>
      ))}
      <h3 className="font-semibold">已保存草稿与冲突</h3>
      <p>不包含尚未成功保存的本机输入；这里不会选择版本或交卷。</p>
      {item.drafts.map((d) => (
        <div key={d.help_id ?? "original"}>
          <p>
            {d.help_id ? `示范跟练 ${d.help_id}` : "原题草稿"} ·{" "}
            {d.unresolved.length
              ? `${d.unresolved.length} 份待选择冲突`
              : "无未解决冲突"}
          </p>
          {d.versions.map((v) => (
            <div className="rounded border p-2" key={v.version}>
              <p>
                {time(v.saved_at)} · {steps[v.progress.step ?? "materials"]}
                {v.version === d.current ? " · 当前选择" : ""}
              </p>
              <Detail title="完整答案与步骤（不混合版本）" value={v} />
            </div>
          ))}
        </div>
      ))}
      <Detail
        title="示范后跟练及独立保存的补答"
        value={{
          practices: item.practices,
          submissions: item.practice_submissions,
        }}
      />
      <Detail title="本轮追溯：身份、入口与实际模型版本" value={item.task} />
    </details>
  )
}

export function PersonalReview() {
  const owner = useRef(sessionStorage.getItem("token"))
  const alive = useRef(true)
  const generation = useRef(0)
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [entry, setEntry] = useState("")
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      generation.current++
    }
  }, [])
  async function load(download: boolean) {
    const attempt = ++generation.current
    const current = () =>
      alive.current &&
      attempt === generation.current &&
      owner.current === sessionStorage.getItem("token")
    setBusy(true)
    setError("")
    try {
      const { data } = download
        ? await PersonalreviewService.exportPersonalReview()
        : await PersonalreviewService.readPersonalReview()
      if (!current()) return
      setSnapshot(data)
      if (download) {
        const url = URL.createObjectURL(
          new Blob([JSON.stringify(data, null, 2)], {
            type: "application/json",
          }),
        )
        const link = document.createElement("a")
        link.href = url
        link.download = "personal-learning.json"
        link.click()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      }
    } catch {
      if (current())
        setError(
          "本次读取或导出失败，未生成下载。下方若有资料仍是上次快照；请重试，不把旧快照当作当前状态。",
        )
    } finally {
      if (current()) setBusy(false)
    }
  }
  return (
    <section
      aria-label="个人复盘与导出"
      className="min-w-0 space-y-3 rounded border p-4 break-words"
    >
      <h2 className="text-xl font-semibold">个人复盘与 JSON 导出</h2>
      <p>
        统一查看四入口的本人学习资料。原始表现、许可澄清与事后复盘分别保留；未验证不表示不会，也不代表职业资历。
      </p>
      <p>
        仅下载本人可访问的已保存资料，不含模型
        Key、认证或注销恢复凭据、他人数据、备份及未获揭示资格的答案。文件包含私有学习内容，请自行妥善保管。
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          className={button}
          disabled={busy}
          onClick={() => void load(false)}
        >
          读取本人复盘
        </Button>
        <Button
          className={button}
          disabled={busy}
          onClick={() => void load(true)}
        >
          读取并下载 JSON
        </Button>
      </div>
      {error && <p role="alert">{error}</p>}
      {snapshot && (
        <>
          <p role="status">
            本次快照：{time(snapshot.read_at)} · {snapshot.rounds.length} 轮 ·{" "}
            {snapshot.level} · 累计修为 {snapshot.total_points}
          </p>
          <label className="block">
            筛选学习入口
            <select
              className="block w-full min-w-0 rounded border p-2"
              value={entry}
              onChange={(e) => setEntry(e.target.value)}
            >
              <option value="">全部入口</option>
              {Object.entries(entries).map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          {snapshot.rounds
            .filter((r) => !entry || r.entry === entry)
            .map((r) => (
              <Round key={r.task.id} item={r} />
            ))}
          {!snapshot.rounds.length && <p>尚无可读取的学习轮次。</p>}
          <h3 className="font-semibold">路线、来源与更新历史</h3>
          <p>
            失败或上游失效不等于删除旧快照；已确认版本和新候选分别保留，项目与
            JD 是教学模拟。
          </p>
          <Detail title="自由主题路线与版本" value={snapshot.topics} />
          <Detail title="JD 原文、推断、路线与证据" value={snapshot.jds} />
          <Detail
            title="项目固定来源、读取失败与复用"
            value={snapshot.projects}
          />
          <Detail
            title="项目路线、旧版与当前确认"
            value={snapshot.project_routes}
          />
          <h3 className="font-semibold">能力、奖励与补验</h3>
          {snapshot.evidence.states.map((s, i) => (
            <p key={i}>
              {s.target.capability_id} · {s.target.difficulty} ·{" "}
              {s.target.background_id}：{label(s.status)}，连续独立通过{" "}
              {s.streak}
            </p>
          ))}
          <Detail
            title="按原答顺序的能力与争议历史"
            value={snapshot.evidence}
          />
          <Detail title="逐轮奖励与复核补差" value={snapshot.rewards} />
          <Detail
            title="原晋升与有序补验记录"
            value={{
              promotions: snapshot.promotions,
              revalidations: snapshot.revalidations,
            }}
          />
          <Detail title="归档标记（原文仍保留）" value={snapshot.archived} />
          <Detail title="永久删除标记（不恢复原文）" value={snapshot.deleted} />
        </>
      )}
    </section>
  )
}
