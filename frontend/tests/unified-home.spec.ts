import { expect, test } from "@playwright/test"

test("六区域首页、首次序章和导航往返保留未保存作答", async ({ page }) => {
  test.setTimeout(60_000)
  test.skip(
    !process.env.TRAINING_BROWSER_TOKEN,
    "由 training_browser.py 提供真实未完成任务",
  )
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto("/")
  await page.evaluate((token) => {
    sessionStorage.setItem("token", token!)
    for (const key of Object.keys(localStorage))
      if (key.startsWith("prologue-seen:")) localStorage.removeItem(key)
  }, process.env.TRAINING_BROWSER_TOKEN)
  let failHome = true
  await page.route("**/api/v1/training/tasks/continue", async (route) => {
    if (failHome)
      await route.fulfill({ status: 503, json: { detail: "temporary" } })
    else await route.continue()
  })
  await page.reload()

  await expect(
    page.getByText("最近练习读取失败；没有自动开始随机练习，已有记录不变。"),
  ).toBeVisible()
  failHome = false
  await page.getByRole("button", { name: "重新读取首页行动" }).click()
  await expect(page.getByText(/最近未完成：/)).toBeVisible()
  await page.unroute("**/api/v1/training/tasks/continue")

  const navigation = page.getByRole("navigation", { name: "主要区域" })
  for (const name of [
    "首页",
    "路线与项目",
    "练习工作台",
    "能力与突破",
    "复盘记录",
    "账号与模型",
  ]) {
    await expect(
      navigation.getByRole("button", { name, exact: true }),
    ).toBeVisible()
  }
  const entries = page.getByRole("region", { name: "四种训练入口" })
  for (const name of ["随机练习", "自由主题", "JD 定向", "公开 GitHub 项目"])
    await expect(entries.getByRole("button", { name })).toBeVisible()
  for (const [name, target] of [
    ["随机练习", "random-entry"],
    ["自由主题", "topic-entry"],
    ["JD 定向", "jd-entry"],
    ["公开 GitHub 项目", "project-entry"],
  ] as const) {
    await entries.getByRole("button", { name, exact: true }).focus()
    await page.keyboard.press("Enter")
    const destination = page.locator(`#${target}`)
    await expect(destination).toBeFocused()
    expect(await destination.evaluate((element) => getComputedStyle(element).outlineStyle)).not.toBe("none")
    await navigation.getByRole("button", { name: "首页", exact: true }).click()
  }
  await expect(page.getByText(/最近未完成：/)).toBeVisible()

  await page.getByRole("button", { name: "观看重回巅峰序章" }).click()
  const prologue = page.getByRole("dialog", { name: "重回巅峰" })
  await expect(prologue).toContainText(
    "已经完成的练习、证据、修为和等级始终保留",
  )
  const skip = prologue.getByRole("button", { name: "跳过并进入首页" })
  await expect(skip).toBeFocused()
  await page.keyboard.press("Enter")
  await expect(prologue).not.toBeVisible()
  await page.reload()
  await expect(
    page.getByRole("button", { name: "观看重回巅峰序章" }),
  ).toHaveCount(0)

  await page.getByRole("button", { name: "继续最近未完成练习" }).click()
  const training = page.getByRole("region", { name: "随机第一关" })
  await expect(
    training.getByText("比较请求证据", { exact: true }),
  ).toBeVisible()
  const material = training.getByRole("region", { name: "案例材料" })
  const judgments = training.getByRole("region", { name: "必答判断" })
  expect((await material.boundingBox())!.x).toBeLessThan(
    (await judgments.boundingBox())!.x,
  )
  await page.setViewportSize({ width: 320, height: 760 })
  await training.getByRole("button", { name: "判断", exact: true }).click()
  const reason = training
    .getByRole("textbox", { name: "这一判断的理由" })
    .first()
  await reason.fill("尚未保存的导航往返输入")
  await navigation
    .getByRole("button", { name: "账号与模型", exact: true })
    .click()
  await expect(
    navigation.getByRole("button", { name: "账号与模型", exact: true }),
  ).toHaveAttribute("aria-current", "page")
  await navigation
    .getByRole("button", { name: "练习工作台", exact: true })
    .focus()
  await page.keyboard.press("Enter")
  await expect(reason).toBeVisible()
  await expect(reason).toHaveValue("尚未保存的导航往返输入")

  await page.evaluate(() => {
    document.documentElement.style.fontSize = "200%"
  })
  await expect(
    training.getByRole("button", { name: "材料", exact: true }),
  ).toBeVisible()
  const materialPanel = training.locator('[data-training-panel="materials"]')
  const judgmentPanel = training.locator('[data-training-panel="judgments"]')
  const coachPanel = training.locator('[data-training-panel="coach"]')
  const rememberPosition = async (panel: typeof materialPanel) =>
    panel.evaluate((element) => {
      const maximum = element.scrollHeight - element.clientHeight
      if (maximum <= 0) throw new Error("panel must be independently scrollable")
      element.scrollTop = Math.min(120, maximum)
      return element.scrollTop
    })

  await training.getByRole("button", { name: "材料", exact: true }).click()
  const materialPosition = await rememberPosition(materialPanel)
  await training.getByRole("button", { name: "判断", exact: true }).click()
  const judgmentPosition = await rememberPosition(judgmentPanel)
  await training.getByRole("button", { name: "概念", exact: true }).click()
  const coachPosition = await rememberPosition(coachPanel)
  await training.getByRole("button", { name: "材料", exact: true }).click()
  await expect.poll(() => materialPanel.evaluate((element) => element.scrollTop)).toBe(materialPosition)
  await training.getByRole("button", { name: "判断", exact: true }).click()
  await expect.poll(() => judgmentPanel.evaluate((element) => element.scrollTop)).toBe(judgmentPosition)
  await training.getByRole("button", { name: "概念", exact: true }).click()
  await expect.poll(() => coachPanel.evaluate((element) => element.scrollTop)).toBe(coachPosition)
  await training.getByRole("button", { name: "判断", exact: true }).click()
  await expect(reason).toHaveValue("尚未保存的导航往返输入")
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
})
