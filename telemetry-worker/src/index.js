// Counting service for Lit Review: anonymous aggregate counts, nothing per person.
// A POST of {event, version, platform} adds 1 to a counter for today (the service's own UTC
// date). No IP address, user agent or request body is stored or logged. A daily job also copies
// GitHub's per-file download counts, which only ever grow, so growth can be charted.

const EVENTS = new Set(['daily', 'new_install'])
const PLATFORMS = new Set(['windows', 'macos-apple-silicon', 'macos-intel', 'other'])
const VERSION = /^\d{1,2}\.\d{1,3}\.\d{1,3}$/
const MAX_BODY = 512
const REPO = 'colinpetree/lit-review'

const reply = (status) => new Response(null, { status })

// A version is counted only if it is a published release of this repo (tag v<version>), so a
// script cannot invent versions: they never pass, never take space, and never crowd out a real
// one. A release is looked up once on its first ping and remembered in `versions`. A failed
// lookup answers 503 (the app tries again later), never a verdict, so an outage or GitHub's rate
// limit cannot wrongly reject a real release.
async function isRelease(env, version) {
  const known = await env.DB.prepare('SELECT 1 FROM versions WHERE version = ?').bind(version).first()
  if (known) return 'yes'
  // GitHub limits anonymous callers to 60 requests an hour per address, and Cloudflare's addresses
  // are shared. An optional read-only token (Worker secret GITHUB_TOKEN, no scopes needed for a
  // public repo) lifts that to 5,000 an hour.
  const headers = { 'User-Agent': 'lit-review-census', Accept: 'application/vnd.github+json' }
  if (env.GITHUB_TOKEN) headers.Authorization = `Bearer ${env.GITHUB_TOKEN}`
  let response
  try {
    response = await fetch(`https://api.github.com/repos/${REPO}/releases/tags/v${version}`, { headers })
  } catch {
    return 'unknown'
  }
  if (response.status === 404) return 'no'
  if (!response.ok) return 'unknown'
  const release = await response.json()
  if (release.draft || release.tag_name !== `v${version}`) return 'no'
  await env.DB.prepare('INSERT OR IGNORE INTO versions (version) VALUES (?)').bind(version).run()
  return 'yes'
}

export default {
  async fetch(request, env) {
    if (request.method !== 'POST') return reply(405)
    // Set KILL = "1" (a Worker variable) to tell every installed copy to stop sending.
    if (env.KILL === '1') return reply(410)

    if (Number(request.headers.get('content-length') || 0) > MAX_BODY) return reply(413)
    const text = await request.text()
    if (text.length > MAX_BODY) return reply(413)
    let body
    try {
      body = JSON.parse(text)
    } catch {
      return reply(400)
    }
    if (!body || typeof body !== 'object' || Array.isArray(body)) return reply(400)
    const { event, version, platform } = body
    if (!EVENTS.has(event) || !PLATFORMS.has(platform)) return reply(400)
    if (typeof version !== 'string' || !VERSION.test(version)) return reply(400)

    const verdict = await isRelease(env, version)
    if (verdict === 'no') return reply(400)
    if (verdict === 'unknown') return reply(503)

    const day = new Date().toISOString().slice(0, 10)
    await env.DB.prepare(
      `INSERT INTO pings (day, event, version, platform, count) VALUES (?, ?, ?, ?, 1)
       ON CONFLICT (day, event, version, platform) DO UPDATE SET count = count + 1`,
    )
      .bind(day, event, version, platform)
      .run()
    return reply(204)
  },

  async scheduled(_controller, env) {
    const day = new Date().toISOString().slice(0, 10)
    const response = await fetch(`https://api.github.com/repos/${REPO}/releases?per_page=100`, {
      headers: { 'User-Agent': 'lit-review-census', Accept: 'application/vnd.github+json' },
    })
    if (!response.ok) throw new Error(`GitHub answered ${response.status}`)
    const releases = await response.json()
    const statements = []
    for (const release of releases) {
      for (const asset of release.assets || []) {
        statements.push(
          env.DB.prepare(
            `INSERT INTO downloads (day, tag, asset, downloads) VALUES (?, ?, ?, ?)
             ON CONFLICT (day, tag, asset) DO UPDATE SET downloads = excluded.downloads`,
          ).bind(day, release.tag_name, asset.name, asset.download_count),
        )
      }
    }
    if (statements.length) await env.DB.batch(statements)
  },
}
