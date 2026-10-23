// dsh-harness-lab · 评测执行器（DSH 插件，替换 headless 配置档里的 headless-runner）
//
// 为什么要换：原版 headless 在 Agent 空闲时就退出 —— 进程里的后台任务（插件用 ctx.jobs.start 起的）跟着没了；
// 有的插件（比如等这一轮说完才启动子进程的）在 headless 下根本跑不起来。原版也不给新会话挂 Agent 预设。
// 这个执行器在同一个进程里：
//   1. 新会话照网页版（session-controller 的 composeAgent）挂上默认预设
//   2. 按脚本连着发几句话（模拟用户的回复）
//   3. 每发一句：等 Agent 空闲 → 这个会话还有后台任务在跑就等它跑完 → 等唤醒的那一轮也空闲 →
//      会话 1.5 秒内没有新事件，才算这一句结束
//   4. 全部发完：flush 会话日志，往 stdout 写一行行 JSON（会话 id、预设、每句用了多久、结束时后台任务的状态），然后退出
// 打分不靠这里的输出，靠会话日志（session.v4.jsonl.zstd）和工作区状态（见 eval/）。
//
// 脚本（命令行的「任务」位置给脚本文件路径）：
//   { "turns": ["第一句", "第二句", …], "turnTimeoutSec": 900 }
//   cd <评测工作区> && dsh --profile headless <脚本.json>
import { createRequire } from 'node:module'
import { randomUUID } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

export const name = 'dsh-lab-eval-runner'
export const inject = ['agentDefaultModel', 'agents', 'sessions', 'jobs']

// 插件文件不在 DSH 的安装目录里，直接 import 找不到 @deepseek-ai/* —— 从 DSH 自己的启动文件（dsh/lib/bin.js）所在的安装去解析；
// 也可以用 DSH_LAB_DSH_ENTRY 指定那个文件
const entry = process.env.DSH_LAB_DSH_ENTRY ?? process.argv[1]
const req = createRequire(entry)
const load = async (pkg) => import(pathToFileURL(req.resolve(pkg)).href)

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const ACTIVE = new Set(['running', 'stopping'])

function line(obj) { process.stdout.write(JSON.stringify(obj) + '\n') }

/** 等这一句彻底结束：Agent 空闲、没有在跑的后台任务、会话 1.5 秒内没新事件。超时返回 false。 */
async function settle(ctx, agent, sessionId, deadline) {
  for (;;) {
    if (Date.now() > deadline) return false
    await agent.whenIdle()
    const active = ctx.jobs.list(sessionId).filter((j) => ACTIVE.has(j.status))
    if (active.length > 0) {
      for (const j of active) {
        const left = deadline - Date.now()
        if (left <= 0) return false
        try { await ctx.jobs.wait(j.id, left, sessionId) } catch { /* 等超时 / 已经结束：下一圈再看 */ }
      }
      continue
    }
    const seq = agent.session.seq
    await sleep(1500)
    if (agent.session.seq === seq && ctx.jobs.list(sessionId).every((j) => !ACTIVE.has(j.status))) return true
  }
}

async function run(ctx, config, exit) {
  await ctx.get('loader')?.await()
  const script = JSON.parse(readFileSync(config.script, 'utf8'))
  const turns = Array.isArray(script.turns) ? script.turns.filter((t) => typeof t === 'string' && t.trim()) : []
  if (turns.length === 0) throw new Error('dsh-lab-eval-runner：脚本里没有 turns')
  const turnTimeoutMs = (Number(script.turnTimeoutSec) || 900) * 1000
  const { installModelSelection } = await load('@deepseek-ai/dsh-agent')
  const { createUserMessage } = await load('@deepseek-ai/dsh-llm')
  const selection = ctx.agentDefaultModel.currentSelection()
  const sessionId = `session-${randomUUID()}`
  const fs = ctx.get('fs')
  const cwd = fs === undefined ? process.cwd() : fs.processPath(await fs.resolve('.'))
  // 预设：会话头写预设 id、setup 里挂上（不这样做，Agent 拿到的是配置档顶层的那一套工具）
  const presets = ctx.get('agentPresets')
  const presetId = presets === undefined ? undefined : (await presets.resolve(undefined)).id
  const { agent } = await ctx.agents.create({
    sessionId, meta: { cwd, ...(presetId === undefined ? {} : { agentPreset: presetId }) },
    agentOptions: { provider: selection.provider, model: selection.model },
    // 不能返回 installModelSelection 的返回值：DSH 会对 setup 的返回值调 .commit()
    setup: async (agentCtx) => {
      installModelSelection(agentCtx, { current: selection, assembled: undefined })
      if (presetId !== undefined) await presets.mount(agentCtx, presetId)
    },
  })
  await agent.whenIdle()
  line({ type: 'session', sessionId, cwd, model: `${selection.provider}/${selection.model}`, preset: presetId ?? null })
  let ok = true
  for (let i = 0; i < turns.length; i++) {
    const t0 = Date.now()
    agent.followup(createUserMessage({ content: [{ type: 'text', text: turns[i] }], source: { kind: 'user' } }))
    const settled = await settle(ctx, agent, sessionId, t0 + turnTimeoutMs)
    const jobs = ctx.jobs.list(sessionId).map((j) => ({ id: j.id, kind: j.kind, label: j.label, status: j.status }))
    line({ type: 'turn', index: i, seconds: Math.round((Date.now() - t0) / 100) / 10, settled, jobs })
    if (!settled) { ok = false; break }
  }
  await ctx.sessions.flush(agent.session)
  line({ type: 'done', ok })
  exit(ok ? 0 : 1)
}

export function apply(ctx, config) {
  const exit = ctx.get('appExit')
  if (exit === undefined) throw new Error('dsh-lab-eval-runner：要由 dsh 启动器启动（ctx.appExit）')
  run(ctx, config, exit).catch((e) => {
    process.stderr.write(`dsh-lab-eval-runner: ${e?.stack ?? e}\n`)
    line({ type: 'error', message: String(e?.message ?? e) })
    exit(1)
  })
}
