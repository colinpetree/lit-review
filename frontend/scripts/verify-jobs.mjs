// CI's e2e check: the background-job flow through the real pages, with the AI and the paper
// sources faked by backend/tests/e2e_server.py (started by packaging/browser_test.py --jobs).
//
//   1. save an AI key (fake; nothing leaves the computer: the server refuses the network)
//   2. New Dataset -> its search and abstract lookup run as jobs -> the dataset fills in
//   3. New Evaluation with the spending question set to "always ask" -> the estimate shows,
//      the confirmation appears, Run evaluation
//   4. stop the grading halfway from the run's menu, see it stop, Resume, see it finish
//   5. export the results as CSV
//
// Usage: node scripts/verify-jobs.mjs --base URL --token SECRET [--artifacts dir]
import { mkdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { chromium } from 'playwright'

const args = process.argv.slice(2)
const arg = (name, fallback) => (args.includes(name) ? args[args.indexOf(name) + 1] : fallback)
const BASE = arg('--base')
const TOKEN = arg('--token')
const ARTIFACTS = arg('--artifacts', null)

const problems = []
const fail = (msg) => {
  problems.push(msg)
  console.error(`::error::${msg}`)
}
const step = (name) => console.log(`verify-jobs: ${name}`)

async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { Authorization: `Bearer ${TOKEN}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  })
  return { status: res.status, json: await res.json().catch(() => null) }
}

async function waitFor(check, message, seconds = 60) {
  const deadline = Date.now() + seconds * 1000
  let last
  while (Date.now() < deadline) {
    last = await check()
    if (last) return last
    await new Promise((r) => setTimeout(r, 300))
  }
  throw new Error(message)
}

async function main() {
  const browser = await chromium.launch()
  const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1400, height: 900 } })
  // "Ask before spending more than" $0: every evaluation asks first (lib/spendSetting.js).
  await context.addInitScript(() => window.localStorage.setItem('lit-review.spend-confirm-usd', '0'))
  if (ARTIFACTS) await context.tracing.start({ screenshots: true, snapshots: true })
  const page = await context.newPage()
  page.on('pageerror', (err) => fail(`uncaught error on ${page.url()}: ${err.message}`))
  page.on('console', (msg) => {
    if (msg.type() === 'error') fail(`console error on ${page.url()}: ${msg.text()}`)
  })
  page.on('response', (res) => {
    if (res.status() >= 500) fail(`${res.status()} from ${res.request().method()} ${res.url()}`)
  })

  try {
    step('save an AI key (a fake one: the server cannot reach any provider)')
    const saved = await api('/api/settings/api-key', { method: 'POST', body: { provider: 'anthropic', api_key: 'sk-ant-e2e-fake' } })
    if (saved.status !== 200) throw new Error(`saving the key answered ${saved.status}`)

    await page.goto(`${BASE}/#token=${TOKEN}`)
    await page.getByRole('link', { name: 'Paper Datasets' }).first().waitFor()

    step('New Dataset: the search and the abstract lookup run in the background')
    await page.goto(`${BASE}/datasets`)
    await page.getByRole('button', { name: /New Dataset/ }).click()
    const newDataset = page.getByRole('dialog')
    await newDataset.getByPlaceholder('Describe the topic in a sentence or two').fill('How fast do coral reefs grow back after bleaching?')
    await newDataset.getByRole('button', { name: 'Search for Papers' }).click()
    await newDataset.waitFor({ state: 'detached' })
    const dataset = await waitFor(async () => {
      const list = (await api('/api/datasets')).json?.datasets ?? []
      return list.find((d) => !d.pending && d.paper_count > 0 && d.state === 'completed')
    }, 'the dataset search did not finish')
    await page.getByText(dataset.name).first().waitFor()
    await waitFor(async () => {
      const jobs = (await api('/api/jobs')).json.jobs
      return jobs.some((j) => j.kind === 'find_abstracts') && jobs.every((j) => !['queued', 'running'].includes(j.status))
    }, 'the abstract lookup did not finish')

    step('New Evaluation: the estimate, the spending question, then Run')
    await page.goto(`${BASE}/evaluations`)
    await page.getByRole('button', { name: /New Evaluation/ }).click()
    const newRun = page.getByRole('dialog')
    await newRun.getByRole('combobox').first().click()
    await page.getByRole('option', { name: new RegExp(dataset.name) }).first().click()
    await newRun.getByPlaceholder('Precisely what should a paper show to be relevant?').fill('Field measurements of coral regrowth after a bleaching event.')
    await newRun.getByText(/\$\d/).first().waitFor() // the estimate
    await newRun.getByRole('button', { name: 'Run Evaluation' }).click()
    // The confirmation (ConfirmModal) opens over the form; its button is "Run evaluation".
    await page.getByRole('heading', { name: 'Run this evaluation?' }).waitFor()
    await page.getByRole('button', { name: 'Run evaluation', exact: true }).click()
    const run = await waitFor(async () => (await api('/api/analysis-runs')).json?.runs?.[0], 'the evaluation was not created')

    step('stop the grading halfway, then resume it')
    await page.goto(`${BASE}/evaluations/${run.id}`)
    await waitFor(async () => {
      const r = (await api(`/api/analysis-runs/${run.id}`)).json
      return r.results.length > 0 && r.remaining > 0
    }, 'the grading never got started')
    await page.locator('main').getByRole('button', { name: 'More actions' }).first().click()
    await page.getByRole('menuitem', { name: 'Stop' }).click()
    const stopped = await waitFor(async () => {
      const r = (await api(`/api/analysis-runs/${run.id}`)).json
      return r.state === 'incomplete' && r.remaining > 0 ? r : null
    }, 'the run did not stop with papers left', 90)
    await page.getByRole('button', { name: /Resume grading/ }).click()
    await waitFor(async () => {
      const r = (await api(`/api/analysis-runs/${run.id}`)).json
      return r.remaining === 0 && r.status === 'completed'
    }, `the resumed run did not finish (it had ${stopped.remaining} left)`, 120)

    step('export the results')
    await page.reload()
    await page.locator('main').getByRole('button', { name: 'More actions' }).first().click()
    await page.getByRole('menuitem', { name: /^Export/ }).first().click()
    const [file] = await Promise.all([page.waitForEvent('download'), page.getByRole('menuitem', { name: 'CSV' }).click()])
    const csv = readFileSync(await file.path(), 'utf8')
    if (!csv.includes('Coral reef study')) throw new Error('the exported CSV does not list the graded papers')

    // Any job that ended in an error. The one stopped on purpose above says db.STOPPED_BY_USER.
    const failed = (await api('/api/jobs')).json.jobs.filter((j) => j.status === 'incomplete' && j.error && !j.error.startsWith('Stopped by user.'))
    if (failed.length) throw new Error(`jobs ended with errors: ${failed.map((j) => `${j.kind}: ${j.error}`).join('; ')}`)
  } catch (err) {
    fail(err.message)
  } finally {
    // Evidence whenever anything was recorded: a step that threw, or a page error, console
    // error or 5xx that a watcher only noted.
    if (ARTIFACTS && problems.length) {
      mkdirSync(ARTIFACTS, { recursive: true })
      await page.screenshot({ path: join(ARTIFACTS, 'jobs-failure.png'), fullPage: true }).catch(() => {})
      await context.tracing.stop({ path: join(ARTIFACTS, 'jobs-trace.zip') }).catch(() => {})
    }
    await browser.close()
  }
  if (problems.length) {
    console.error(`verify-jobs: ${problems.length} problem(s)`)
    process.exit(1)
  }
  console.log('verify-jobs: all checks passed')
}

await main()
