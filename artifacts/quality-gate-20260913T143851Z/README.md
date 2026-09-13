# #40 provisional model quality run

This artifact records one authorized Zhipu Coding Plan run against the five draft benchmark batches for #35–#39.

- Model: `glm-5.3-flash`
- Endpoint: `https://open.bigmodel.cn/api/coding/paas/v4/chat/completions`
- Temperature: `0`
- Seed: omitted
- System prompt: `quality-gate-v1.0`
- Scope: 84 cases, 168 candidate labels
- Generated: 2026-09-13T14:45:35Z
- Requests: 168 successful HTTP responses; no request failures
- Usage: 163,515 total tokens (93,828 prompt; 69,687 completion)

## Result

The model matched the AI-draft rubric labels for 103/168 labels (61.31%). There were 65 `uncertain` predictions and zero security false permits under the provisional rubric. Domain-level results and the full per-label responses are in `report.json` and `raw.jsonl`.

This is **provisional** evidence only. The expected labels are AI drafts marked `pending_human_review`; they are not human truth. This artifact does not satisfy the human-review requirements of #35–#39, does not prove real-world model quality, and does not close #40.
