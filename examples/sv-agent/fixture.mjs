// examples/sv-agent · 造起始状态：直接用插件自己导出的函数写，格式和真的一样。
//   node fixture.mjs <spec.json>
// spec：{ "store": <评测数据目录>/snapshots, "projects": [ { "dir", "name", "status", "notes": [..],
//          "files": { "相对路径": "内容" | null(空文件) }, "versions": [ { "id", "note", "files": {..}, "seal": true } ] } ] }
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { readFileSync } from 'node:fs'

const SV = process.env.SV_BRIDGE ?? (() => { throw new Error('要设 SV_BRIDGE（sv-bridge 仓库的路径）') })()
const P = await import(pathToFileURL(join(SV, 'dsh/plugins/sv-project/index.js')).href)
const A = await import(pathToFileURL(join(SV, 'dsh/plugins/sv-artifact/index.js')).href)
const spec = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const stamp = '2026-10-20 12:00'

const put = (base, files) => {
  for (const [rel, body] of Object.entries(files ?? {})) {
    const f = join(base, rel)
    mkdirSync(dirname(f), { recursive: true })
    writeFileSync(f, body ?? '', 'utf8')
  }
}

for (const pj of spec.projects ?? []) {
  mkdirSync(pj.dir, { recursive: true })
  P.writeProject(pj.dir, { schema: 'sv-agent/project@1', name: pj.name, kind: pj.kind ?? 'cover', created: stamp, updated: stamp,
    source: pj.source ?? '评测台造的', status: pj.status ?? '刚建', external: [], notes: pj.notes ?? [] })
  put(pj.dir, pj.files)
  if (pj.versions?.length) {
    const m = A.readManifest(spec.store, pj.dir)
    for (const v of pj.versions) {
      put(join(pj.dir, v.id), v.files)
      m.versions.push({ id: v.id, folder: v.id, created: stamp, by: 'agent', note: v.note ?? '', sealed: null, files: {}, discarded: null })
      if (v.seal !== false) A.sealVersion(pj.dir, m, v.id, v.note ?? '评测台封版')
    }
    A.writeManifest(spec.store, pj.dir, m)
  }
}
console.log(JSON.stringify({ ok: true, projects: (spec.projects ?? []).map((p) => p.name) }))
