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
