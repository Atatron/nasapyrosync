// Vercel build step (see vercel.json): upload the full-archive parts in deploy/blob/db to Vercel Blob.
// Runs only when the project has a Blob store connected (BLOB_READ_WRITE_TOKEN set by Vercel).
// Parts already in the store with the right size are skipped, so a normal redeploy uploads nothing.
// The token is never printed.
import { readFileSync, statSync, createReadStream } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { list, put } from '@vercel/blob'

const here = dirname(fileURLToPath(import.meta.url))
const manifest = JSON.parse(readFileSync(join(here, 'manifest.json'), 'utf8'))
const token = process.env.BLOB_READ_WRITE_TOKEN

if (!token) {
  console.log('[pyrosync blob] No Blob store connected (BLOB_READ_WRITE_TOKEN missing): skipping upload. The demo falls back to the bundled slim database.')
  process.exit(0)
}

const { blobs } = await list({ prefix: manifest.prefix, token, limit: 100 })
const have = new Map(blobs.map((b) => [b.pathname, b.size]))
for (const p of manifest.parts) {
  const pathname = manifest.prefix + p.name
  const file = join(here, 'db', p.name)
  if (statSync(file).size !== p.bytes) throw new Error(`${p.name}: size on disk does not match manifest.json`)
  if (have.get(pathname) === p.bytes) { console.log(`[pyrosync blob] ${pathname} already stored, skipped`); continue }
  const t = Date.now()
  await put(pathname, createReadStream(file), {
    access: 'public', token, addRandomSuffix: false, allowOverwrite: true, multipart: true,
    contentType: 'application/octet-stream', cacheControlMaxAge: 31536000,
  })
  console.log(`[pyrosync blob] uploaded ${pathname} (${(p.bytes / 1e6).toFixed(1)} MB) in ${((Date.now() - t) / 1000).toFixed(1)} s`)
}
console.log('[pyrosync blob] full archive is in the Blob store')
