// Release check: drive the real app's pages in Chromium, the way a person would, against
// the sample data written by backend/ci_fixture.py. Run by packaging/browser_test.py (which
// starts the app and passes its address and secret), on the Windows build leg of
// .github/workflows/build-test.yml; modelled on personal-website's verify-admin.mjs.
//
// Usage:
//   node scripts/verify-app.mjs --base http://127.0.0.1:PORT --token SECRET --manifest m.json [--artifacts dir]
//
// The walk, in the light theme:
//   lists in table and card view; a dataset: exclude and include a paper, mark it read,
//   rename the dataset, export CSV; an evaluation: set a paper's relevance, export RIS and
//   BibTeX; Settings: every section, the theme surviving a reload, save and remove an AI
//   key, download a backup; delete a dataset, restore it from Deleted Items; a page reload
//   on a client route; an unknown /api path is a JSON 404.
// Then a read-only tour of the same pages in the dark theme.
//
// Any uncaught page error, unexpected console error or server error (5xx) fails it. It
// must stay offline: it never saves an Elsevier, Springer or Semantic Scholar key (that
// queues real abstract lookups), and at the end no background job may have run.
// --artifacts: where to save a screenshot and a Playwright trace when a step fails.
import { mkdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { chromium } from 'playwright'

const args = process.argv.slice(2)
const arg = (name, fallback) => (args.includes(name) ? args[args.indexOf(name) + 1] : fallback)
const BASE = arg('--base')
const TOKEN = arg('--token')
const ARTIFACTS = arg('--artifacts', null)
const manifest = JSON.parse(readFileSync(arg('--manifest'), 'utf8'))
if (!BASE || !TOKEN) throw new Error('--base and --token are required')

const problems = []
const fail = (msg) => {
  problems.push(msg)
  console.error(`::error::${msg}`)
}
const step = (name) => console.log(`verify-app: ${name}`)

async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { Authorization: `Bearer ${TOKEN}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  })
  const text = await res.text()
  let json = null
  try {
    json = JSON.parse(text)
  } catch {
    /* not JSON */
  }
  return { status: res.status, json, text }
}

function expect(condition, message) {
  if (!condition) throw new Error(message)
}

// Uncaught errors, console errors and 5xx answers fail the run. A 4xx the page expects
// (none in this walk) would be listed here.
function watch(page) {
  page.on('pageerror', (err) => fail(`uncaught error on ${page.url()}: ${err.message}`))
  page.on('console', (msg) => {
    if (msg.type() === 'error') fail(`console error on ${page.url()}: ${msg.text()}`)
  })
  page.on('response', (res) => {
    if (res.status() >= 500) fail(`${res.status()} from ${res.request().method()} ${res.url()}`)
  })
}

async function newPage(browser, theme) {
  const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1400, height: 900 } })
  // The theme the page reads before its first paint (lib/theme.js, index.html). Set once only,
  // so a theme chosen in Settings during the walk survives a reload.
  await context.addInitScript((t) => {
    if (!window.localStorage.getItem('theme')) window.localStorage.setItem('theme', t)
  }, theme)
  if (ARTIFACTS) await context.tracing.start({ screenshots: true, snapshots: true })
  const page = await context.newPage()
  watch(page)
  // The private link: the secret travels after the #, which no server ever sees.
  await page.goto(`${BASE}/#token=${TOKEN}`)
  await page.getByRole('link', { name: 'Paper Datasets' }).first().waitFor()
  return { context, page }
}

async function openMenu(scope) {
  await scope.getByRole('button', { name: 'More actions' }).first().click()
}

// Menu entries (components/MoreMenu.jsx) are menuitems, or menuitemradios for a choice
// such as Relevance. A label matches the start of the entry ("Export" finds "Export (6)").
async function pickMenu(page, ...labels) {
  for (const label of labels) {
    const name = new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`)
    await page.getByRole('menuitem', { name }).or(page.getByRole('menuitemradio', { name })).first().click()
  }
}

// The card of one paper on a dataset or evaluation page, found by its title.
const paperCard = (page, title) =>
  page.locator('div, article, li').filter({ hasText: title }).filter({ has: page.getByRole('button', { name: 'More actions' }) }).last()

async function download(page, action) {
  const [file] = await Promise.all([page.waitForEvent('download'), action()])
  const path = await file.path()
  return { name: file.suggestedFilename(), text: readFileSync(path, 'utf8'), bytes: readFileSync(path) }
}

// A pick list (components/Combobox.jsx) shows its current choice as its value.
async function chooseOption(scope, current, label) {
  await scope.locator(`input[role="combobox"][value="${current}"]`).first().click()
  await scope.getByRole('option', { name: label }).first().click()
}

async function fullWalk(page) {
  const { first, second, trashed } = manifest.datasets
  const completed = manifest.runs.completed

  step('dataset list in table and card view')
  await page.goto(`${BASE}/datasets`)
  await page.getByText(first.name).first().waitFor()
  await page.getByText(second.name).first().waitFor()
  await chooseOption(page, 'Table', 'Card')
  await page.getByText(first.name).first().waitFor()
  await chooseOption(page, 'Card', 'Table')
  await page.getByText(first.name).first().waitFor()

  step('open a dataset')
  await page.getByText(first.name).first().click()
  await page.waitForURL(`**/datasets/${first.id}**`)
  const target = (await api(`/api/datasets/${first.id}`)).json.papers.find((p) => p.title !== manifest.retracted_title && p.abstract)
  await page.getByText(target.title).first().waitFor()

  step('exclude, include and mark a paper read')
  await openMenu(paperCard(page, target.title))
  await pickMenu(page, 'Exclude paper')
  await expectPaper(first.id, target.id, (p) => p.excluded, 'excluded')
  await openMenu(paperCard(page, target.title))
  await pickMenu(page, 'Include paper')
  await expectPaper(first.id, target.id, (p) => !p.excluded, 'included again')
  await openMenu(paperCard(page, target.title))
  await pickMenu(page, 'Mark as read')
  await expectPaper(first.id, target.id, (p) => p.read, 'marked read')

  step('rename the dataset')
  const newName = 'Graphene heat flow (renamed)'
  await openMenu(page.locator('main'))
  await pickMenu(page, 'Rename')
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('textbox', { name: 'Name' }).fill(newName)
  await dialog.getByRole('button', { name: 'Rename' }).click()
  await page.getByText(newName).first().waitFor()
  expect((await api(`/api/datasets/${first.id}`)).json.name === newName, 'the new dataset name was not saved')

  step('export the dataset as CSV')
  await openMenu(page.locator('main'))
  const csv = await download(page, () => pickMenu(page, 'Export', 'CSV'))
  expect(csv.name.endsWith('.csv'), `the CSV download was named ${csv.name}`)
  expect(csv.text.includes(target.title), 'the CSV does not list the dataset papers')

  step('an evaluation: relevance and exports')
  await page.goto(`${BASE}/evaluations/${completed.id}`)
  await page.getByText(manifest.paper.title).first().waitFor()
  await openMenu(paperCard(page, manifest.paper.title))
  await pickMenu(page, 'Relevance', 'Relevant')
  await waitFor(async () => {
    const run = (await api(`/api/analysis-runs/${completed.id}`)).json
    const result = (run.results || []).find((r) => r.id === manifest.paper.id)
    return result && result.relevance === 'relevant'
  }, 'the relevance was not saved')
  for (const [format, extension, marker] of [['RIS', '.ris', 'TY  -'], ['BibTeX', '.bib', '@']]) {
    await openMenu(page.locator('main'))
    const file = await download(page, () => pickMenu(page, 'Export', format))
    expect(file.name.endsWith(extension), `the ${format} download was named ${file.name}`)
    expect(file.text.includes(marker), `the ${format} file does not look like ${format}`)
  }

  step('a client route survives a reload')
  await page.reload()
  await page.getByText(manifest.paper.title).first().waitFor()

  step('Settings: every section')
  await page.getByRole('button', { name: 'Settings' }).click()
  const settings = page.getByRole('dialog')
  for (const section of ['AI Integrations', 'Research Databases', 'Your Data', 'Appearance', 'Software and Updates', 'License and Notices']) {
    await settings.getByRole('navigation', { name: 'Settings sections' }).getByText(section, { exact: true }).click()
    await settings.getByRole('heading', { name: section }).first().waitFor()
  }

  step('Settings: save and remove an AI provider key (never a lookup key: that would queue real lookups)')
  await settings.getByRole('navigation', { name: 'Settings sections' }).getByText('AI Integrations', { exact: true }).click()
  // The key card (settings/ProviderKeyCard.jsx): the card element that holds the "Anthropic" title.
  const card = settings.locator('div.flex-col').filter({ has: page.getByRole('heading', { name: /Anthropic/ }) }).filter({ has: page.locator('input, button') }).last()
  await card.getByRole('button', { name: 'Edit' }).click()
  await card.locator('input[type="password"]').fill('sk-ant-ci-not-a-real-key')
  await card.getByRole('button', { name: 'Save' }).click()
  await waitFor(async () => (await api('/api/settings/api-key')).json.anthropic === true, 'the AI key was not saved')
  await card.getByRole('button', { name: /^(Edit|Saved)$/ }).click()
  await card.getByRole('button', { name: 'Remove saved key' }).click()
  await card.getByRole('button', { name: 'Save' }).click()
  await waitFor(async () => (await api('/api/settings/api-key')).json.anthropic === false, 'the AI key was not removed')

  step('Settings: download a backup')
  await settings.getByRole('navigation', { name: 'Settings sections' }).getByText('Your Data', { exact: true }).click()
  const backup = await download(page, () => settings.getByRole('button', { name: 'Download backup' }).click())
  expect(backup.bytes.subarray(0, 15).toString('latin1') === 'SQLite format 3', 'the backup is not a SQLite database')

  step('Settings: the theme survives a reload')
  await settings.getByRole('navigation', { name: 'Settings sections' }).getByText('Appearance', { exact: true }).click()
  await chooseOption(settings, 'Light', 'Dark')
  await page.keyboard.press('Escape')
  await page.reload()
  await page.getByRole('link', { name: 'Paper Datasets' }).first().waitFor()
  expect(await page.evaluate(() => document.documentElement.classList.contains('dark')), 'the dark theme did not survive a reload')
  await page.evaluate(() => window.localStorage.setItem('theme', 'light'))
  await page.reload()

  step('delete a dataset, then restore it from Deleted Items')
  await page.goto(`${BASE}/datasets/${second.id}`)
  await page.getByText(second.name).first().waitFor()
  await openMenu(page.locator('main'))
  await pickMenu(page, 'Delete')
  await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click()
  await waitFor(async () => (await api(`/api/datasets/${second.id}`)).status === 404, 'the dataset was not deleted')
  await page.goto(`${BASE}/trash`)
  for (const name of [second.name, trashed.name]) {
    const row = page.locator('li, tr, div').filter({ hasText: name }).filter({ has: page.getByRole('button', { name: 'Restore' }) }).last()
    await row.getByRole('button', { name: 'Restore' }).click()
  }
  await waitFor(async () => (await api(`/api/datasets/${second.id}`)).status === 200, 'the dataset was not restored')
  await waitFor(async () => (await api(`/api/datasets/${trashed.id}`)).status === 200, 'the fixture trashed dataset was not restored')
}

async function expectPaper(datasetId, paperId, test, what) {
  await waitFor(async () => {
    const paper = (await api(`/api/datasets/${datasetId}`)).json.papers.find((p) => p.id === paperId)
    return paper && test(paper)
  }, `the paper was not ${what}`)
}

async function waitFor(check, message, seconds = 10) {
  const deadline = Date.now() + seconds * 1000
  while (Date.now() < deadline) {
    if (await check()) return
    await new Promise((r) => setTimeout(r, 200))
  }
  throw new Error(message)
}

// The same pages again, only looking, in the other theme.
async function tour(page) {
  const { first } = manifest.datasets
  for (const [path, text] of [
    ['/datasets', manifest.datasets.second.name],
    [`/datasets/${first.id}`, manifest.paper.title],
    ['/prompts', manifest.prompt.name],
    [`/prompts/${manifest.prompt.id}`, manifest.prompt.name],
    ['/evaluations', manifest.runs.incomplete.name],
    [`/evaluations/${manifest.runs.completed.id}`, manifest.paper.title],
    ['/trash', 'Deleted Items'],
  ]) {
    step(`tour ${path}`)
    await page.goto(`${BASE}${path}`)
    await page.getByText(text).first().waitFor()
  }
  expect(await page.evaluate(() => document.documentElement.classList.contains('dark')), 'the dark theme was not applied')
}

async function checkApi() {
  step('an unknown /api path is a JSON 404')
  const missing = await api('/api/no-such-thing')
  expect(missing.status === 404 && missing.json && missing.json.error, `an unknown /api path answered ${missing.status}: ${missing.text.slice(0, 80)}`)

  step('no background job ran (the walk must stay offline)')
  const jobs = (await api('/api/jobs')).json.jobs
  expect(jobs.length === 0, `background jobs were started: ${jobs.map((j) => j.kind).join(', ')}`)
}

// A screenshot and the Playwright trace of one walk, kept whenever that walk recorded a problem,
// whether a step threw or a watcher (page error, console error, 5xx) only noted it.
async function finishWalk({ context, page }, theme, hadProblems) {
  if (!ARTIFACTS) return
  if (hadProblems) {
    mkdirSync(ARTIFACTS, { recursive: true })
    await page.screenshot({ path: join(ARTIFACTS, `failure-${theme}.png`), fullPage: true }).catch(() => {})
    await context.tracing.stop({ path: join(ARTIFACTS, `trace-${theme}.zip`) }).catch(() => {})
  } else {
    await context.tracing.stop().catch(() => {})
  }
}

async function main() {
  const browser = await chromium.launch()
  try {
    for (const [theme, walk] of [['light', fullWalk], ['dark', tour]]) {
      const before = problems.length
      const current = await newPage(browser, theme)
      try {
        await walk(current.page)
      } catch (err) {
        fail(err.message)
      } finally {
        await finishWalk(current, theme, problems.length > before)
        await current.context.close()
      }
      // The tour reuses what the walk changed: after a failure it would only add noise.
      if (problems.length) break
    }
    if (!problems.length) await checkApi()
  } catch (err) {
    fail(err.message)
  } finally {
    await browser.close()
  }
  if (problems.length) {
    console.error(`verify-app: ${problems.length} problem(s)`)
    process.exit(1)
  }
  console.log('verify-app: all checks passed')
}

await main()
