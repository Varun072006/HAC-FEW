// Browser journey: build -> save -> run -> approval gate -> second user approves -> trace.
// Needs the API and the console running, and: npx playwright install chromium
//   BASE=http://127.0.0.1:5173 OUT=./e2e/out npm run e2e
// Uses the seeded development accounts (HACFEW_DEV_PASSWORD, default hacfew-dev).
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const BASE = process.env.BASE ?? 'http://127.0.0.1:5173'
const OUT = process.env.OUT ?? './e2e/out'
mkdirSync(OUT, { recursive: true })
const log = (...a) => console.log(...a)
const browser = await chromium.launch()
const consoleErrors = []

async function session(viewport = { width: 1440, height: 900 }) {
  const ctx = await browser.newContext({ viewport })
  const page = await ctx.newPage()
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(`${page.url()} :: ${m.text()}`) })
  page.on('pageerror', (e) => consoleErrors.push(`PAGEERROR ${e.message}`))
  return { ctx, page }
}
async function login(page, user) {
  await page.goto(BASE + '/')
  await page.getByLabel('Username').fill(user)
  await page.getByLabel('Password').fill((process.env.HACFEW_DEV_PASSWORD ?? 'hacfew-dev'))
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('navigation', { name: 'Primary' }).waitFor()
}
const shot = (page, name) => page.screenshot({ path: `${OUT}/${name}.png` })

// ---- login page (desktop + mobile)
{
  const { ctx, page } = await session()
  await page.goto(BASE + '/'); await page.getByLabel('Username').waitFor(); await shot(page, '01-login'); await ctx.close()
  const m = await session({ width: 390, height: 800 })
  await m.page.goto(BASE + '/'); await m.page.getByLabel('Username').waitFor(); await shot(m.page, '01b-login-mobile'); await m.ctx.close()
}

// ---- manager: build + run an expense workflow
const mgr = await session()
await login(mgr.page, 'manager')
await shot(mgr.page, '02-overview-empty')
await mgr.page.goto(BASE + '/workflows'); await mgr.page.getByText('Expense reimbursement').first().waitFor()
await shot(mgr.page, '03-workflows')
await mgr.page.goto(BASE + '/workflows/new?template=expense-approval')
await mgr.page.getByLabel('Workflow canvas').waitFor()
await mgr.page.getByText('Submit expense').first().waitFor()
await mgr.page.waitForTimeout(1200)
await shot(mgr.page, '04-builder-template')
await mgr.page.locator('.react-flow__node').filter({ hasText: 'finance.submit_expense' }).click()
await mgr.page.waitForTimeout(500)
await shot(mgr.page, '05-builder-node-selected')
await mgr.page.getByRole('button', { name: 'Save' }).click()
await mgr.page.waitForURL(/\/workflows\/wf_/, { waitUntil: 'commit' })
await mgr.page.getByText('All changes saved').waitFor()
const wfUrl = mgr.page.url(); log('saved workflow', wfUrl)
await shot(mgr.page, '06-builder-saved')

// refresh persistence
await mgr.page.reload(); await mgr.page.getByLabel('Workflow canvas').waitFor(); await mgr.page.waitForTimeout(800)
log('after reload nodes visible:', await mgr.page.locator('.react-flow__node').count())

// run it ($350 -> manager approval)
await mgr.page.getByRole('button', { name: 'Run' }).click()
await mgr.page.locator('#run-amount').fill('350')
await mgr.page.locator('#run-description').fill('Client dinner in Chicago')
await shot(mgr.page, '07-run-dialog')
await mgr.page.getByRole('button', { name: 'Run workflow' }).click()
await mgr.page.waitForURL(/\/runs\/run_/, { waitUntil: 'commit' })
await mgr.page.getByText('Paused at a human approval gate').waitFor({ timeout: 15000 })
const runUrl = mgr.page.url(); log('run', runUrl)
await shot(mgr.page, '08-run-awaiting-approval')

// the requester must not be able to approve
const approveBtn = mgr.page.getByRole('button', { name: 'Approve…' })
log('requester approve button disabled:', await approveBtn.isDisabled())

// ---- director approves
const dir = await session()
await login(dir.page, 'director')
await dir.page.goto(BASE + '/approvals')
await dir.page.getByText('Why approval is needed').first().waitFor()
await shot(dir.page, '09-approvals-inbox')
await dir.page.getByRole('button', { name: 'Approve…' }).first().click()
await dir.page.getByLabel('Comment (optional)').fill('Looks fine')
await shot(dir.page, '10-approve-dialog')
await dir.page.getByRole('dialog').getByRole('button', { name: 'Approve' }).click()
await dir.page.getByText('Nothing is waiting for approval').waitFor({ timeout: 15000 }).catch(() => log('inbox not yet empty (other pending items?)'))
await dir.page.goto(runUrl)
await dir.page.getByText('Completed').first().waitFor({ timeout: 15000 })
await shot(dir.page, '11-run-completed-steps')
await dir.page.getByRole('tab', { name: 'Graph' }).click(); await dir.page.waitForTimeout(800); await shot(dir.page, '12-run-graph')
await dir.page.getByRole('tab', { name: /Events/ }).click(); await shot(dir.page, '13-run-events')

// manager's own view refreshed live (no manual reload)
await mgr.page.waitForTimeout(3500)
log('manager sees status:', await mgr.page.getByRole('status').first().innerText())

// ---- other pages as admin
const adm = await session()
await login(adm.page, 'admin')
for (const [path, name, wait] of [
  ['/', '14-overview', 'Recent runs'], ['/runs', '15-runs', 'Runs'], ['/agents', '16-agents', 'All agents'],
  ['/connectors', '17-connectors', 'Healthy'], ['/policies', '18-policies', 'Decision rules'],
  ['/observability', '19-observability', 'Step runs'], ['/settings', '20-settings', 'Accounts'],
]) {
  await adm.page.goto(BASE + path); await adm.page.getByText(wait).first().waitFor({ timeout: 15000 }); await adm.page.waitForTimeout(600); await shot(adm.page, name)
}
await adm.page.goto(BASE + '/observability'); await adm.page.getByRole('tab', { name: 'Audit trail' }).click()
await adm.page.getByRole('button', { name: 'Verify hash chain' }).click(); await adm.page.getByText(/Chain intact/).waitFor(); await shot(adm.page, '21-audit')

// employee view: restricted
const emp = await session()
await login(emp.page, 'employee')
await emp.page.goto(BASE + '/observability'); await emp.page.getByText('Audit trail is restricted').waitFor().catch(() => {})
await shot(emp.page, '22-employee-observability')
await emp.page.goto(BASE + '/workflows'); await shot(emp.page, '23-employee-workflows')

// mobile overview
const mob = await session({ width: 390, height: 844 })
await login(mob.page, 'manager').catch(async () => { await mob.page.getByLabel('Open navigation').click() })
await shot(mob.page, '24-mobile-overview')

log('CONSOLE ERRORS:', consoleErrors.length); consoleErrors.slice(0, 15).forEach((e) => log(' -', e))
await browser.close()
