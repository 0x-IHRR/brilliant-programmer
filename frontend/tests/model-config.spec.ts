import { expect, test } from "@playwright/test"

test("personal config saves without provider requests, survives reload and deletes", async ({ page, request }) => {
  const admin = await request.post("/api/v1/login/access-token", { form: {
    username: process.env.FIRST_SUPERUSER!, password: process.env.FIRST_SUPERUSER_PASSWORD!,
  } })
  const adminHeaders = { Authorization: `Bearer ${(await admin.json()).access_token}` }
  const invitation = await request.post("/api/v1/invitations", { headers: adminHeaders })
  const email = `model-browser-${crypto.randomUUID()}@example.com`
  const password = "fake-browser-password-only"
  const signup = await request.post("/api/v1/users/signup", { data: { email, password, invitation_code: (await invitation.json()).code } })
  expect(signup.status()).toBe(201)
  await page.goto("/")
  await page.getByLabel("邮箱", { exact: true }).fill(email)
  await page.getByLabel("密码（12–128 字符）").fill(password)
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page.getByRole("heading", { name: "我的训练首页" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "个人模型配置" })).toHaveCount(0)
  const mailpit = process.env.MAILPIT_URL ?? "http://127.0.0.1:18025"
  const messages = (await (await request.get(`${mailpit}/api/v1/messages?limit=1000`)).json()).messages
  const message = messages.find((m: { To: { Address: string }[] }) => m.To.some(t => t.Address === email))
  const body = (await (await request.get(`${mailpit}/api/v1/message/${message.ID}`)).json()).Text as string
  await page.goto(body.match(/http[^\s]+#verify=[A-Za-z0-9_-]{43}/)![0])
  await page.getByRole("button", { name: "确认验证邮箱" }).click()
  await expect(page.getByText("尚未配置，不会分配默认 Key。")).toBeVisible()
  const providerRequests: string[] = []
  page.on("request", r => { if (r.url().includes("api.example.com")) providerRequests.push(r.url()) })
  await page.getByLabel("模型服务地址（公网 HTTPS）").fill("https://api.example.com/v1")
  await page.getByLabel("模型 ID", { exact: true }).fill("synthetic-model")
  const fakeKey = "browser-fake-key-no-provider"
  await page.getByLabel("API Key", { exact: true }).fill(fakeKey)
  await page.getByRole("checkbox").check()
  await page.getByRole("button", { name: "保存配置", exact: true }).click()
  await expect(page.getByText("配置已保存。未调用模型服务，连接和教学质量尚未验证。")).toBeVisible()
  await expect(page.locator("#model-key")).toHaveValue("")
  expect(await page.evaluate(k => JSON.stringify({ ...localStorage, ...sessionStorage }).includes(k), fakeKey)).toBe(false)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => sessionStorage.getItem("token"))}` }
  const saved = await request.get("/api/v1/model-config", { headers })
  expect(await saved.text()).not.toContain(fakeKey)
  const oldVersion = (await saved.json()).version
  // UI contract uses controlled API replies. The Python suite exercises real TLS/HTTP.
  await expect(page.getByRole("button", { name: "测试连接", exact: true })).toBeDisabled()
  await expect(page.getByText("测试连接、获取模型 ID 及自动重试都可能收费。", { exact: false })).toBeVisible()
  const probes: { service_url: string; model_id: string; api_key: string }[] = []
  let release: (() => void) | undefined
  let delay = false
  let fail = false
  await page.route("**/api/v1/model-config/probe/*", async route => {
    probes.push(route.request().postDataJSON())
    if (delay) await new Promise<void>(resolve => { release = resolve })
    await route.fulfill({ json: {
      ok: !fail, code: fail ? "service_rejected" : "ok",
      message: fail ? "服务不支持模型列表，可继续手填。" : "受控模型列表已返回，选择才回填。",
      models: fail ? [] : ["actual-service-model", "<script>unsafe</script>"],
      attempts: [{ number: 1, code: fail ? "service_rejected" : "ok", prompt_tokens: null, completion_tokens: null, total_tokens: null }],
    } })
  })
  await page.locator("#model-id").fill("")
  await page.locator("#model-key").fill("fake-draft-key")
  await expect(page.getByRole("button", { name: "测试连接", exact: true })).toBeDisabled()
  await page.getByRole("button", { name: "获取模型 ID", exact: true }).click()
  await expect(page.locator("#returned-model")).toBeVisible()
  await expect(page.locator("#model-id")).toHaveValue("")
  expect(probes[0]).toMatchObject({ model_id: "", api_key: "fake-draft-key" })
  await expect(page.getByText("第 1 次：ok；输入 未知，输出 未知，合计 未知。")).toBeVisible()
  await expect(page.getByText("实际费用请查看模型服务商账单。", { exact: false })).toBeVisible()
  expect(await page.locator("script").filter({ hasText: "unsafe" }).count()).toBe(0)
  await page.locator("#returned-model").selectOption("actual-service-model")
  await expect(page.locator("#model-id")).toHaveValue("actual-service-model")
  expect((await (await request.get("/api/v1/model-config", { headers })).json()).version).toBe(oldVersion)
  // Key edits invalidate in-flight results, and the late completion cannot erase the new Key.
  delay = true
  await page.locator("#model-key").fill("fake-old-draft-key")
  await page.getByRole("button", { name: "获取模型 ID", exact: true }).click()
  await expect.poll(() => Boolean(release)).toBe(true)
  await page.locator("#model-key").fill("fake-new-draft-key")
  release!()
  await expect(page.getByRole("button", { name: "获取模型 ID", exact: true })).toBeEnabled()
  await expect(page.locator("#returned-model")).toHaveCount(0)
  await expect(page.locator("#model-key")).toHaveValue("fake-new-draft-key")
  // Ordinary edits still discard the submitted Key when the delayed probe finishes.
  release = undefined
  await page.getByRole("button", { name: "获取模型 ID", exact: true }).click()
  await expect.poll(() => Boolean(release)).toBe(true)
  await page.locator("#model-id").fill("changed-during-probe")
  release!()
  await expect(page.getByRole("button", { name: "保存配置", exact: true })).toBeEnabled()
  await expect(page.locator("#model-key")).toHaveValue("")
  delay = false
  fail = true
  await page.locator("#model-key").fill("fake-draft-key")
  await page.getByRole("button", { name: "获取模型 ID", exact: true }).click()
  await expect(page.getByText("服务不支持模型列表，可继续手填。")).toBeVisible()
  await page.locator("#model-id").fill("manual-after-failure")
  await page.setViewportSize({ width: 320, height: 844 })
  await page.screenshot({ path: "test-results/model-connection-mobile.png", fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect((await (await request.get("/api/v1/model-config", { headers })).json()).version).toBe(oldVersion)
  await page.unroute("**/api/v1/model-config/probe/*")
  // The same Key-specific cleanup rule applies to failed saves.
  let releaseSave: (() => void) | undefined
  await page.route("**/api/v1/model-config", async route => {
    if (route.request().method() !== "PUT") return route.continue()
    await new Promise<void>(resolve => { releaseSave = resolve })
    await route.abort()
  })
  for (const editKey of [false, true]) {
    releaseSave = undefined
    await page.locator("#model-key").fill("fake-submitted-save-key")
    await page.getByRole("button", { name: "保存配置", exact: true }).click()
    await expect.poll(() => Boolean(releaseSave)).toBe(true)
    await page.locator(editKey ? "#model-key" : "#model-id").fill(editKey ? "fake-new-save-key" : "changed-during-save")
    releaseSave!()
    await expect(page.getByRole("button", { name: "保存配置", exact: true })).toBeEnabled()
    await expect(page.locator("#model-key")).toHaveValue(editKey ? "fake-new-save-key" : "")
  }
  await page.unroute("**/api/v1/model-config")
  await page.reload()
  await expect(page.getByLabel("模型 ID", { exact: true })).toHaveValue("synthetic-model")
  await expect(page.locator("#model-key")).toHaveValue("")
  await page.getByLabel("模型 ID", { exact: true }).fill("synthetic-replacement")
  await page.locator("#model-key").fill("browser-replacement-fake-key")
  await page.getByRole("checkbox").check()
  // A failed save clears Key but preserves ordinary inputs and actual saved state.
  await page.route("**/api/v1/model-config", route => route.request().method() === "PUT" ? route.abort() : route.continue())
  await page.getByRole("button", { name: "保存配置", exact: true }).click()
  await expect(page.getByRole("status")).toContainText("操作未确认成功")
  await expect(page.locator("#model-key")).toHaveValue("")
  await expect(page.getByLabel("模型 ID", { exact: true })).toHaveValue("synthetic-replacement")
  expect((await (await request.get("/api/v1/model-config", { headers })).json()).version).toBe(oldVersion)
  await page.unroute("**/api/v1/model-config")
  await page.locator("#model-key").fill("browser-replacement-fake-key")
  await page.getByRole("button", { name: "保存配置", exact: true }).click()
  await expect(page.getByText("配置已保存。未调用模型服务，连接和教学质量尚未验证。")).toBeVisible()
  expect((await (await request.get("/api/v1/model-config", { headers })).json()).version).not.toBe(oldVersion)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: "test-results/model-config-mobile.png", fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  page.once("dialog", dialog => dialog.accept())
  await page.getByRole("button", { name: "删除配置及 Key" }).click()
  await expect(page.getByText("配置及 Key 已删除，旧版本不能发起新调用。")).toBeVisible()
  await page.reload()
  await expect(page.getByText("尚未配置，不会分配默认 Key。")).toBeVisible()
  expect(providerRequests).toEqual([])
  await page.getByRole("button", { name: "退出登录" }).click()
  await request.post("/api/v1/login/logout", { headers: adminHeaders })
})
