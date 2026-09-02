async page => {
const failures = []
const browserErrors = []

page.on('console', (message) => {
  if (message.type() === 'error') browserErrors.push(`console: ${message.text()}`)
})
page.on('pageerror', (error) => browserErrors.push(`pageerror: ${error.message}`))

async function expectVisible(locator, label) {
  try {
    await locator.waitFor({ state: 'visible', timeout: 10000 })
  } catch {
    failures.push(`${label}不可见`)
  }
}

async function expectText(text, label = text) {
  await expectVisible(page.getByText(text, { exact: true }).first(), label)
}

await page.setViewportSize({ width: 1440, height: 1000 })
await page.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle' })

for (const text of ['3 个解决方案', '统一口径测试', '72 小时同步回放', '未来改进方案']) {
  await expectText(text)
}
if (await page.getByText('数据清单', { exact: true }).count()) failures.push('仍显示“数据清单”入口')
await expectText('同一问题，三种解决方案')
const experimentCard = page.locator('.foundation-card').filter({ hasText: '统一实验设定' })
await experimentCard.getByRole('button', { name: '展开完整信息 ↓' }).click()
await expectVisible(experimentCard.getByText('查看当前案例', { exact: true }), '统一实验设定中的当前案例')
await expectVisible(experimentCard.getByLabel('当前案例'), '统一实验设定中的案例选择器')
if (await page.getByText('上面的规则和参数保持不变；这里只切换具体案例的需求、节点参数和异常信息。', { exact: true }).count()) failures.push('仍显示修改过程提示语')
await page.screenshot({ path: 'output/playwright/desktop-home.png', fullPage: false })

const milpTab = page.getByRole('tab', { name: '01MILP联合决策' })
await milpTab.click()
await expectText('异常发生后分别处理')
for (const text of ['当前接入', '未来接入', '观察期内不接入', '减少剩余需求', '扣减可用自有车']) {
  await expectText(text)
}
await page.getByText('核心逻辑', { exact: true }).scrollIntoViewIfNeeded()
await page.screenshot({ path: 'output/playwright/desktop-milp-flow.png', fullPage: false })

const bendersTab = page.getByRole('tab', { name: '02Benders分解＋列生成' })
await bendersTab.click()
await expectText('列生成受限主问题')
await expectText('列生成定价子问题')

const qTab = page.getByRole('tab', { name: '03Q-learning—LP两层混合方法' })
await qTab.click()
await expectText('每一行：5维离散状态')
await expectText('每一列：9种组合规则')
await expectText('Q值如何更新')
if (await page.getByText('一张上层Q表，不是两张Q表', { exact: true }).count()) failures.push('仍显示已要求删除的Q表提示块')
const actionCells = await page.locator('.q-action-matrix > span').count()
if (actionCells !== 10) failures.push(`九种动作矩阵结构异常：应有1个空角格+9个动作格，实际${actionCells}个span`)
const improvementColumns = await page.locator('.improvement-row').first().evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length)
if (improvementColumns !== 2) failures.push(`缺点与改进方案应左右两栏显示，实际${improvementColumns}栏`)
await page.locator('.improvement-card').scrollIntoViewIfNeeded()
await page.screenshot({ path: 'output/playwright/desktop-improvements.png', fullPage: false })
await page.getByText('每一行：5维离散状态', { exact: true }).scrollIntoViewIfNeeded()
await page.screenshot({ path: 'output/playwright/desktop-q-table.png', fullPage: false })

await page.getByRole('link', { name: '结果对比' }).click()
await expectText('三种解决方案的结果对比与差距解释')
const comparisonColumns = await page.locator('.three-method-table .table-head > span').count()
if (comparisonColumns !== 6) failures.push(`场景对比表应有6列，实际${comparisonColumns}列`)
await page.getByRole('button', { name: '方法箱型图' }).click()
await expectVisible(page.getByRole('img', { name: /方法箱型图/ }), '方法箱型图')
await page.screenshot({ path: 'output/playwright/desktop-comparison.png', fullPage: false })

await page.setViewportSize({ width: 390, height: 844 })
await page.goto('http://127.0.0.1:5173/#methods', { waitUntil: 'networkidle' })
await page.getByRole('tab', { name: '03Q-learning—LP两层混合方法' }).click()
await page.getByText('每一行：5维离散状态', { exact: true }).scrollIntoViewIfNeeded()
const viewport = await page.evaluate(() => ({ viewport: window.innerWidth, document: document.documentElement.scrollWidth }))
if (viewport.document > viewport.viewport + 1) {
  const overflowElements = await page.evaluate(() => [...document.querySelectorAll('body *')]
    .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
    .slice(0, 8)
    .map((element) => `${element.tagName.toLowerCase()}.${element.className}`))
  failures.push(`手机端页面发生横向溢出：页面${viewport.document}px，视口${viewport.viewport}px；相关元素：${overflowElements.join('，')}`)
}
await page.screenshot({ path: 'output/playwright/mobile-q-table.png', fullPage: false })

if (browserErrors.length) failures.push(...browserErrors)
if (failures.length) throw new Error(`网页验收失败：\n- ${failures.join('\n- ')}`)

console.log(JSON.stringify({
  status: 'pass',
  checks: ['desktop layout', 'MILP event branches', 'Benders-CG flow', 'Q-table and 9 actions', 'six-column comparison', 'chart switch', 'mobile overflow', 'browser console'],
  screenshots: ['desktop-home.png', 'desktop-milp-flow.png', 'desktop-q-table.png', 'desktop-improvements.png', 'desktop-comparison.png', 'mobile-q-table.png'],
}, null, 2))
}
