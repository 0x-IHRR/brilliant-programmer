import type { CollectionView, PublicCase } from "../client"
import { Button } from "../components/ui/button"

export function DraftVersions({ collection, caseData, busy, expanded, choose, remove, read }: { collection: CollectionView | null; caseData: PublicCase; busy: boolean; expanded: boolean; choose: (id: string) => Promise<void>; remove: () => Promise<void>; read: () => Promise<void> }) {
  const cls = "h-auto min-h-9 max-w-full whitespace-normal"
  return <details className="min-w-0 space-y-2" open={expanded || Boolean(collection?.unresolved.length)}>
    <summary>草稿版本与删除</summary>
    <p>冲突版本全部保留。请选择完整的一份答案和步骤；选择不交卷、不合并，也不删除其他版本。</p>
    <Button className={cls} variant="outline" disabled={busy} onClick={() => void read()}>读取全部草稿版本</Button>
    {collection && !collection.current && <p>服务端当前没有已选草稿；本机未保存输入不代表已恢复。保留版本仍可明确选择。</p>}
    {collection?.versions.map((item, index) => <article aria-label={`草稿版本 ${index + 1}`} key={item.version} className="border p-2 space-y-1 break-words">
      <p>版本 {index + 1} · {item.version === collection.current ? "当前版本" : "保留版本"} · {collection.unresolved.includes(item.version) ? "待选择" : "历史/已选择"}</p>
      <p>步骤：{({ materials: "材料", judgments: "作答", coach: "求助" })[item.progress.step ?? "materials"]}；保存时间：{item.saved_at}；原答关联：{item.progress.based_on_submission_id ?? "尚无正式提交"}</p>
      {caseData.judgments.map(j => { const a = item.progress.answers?.find(x => x.judgment_id === j.id); const v = a?.value; return <p key={j.id} className="whitespace-pre-wrap">{j.prompt}：{Array.isArray(v) ? v.map(n => j.options[n] ?? "未选").join(" → ") : typeof v === "number" ? j.options[v] : v || "尚未作答"}；理由：{a?.reason || "尚未填写"}</p> })}
      <Button className={cls} disabled={busy} onClick={() => void choose(item.version)}>选择版本 {index + 1}</Button>
    </article>)}
    {collection?.current && <Button className={cls} variant="outline" disabled={busy} onClick={() => void remove()}>删除指定当前草稿</Button>}
  </details>
}
