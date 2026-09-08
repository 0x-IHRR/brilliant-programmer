import { expect, test } from "@playwright/test"

test("password recovery revokes two devices; mobile keyboard and failure recovery", async ({ page, browser, request }) => {
  const admin = await request.post("/api/v1/login/access-token", { form: { username: process.env.FIRST_SUPERUSER!, password: process.env.FIRST_SUPERUSER_PASSWORD! } })
  expect(admin.ok()).toBe(true)
  const adminHeaders = { Authorization: `Bearer ${(await admin.json()).access_token}` }
  const invitation = await request.post("/api/v1/invitations", { headers: adminHeaders })
  const email = `reset-browser-${crypto.randomUUID()}@example.com`
  const password = "old-browser-reset-password"
  const nextPassword = "new-browser-reset-password"
  const signup = await request.post("/api/v1/users/signup", { data: { email, password, invitation_code: (await invitation.json()).code } })
  expect(signup.status()).toBe(201)
  const mailpit = process.env.MAILPIT_URL ?? "http://127.0.0.1:18025"
  async function link(kind: string) {
    const messages = (await (await request.get(`${mailpit}/api/v1/messages?limit=1000`)).json()).messages
    const message = messages.find((m: { To: { Address: string }[] }) => m.To.some(t => t.Address === email))
    const body = (await (await request.get(`${mailpit}/api/v1/message/${message.ID}`)).json()).Text as string
    return body.match(new RegExp(`http[^\\s]+#${kind}=[A-Za-z0-9_-]{43}`))![0]
  }
  await page.goto(await link("verify"))
  await page.getByLabel("邮箱", { exact: true }).fill(email)
  await page.getByLabel("密码（12–128 字符）", { exact: true }).fill(password)
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await page.getByRole("button", { name: "确认验证邮箱" }).click()
  await expect(page.getByRole("status")).toContainText("邮箱验证成功")
  const tokenA = await page.evaluate(() => sessionStorage.getItem("token"))
  const second = await browser.newContext({ baseURL: test.info().project.use.baseURL })
  const other = await second.newPage()
  await other.goto("/")
  await other.getByLabel("邮箱", { exact: true }).fill(email)
  await other.getByLabel("密码（12–128 字符）", { exact: true }).fill(password)
  await other.getByRole("button", { name: "登录", exact: true }).click()
  await expect(other.getByRole("heading", { name: "我的训练首页" })).toBeVisible()
  const tokenB = await other.evaluate(() => sessionStorage.getItem("token"))
  await page.setViewportSize({ width: 320, height: 740 })
  await page.getByRole("button", { name: "忘记密码", exact: true }).click()
  await page.getByLabel("原已验证邮箱").focus()
  await page.keyboard.type(email)
  await page.keyboard.press("Tab")
  await expect(page.getByRole("button", { name: "申请重置邮件" })).toBeFocused()
  await page.keyboard.press("Enter")
  const recovery = page.getByRole("region", { name: "密码找回" })
  await expect(recovery.getByRole("alert")).toContainText("请求已受理")
  const resetLink = await link("reset")
  await page.goto("/#reset=" + "x".repeat(43))
  await page.getByLabel("新密码（12–128 字符）").fill(nextPassword)
  await page.getByRole("button", { name: "重置密码并退出所有设备" }).click()
  await expect(recovery.getByRole("alert")).toContainText("链接无效")
  await page.goto(resetLink)
  await expect(page).not.toHaveURL(/reset=/)
  for (const token of [tokenA, tokenB]) {
    expect((await request.get("/api/v1/users/me", { headers: { Authorization: `Bearer ${token}` } })).status()).toBe(200)
  }
  await page.route("**/api/v1/password-reset/confirm", route => route.abort())
  await page.getByLabel("新密码（12–128 字符）").fill(nextPassword)
  await page.getByRole("button", { name: "重置密码并退出所有设备" }).click()
  await expect(recovery.getByRole("alert")).toContainText("操作未确认成功")
  await expect(page.getByLabel("新密码（12–128 字符）")).toHaveValue("")
  expect(await page.evaluate(() => sessionStorage.getItem("token"))).toBe(tokenA)
  await page.unroute("**/api/v1/password-reset/confirm")
  await page.getByLabel("新密码（12–128 字符）").focus()
  await page.keyboard.type(nextPassword)
  await page.keyboard.press("Tab")
  await expect(page.getByRole("button", { name: "重置密码并退出所有设备" })).toBeFocused()
  await page.screenshot({ path: "test-results/password-reset-mobile.png" })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.keyboard.press("Enter")
  await expect(page.getByRole("status")).toContainText("所有设备均需")
  await expect(page.getByRole("heading", { name: "邮箱登录" })).toBeVisible()
  expect(await page.evaluate(() => sessionStorage.getItem("token"))).toBeNull()
  for (const token of [tokenA, tokenB]) {
    expect((await request.get("/api/v1/users/me", { headers: { Authorization: `Bearer ${token}` } })).status()).toBe(401)
  }
  // This request is outside the App action wrapper; the shared client still forces relogin.
  await other.getByRole("button", { name: "重新读取能力目录" }).click()
  await expect(other.getByRole("status")).toContainText("请重新登录")
  await expect(other.getByRole("heading", { name: "邮箱登录" })).toBeVisible()
  expect(await other.evaluate(() => sessionStorage.getItem("token"))).toBeNull()
  await page.getByLabel("邮箱", { exact: true }).fill(email)
  await page.getByLabel("密码（12–128 字符）", { exact: true }).fill(nextPassword)
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page.getByRole("heading", { name: "我的训练首页" })).toBeVisible()
  await page.goto(resetLink)
  await page.getByLabel("新密码（12–128 字符）").fill("replay-browser-reset-password")
  await page.getByRole("button", { name: "重置密码并退出所有设备" }).click()
  await expect(recovery.getByRole("alert")).toContainText("链接无效")
  await second.close()
  await request.post("/api/v1/login/logout", { headers: adminHeaders })
})


