const args = process.argv.slice(2)
const cliMarker = args.indexOf('--cli-args')
const launcherArgs = cliMarker >= 0 ? args.slice(0, cliMarker) : args
const cliArgs = cliMarker >= 0 ? args.slice(cliMarker + 1) : []

function option(name: string, fallback: string): string {
  const index = launcherArgs.indexOf(name)
  return index >= 0 ? launcherArgs[index + 1] ?? fallback : fallback
}

const port = Number.parseInt(option('--port', '4317'), 10)
const noBrowser = launcherArgs.includes('--no-browser')
const noForcedSessionMemory = launcherArgs.includes(
  '--no-forced-session-memory',
)
const waitForDebugger = launcherArgs.includes('--wait-for-debugger')
const dashboardUrl = `http://127.0.0.1:${port}`
const env = {
  ...process.env,
  CLAUDE_CODE_CONTEXT_INSPECTOR: '1',
  CLAUDE_CODE_CONTEXT_INSPECTOR_RESET: '1',
  CLAUDE_CODE_CONTEXT_INSPECTOR_BREAKPOINTS: option(
    '--breakpoints',
    'instructions_loaded,agent_memory_loaded,memory_recall_resolved,session_memory_updated,api_request_ready',
  ),
  CONTEXT_INSPECTOR_PORT: String(port),
}

if (!noForcedSessionMemory) {
  Object.assign(env, {
    CLAUDE_CODE_CONTEXT_INSPECTOR_FORCE_SESSION_MEMORY: '1',
    CLAUDE_CODE_CONTEXT_INSPECTOR_SM_INIT_TOKENS: '1',
    CLAUDE_CODE_CONTEXT_INSPECTOR_SM_UPDATE_TOKENS: '1',
    CLAUDE_CODE_CONTEXT_INSPECTOR_SM_TOOL_CALLS: '1',
  })
}

const dashboard = Bun.spawn(
  [process.execPath, 'run', 'scripts/context-inspector/server.ts', '--port', String(port)],
  {
    cwd: process.cwd(),
    env,
    stdout: 'ignore',
    stderr: 'inherit',
  },
)

async function waitForDashboard(): Promise<void> {
  for (let attempt = 0; attempt < 40; attempt++) {
    if (dashboard.exitCode !== null) {
      throw new Error(`Inspector 网页进程已退出，退出码：${dashboard.exitCode}`)
    }
    try {
      const response = await fetch(`${dashboardUrl}/api/health`)
      if (response.ok) return
    } catch {
      // The server normally needs only one or two attempts to bind the port.
    }
    await Bun.sleep(200)
  }
  throw new Error(`Inspector 网页在 8 秒内未启动：${dashboardUrl}`)
}

try {
  await waitForDashboard()
  console.log(`\nContext Memory Inspector 已启动：${dashboardUrl}`)
  console.log('CLI 退出后，网页服务会自动关闭。\n')

  if (!noBrowser) {
    Bun.spawn(['cmd.exe', '/c', 'start', '', dashboardUrl], {
      stdin: 'ignore',
      stdout: 'ignore',
      stderr: 'ignore',
    }).unref()
  }

  const cliCommand = [process.execPath]
  if (waitForDebugger) {
    cliCommand.push('--inspect-wait')
    console.log('CLI 正在等待调试器连接（Bun inspector 默认端口 6499）…')
  }
  cliCommand.push('run', 'src/entrypoints/cli.tsx', ...cliArgs)

  const cli = Bun.spawn(cliCommand, {
    cwd: process.cwd(),
    env,
    stdin: 'inherit',
    stdout: 'inherit',
    stderr: 'inherit',
  })
  const exitCode = await cli.exited
  if (exitCode !== 0) process.exitCode = exitCode
} finally {
  dashboard.kill()
  await dashboard.exited
}
