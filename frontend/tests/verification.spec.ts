import { expect, test } from "@playwright/test"

test("controlled SMTP registration, email-bound verification and server logout", async ({ page, request }) => {
  const admin = await request.post("/api/v1/login/access-token", { form: {
    username: process.env.FIRST_SUPERUSER!, password: process.env.FIRST_SUPERUSER_PASSWORD!,
  } })
  expect(admin.ok()).toBe(true)
  const adminToken = (await admin.json()).access_token
  const invitation = await request.post("/api/v1/invitations", { headers: { Authorization: `Bearer ${adminToken}` } })
  expect(invitation.status()).toBe(201)
  const email = `mail-browser-${crypto.randomUUID()}@example.com`
  await page.goto("/")
  await page.getByRole("button", { name: "使用邀请码注册" }).click()
  await page.getByLabel("邮箱", { exact: true }).fill(email)
  await page.getByLabel("密码（12–128 字符）").fill("mail-browser-test-password")
  await page.getByLabel("邀请码", { exact: true }).fill((await invitation.json()).code)
  await page.getByRole("button", { name: "注册", exact: true }).click()
  await expect(page.getByRole("status")).toContainText("验证邮件已交给本地收件服务")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page.getByRole("heading", { name: "我的训练首页" })).toBeVisible()
  const token = await page.evaluate(() => sessionStorage.getItem("token"))
  const headers = { Authorization: `Bearer ${token}` }
  expect((await request.get("/api/v1/training/access", { headers })).status()).toBe(403)
  await page.getByRole("button", { name: "重发验证邮件" }).click()
  await expect(page.getByRole("status")).toContainText("一分钟后重发")
  const mailpit = process.env.MAILPIT_URL ?? "http://127.0.0.1:18025"
  const messages = (await (await request.get(`${mailpit}/api/v1/messages?limit=1000`)).json()).messages
  const message = messages.find((m: { To: { Address: string }[] }) => m.To.some(t => t.Address === email))
  expect(message).toBeTruthy()
  const body = (await (await request.get(`${mailpit}/api/v1/message/${message.ID}`)).json()).Text as string
  const link = body.match(/http[^\s]+#verify=[A-Za-z0-9_-]{43}/)![0]
  const verificationToken = link.split("#verify=")[1]
  // Browser loads a forged link; actual backend rejects it without lifting the gate.
  await page.goto("/#verify=" + "x".repeat(43))
  await page.getByRole("button", { name: "确认验证邮箱" }).click()
  await expect(page.getByRole("status")).toContainText("验证链接无效")
  expect((await request.get("/api/v1/training/access", { headers })).status()).toBe(403)
  await page.goto(link)
  await expect(page).not.toHaveURL(/verify=/)
  await page.getByRole("button", { name: "确认验证邮箱" }).click()
  await expect(page.getByRole("status")).toContainText("邮箱验证成功")
  await expect(page.getByRole("button", { name: "重发验证邮件" })).toHaveCount(0)
  await page.getByRole("button", { name: "检查训练准入" }).click()
  await expect(page.getByRole("status")).toHaveText("邮箱准入检查通过")
  expect((await request.post("/api/v1/users/me/verify-email", { headers, data: { token: verificationToken } })).status()).toBe(400)
  // Failed logout retains local credentials so the user can retry server revocation.
  await page.route("**/api/v1/login/logout", route => route.abort())
  await page.getByRole("button", { name: "退出登录" }).click()
  await expect(page.getByRole("status")).toContainText("操作未确认成功")
  expect(await page.evaluate(() => sessionStorage.getItem("token"))).toBe(token)
  await page.unroute("**/api/v1/login/logout")
  await page.getByRole("button", { name: "退出登录" }).click()
  await expect(page.getByRole("status")).toHaveText("已退出当前设备")
  expect((await request.get("/api/v1/users/me", { headers })).status()).toBe(401)
  expect((await request.get("/api/v1/training/access", { headers })).status()).toBe(401)
  await page.reload()
  await expect(page.getByRole("heading", { name: "邮箱登录" })).toBeVisible()
  await request.post("/api/v1/login/logout", { headers: { Authorization: `Bearer ${adminToken}` } })
})