for (const delayedPath of ["/api/v1/capabilities/catalog", "/api/v1/model-config", "/api/v1/training/tasks"]) {
  test(`late 401 from ${delayedPath} preserves replacement session`, async ({ page }) => {
    // Real UI and generated SDK; controlled responses isolate the response-order race.
    const users = {
      A: { id: crypto.randomUUID(), email: "a@example.com", email_verified: true, is_active: true, is_superuser: false, level: "小白程序员" },
      B: { id: crypto.randomUUID(), email: "b@example.com", email_verified: true, is_active: true, is_superuser: false, level: "小白程序员" },
    }
    let release!: () => void
    const delayed = new Promise<void>(resolve => { release = resolve })
    let started!: () => void
    const pending = new Promise<void>(resolve => { started = resolve })
    await page.route("**/api/v1/**", async route => {
      const req = route.request()
      const path = new URL(req.url()).pathname
      const account = req.headers().authorization === "Bearer session-B" ? "B" : "A"
      if (path === "/api/v1/login/access-token") {
        const name = new URLSearchParams(req.postData()!).get("username") === users.B.email ? "B" : "A"
        await route.fulfill({ json: { access_token: `session-${name}`, token_type: "bearer" } })
      } else if (path === "/api/v1/users/me") {
        await route.fulfill({ json: users[account] })
      } else if (path === "/api/v1/login/logout") {
        await route.fulfill({ json: { message: "已退出当前设备" } })
      } else if (path === delayedPath && account === "A") {
        started()
        await delayed
        await route.fulfill({ status: 401, json: { detail: "请重新登录" } })
      } else if (path === "/api/v1/capabilities/catalog") {
        await route.fulfill({ json: { version: "test", quality: "test", domains: [], backgrounds: [], difficulty_criteria: { 基础: "test" } } })
      } else if (path === "/api/v1/model-config") {
        await route.fulfill({ json: null })
      } else if (path === "/api/v1/training/tasks") {
        await route.fulfill({ json: [] })
      } else if (path === "/api/v1/training/access") {
        await route.fulfill({ status: 401, json: { detail: "请重新登录" } })
      } else {
        throw new Error(`Unexpected test request: ${path}`)
      }
    })
    async function signIn(email: string) {
      await page.getByLabel("邮箱", { exact: true }).fill(email)
      await page.getByLabel("密码（12–128 字符）", { exact: true }).fill("synthetic-password")
      await page.getByRole("button", { name: "登录", exact: true }).click()
      await expect(page.getByRole("heading", { name: "我的训练首页" })).toBeVisible()
    }
    await page.goto("/")
    await signIn(users.A.email)
    await pending
    await page.getByRole("button", { name: "退出登录" }).click()
    await signIn(users.B.email)
    const response = page.waitForResponse(r => new URL(r.url()).pathname === delayedPath && r.status() === 401)
    release()
    await (await response).finished()
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
    expect(await page.evaluate(() => sessionStorage.getItem("token"))).toBe("session-B")
    await expect(page.getByRole("heading", { name: "我的训练首页" })).toBeVisible()
    await expect(page.getByRole("status")).not.toContainText("请重新登录")
    // B's own authenticated failure still revokes B, including through App.action.
    await page.getByRole("button", { name: "检查训练准入" }).click()
    await expect(page.getByRole("status")).toContainText("请重新登录")
    await expect(page.getByRole("heading", { name: "邮箱登录" })).toBeVisible()
    expect(await page.evaluate(() => sessionStorage.getItem("token"))).toBeNull()
  })
}
