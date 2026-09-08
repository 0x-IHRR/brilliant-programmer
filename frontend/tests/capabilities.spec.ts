import { expect, test } from "@playwright/test"

test("verified catalog, keyboard prerequisites, mobile zoom and retry", async ({ page, request }) => {
  const admin = await request.post("/api/v1/login/access-token", { form: {
    username: process.env.FIRST_SUPERUSER!, password: process.env.FIRST_SUPERUSER_PASSWORD!,
  } })
  const adminHeaders = { Authorization: `Bearer ${(await admin.json()).access_token}` }
  const invitation = await request.post("/api/v1/invitations", { headers: adminHeaders })
  const email = `map-${crypto.randomUUID().slice(0, 8)}@example.com`
  const password = "map-browser-test-password"
  expect((await request.post("/api/v1/users/signup", { data: { email, password, invitation_code: (await invitation.json()).code } })).status()).toBe(201)
  const login = await request.post("/api/v1/login/access-token", { form: { username: email, password } })
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` }
  const mailpit = process.env.MAILPIT_URL!
  const messages = (await (await request.get(`${mailpit}/api/v1/messages?limit=1000`)).json()).messages
  const message = messages.find((m: { To: { Address: string }[] }) => m.To.some(t => t.Address === email))
  const body = (await (await request.get(`${mailpit}/api/v1/message/${message.ID}`)).json()).Text as string
  const token = body.match(/#verify=([A-Za-z0-9_-]{43})/)![1]
  expect((await request.post("/api/v1/users/me/verify-email", { headers, data: { token } })).status()).toBe(200)
  await page.route("**/api/v1/capabilities/catalog", route => route.abort())
  await page.goto("/")
  await page.getByLabel("邮箱", { exact: true }).fill(email)
  await page.getByLabel("密码（12–128 字符）").fill(password)
  await page.getByRole("button", { name: "登录", exact: true }).click()
  const map = page.getByRole("region", { name: "全栈能力与前置地图" })
  await expect(map.getByRole("alert")).toContainText("目录读取失败")
  await page.unroute("**/api/v1/capabilities/catalog")
  await map.getByRole("button", { name: "重新读取能力目录" }).click()
  await expect(map.getByRole("article")).toHaveCount(14)
  await expect(map).toContainText("不表示不会")
  await expect(map).toContainText("尚未人工核验")
  const first = map.locator("summary").first()
  await first.focus()
  await page.keyboard.press("Enter")
  await expect(first.locator("..")).toHaveAttribute("open", "")
  await expect(first.locator("..")).toContainText("无需先验能力证明")
  expect(await first.evaluate(el => getComputedStyle(el).outlineStyle)).not.toBe("none")
  const domain = map.getByLabel("查看领域", { exact: true })
  await domain.selectOption("architecture")
  const difficulty = map.getByRole("radio", { name: "综合", exact: true })
  await map.getByRole("radio", { name: "基础", exact: true }).focus()
  await page.keyboard.press("ArrowDown")
  await page.keyboard.press("ArrowDown")
  await expect(difficulty).toBeChecked()
  const evolution = map.locator("summary").filter({ hasText: "比较兼容迁移与故障范围代价" })
  await evolution.focus()
  await page.keyboard.press("Enter")
  await expect(evolution.locator("..")).toContainText("以下全部必需")
  await expect(evolution.locator("..")).toContainText("替代组 2")
  await page.setViewportSize({ width: 320, height: 800 })
  await page.evaluate(() => { document.documentElement.style.fontSize = "200%" })
  await map.scrollIntoViewIfNeeded()
  await page.screenshot({ path: "test-results/capability-map-mobile.png", fullPage: true })
  const overflow = await page.evaluate(() => Array.from(document.querySelectorAll("body *")).filter(el => el.getBoundingClientRect().right > innerWidth).map(el => `${el.tagName}#${el.id}`))
  expect(overflow).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.route("**/api/v1/capabilities/catalog", route => route.abort())
  await map.getByRole("button", { name: "重新读取能力目录" }).click()
  await expect(map.getByRole("alert")).toContainText("已有目录保留")
  await expect(domain).toHaveValue("architecture")
  await expect(difficulty).toBeChecked()
  await expect(map.getByRole("article")).toHaveCount(1)
  await page.unroute("**/api/v1/capabilities/catalog")
  await request.post("/api/v1/login/logout", { headers })
  await request.post("/api/v1/login/logout", { headers: adminHeaders })
})
