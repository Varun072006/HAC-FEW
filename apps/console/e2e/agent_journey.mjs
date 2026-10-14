// Browser journey for the agent runtime: plan -> validate -> execute -> pause on approval -> delegation view
// -> second user approves -> resumed run completes with its persisted trace.
// Needs the API and console running, and: npx playwright install chromium
//   BASE=http://127.0.0.1:5173 OUT=./e2e/out npm run e2e:agent
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const BASE = process.env.BASE ?? 'http://127.0.0.1:5173'
const OUT = process.env.OUT ?? './e2e/out'
mkdirSync(OUT, { recursive: true })
const browser = await chromium.launch()
const consoleErrors = []
let failures = 0
const check = (cond, msg) => { console.log((cond ? 'ok   ' : 'FAIL ') + msg); if (!cond) failures++ }

async function session() {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const page = await ctx.newPage()
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(`${page.url()} :: ${m.text()}`) })
  page.on('pageerror', (e) => consoleErrors.push(`PAGEERROR ${e.message}`))
  return { ctx, page }
}
async function login(page, user) {
  await page.goto(BASE + '/')
  await page.getByLabel('Username').fill(user)
  await page.getByLabel('Password').fill(process.env.HACFEW_DEV_PASSWORD ?? 'hacfew-dev')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('navigation', { name: 'Primary' }).waitFor()
}
const shot = (page, name) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true })

const mgr = await session()
await login(mgr.page, 'manager')

// ---- agents: the registry is real and shows the three levels
await mgr.page.getByRole('link', { name: 'Agents' }).click()
await mgr.page.getByRole('table', { name: 'Agent registry' }).waitFor()
check(await mgr.page.getByRole('button', { name: /Organization Supervisor/ }).count() > 0, 'agent registry lists the supervisor')
check(await mgr.page.getByRole('button', { name: /Expense Specialist/ }).count() > 0, 'agent registry lists specialists')
check(await mgr.page.getByRole('button', { name: 'New agent' }).count() === 0, 'a manager cannot create agents (no agent:write)')
await shot(mgr.page, '10-agents')

// ---- plan & run
await mgr.page.getByRole('link', { name: 'Plan & run' }).click()
await mgr.page.getByLabel('Objective').fill('Reimburse an expense claim with the receipt')
await mgr.page.getByRole('button', { name: /Generate and validate plan/ }).click()
await mgr.page.getByRole('table', { name: 'Plan tasks' }).waitFor()
check(await mgr.page.getByText('valid', { exact: true }).count() > 0, 'plan generated and validated')
check(await mgr.page.getByText('erp_submit_expense').count() > 0, 'plan lists the protected operation')
await shot(mgr.page, '11-plan')
await mgr.page.getByLabel('amount').fill('350')
await mgr.page.getByLabel('description').fill('Client dinner (e2e)')
await mgr.page.getByRole('button', { name: 'Execute plan' }).click()
await mgr.page.waitForURL(/\/runs\/run_/)
const runUrl = mgr.page.url()
await mgr.page.getByText('Paused at a human approval gate').waitFor({ timeout: 30000 })
check(true, 'run paused at the approval gate')
await mgr.page.getByText(/Live · streaming/).waitFor({ timeout: 15000 })
check(true, 'events arrive over the live SSE stream (not polling)')
await mgr.page.getByRole('tab', { name: 'Delegation' }).click()
await mgr.page.getByText('Finance Coordinator').first().waitFor({ timeout: 15000 })
check(await mgr.page.getByText('Expense Specialist').count() > 0 && await mgr.page.getByText('Organization Supervisor').count() > 0, 'delegation tree shows supervisor -> coordinator -> specialist')
await shot(mgr.page, '12-delegation')
await mgr.page.getByRole('tab', { name: 'Events' }).click()
check(await mgr.page.getByText('agent.delegated').count() > 0 && await mgr.page.getByText('approval.requested').count() > 0, 'event feed shows delegation and the approval request')

// ---- the director approves in a separate session
const dir = await session()
await login(dir.page, 'director')
await dir.page.goto(runUrl)
await dir.page.getByRole('button', { name: /Approve/ }).first().click()
await dir.page.getByRole('dialog').getByRole('button', { name: /Approve/ }).click()
await mgr.page.getByRole('tab', { name: 'Steps' }).click()
await mgr.page.getByText(/Approved by Dana Director/).first().waitFor({ state: 'attached', timeout: 30000 })
check(true, 'resumed step records who approved')
check(await mgr.page.getByText('Resource use against limits').count() > 0, 'budget panel shown')
check(await mgr.page.getByRole('status').getByText('Completed', { exact: true }).count() > 0, 'run reached Completed')
await shot(mgr.page, '13-run-completed')

check(consoleErrors.length === 0, `no browser console errors${consoleErrors.length ? ': ' + consoleErrors.slice(0, 3).join(' | ') : ''}`)
await browser.close()
if (failures) { console.log(`${failures} check(s) failed`); process.exit(1) }
console.log('AGENT JOURNEY PASSED')
