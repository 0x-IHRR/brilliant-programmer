# #40 provisional model quality run

This artifact records the corrected authorized Zhipu Coding Plan run against the five draft benchmark batches for #35–#39.

- Model: `glm-5.3-flash`
- Endpoint: `https://open.bigmodel.cn/api/coding/paas/v4/chat/completions`
- Temperature: `0`
- Seed: omitted
- Thinking: `{"type":"disabled"}`
- System prompt: `quality-gate-v1.0`
- Scope: 84 cases, 168 candidate labels
- Generated: 2026-09-13T14:54:30Z
- Requests: 168 successful HTTP responses; no request failures
- Usage: 108,481 total tokens (93,828 prompt; 14,653 completion)

## Result

Strict structured-output comparison matched the AI-draft rubric labels for 167/168 labels (99.40%). Semantic recovery of the one malformed JSON response matched 168/168 (100%), with one structured-output failure. Every domain met the 90% semantic threshold; security false permits were zero.

This is **provisional** evidence only. The expected labels are AI drafts marked `pending_human_review`; they are not human truth. This artifact does not satisfy the human-review requirements of #35–#39, does not prove real-world model quality, and does not close #40. Provider `reasoning_content` was excluded from persisted artifacts.
