import { readFile } from 'fs/promises'
import { join, resolve } from 'path'

type InspectorEvent = {
  version: number
  id: string
  runId: string
  sequence: number
  timestamp: string
  stage: string
  pid: number
  cwd: string
  data: unknown
}

function argument(name: string): string | undefined {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : undefined
}

const port = Number.parseInt(
  argument('--port') ?? process.env.CONTEXT_INSPECTOR_PORT ?? '4317',
  10,
)
const dataDir = resolve(
  argument('--dir') ??
    process.env.CLAUDE_CODE_CONTEXT_INSPECTOR_DIR ??
    join(process.cwd(), '.claude', 'context-inspector'),
)
const eventsPath = join(dataDir, 'events.jsonl')
const htmlPath = join(import.meta.dir, 'index.html')

async function readEvents(): Promise<InspectorEvent[]> {
  try {
    const content = await readFile(eventsPath, 'utf8')
    return content
      .split(/\r?\n/)
      .filter(Boolean)
      .flatMap(line => {
        try {
          return [JSON.parse(line) as InspectorEvent]
        } catch {
          // The writer may be between append syscalls; ignore an incomplete line.
          return []
        }
      })
  } catch {
    return []
  }
}

const server = Bun.serve({
  hostname: '127.0.0.1',
  port,
  async fetch(request) {
    const url = new URL(request.url)
    if (url.pathname === '/api/events') {
      const events = await readEvents()
      return Response.json({ dataDir, events })
    }
    if (url.pathname === '/api/health') {
      return Response.json({ ok: true, dataDir, eventsPath })
    }
    if (url.pathname === '/' || url.pathname === '/index.html') {
      return new Response(Bun.file(htmlPath), {
        headers: { 'content-type': 'text/html; charset=utf-8' },
      })
    }
    return new Response('Not found', { status: 404 })
  },
})

console.log(`Context Memory Inspector: http://${server.hostname}:${server.port}`)
console.log(`Reading snapshots from: ${eventsPath}`)
