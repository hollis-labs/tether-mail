import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

const URN = 'msg://agent/agent-mux/agt_me'
const SDIR = '/s/k'
const LAUNCH = [
  '#!/usr/bin/env bash',
  'export TETHER_AGENT_NAME=architect',
  'export TETHER_AGENT_LABEL=Archie',
  `export TETHER_AGENT_URN=${URN}`,
  `cd ${SDIR}`,
  `exec claude --setting-sources project,local --settings ${SDIR}/claude-settings.json --strict-mcp-config --mcp-config ${SDIR}/claude-mcp.json --plugin-dir /a/plugins/tether-mail/claude --dangerously-skip-permissions -n Archie -- 'boot prompt' "$@"`,
].join('\n')

const mail = (id: string, attention: string, extra: object = {}) => ({
  id, from: 'msg://agent/agent-mux/tether', subject: `subject ${id}`, body: `BODY-${id} `.repeat(20), attention, ...extra,
})

type Run = { exitCode: number; stdout: string; stderr: string; isStdoutTruncated: boolean; isStderrTruncated: boolean }
const ran = (exitCode: number, stdout = '', stderr = ''): Run =>
  ({ exitCode, stdout, stderr, isStdoutTruncated: false, isStderrTruncated: false })
// What `claude -p --output-format json --json-schema` prints.
const sidecarSays = (r: object) => ran(0, JSON.stringify({ type: 'result', is_error: false, result: '', structured_output: r }))
const HANDLED = { handled: true, summary: 'replied to @archie (skills list)', replied_to: '@archie', needs_human: false, needs_main_session: false }

// Stands for the engine beneath the mod in a plain local session: a fake watcher that
// prints `lines` once, a fake CLI that records its argv, a stubbed `claude -p` sidecar,
// the seat's launch.sh, a clock the test moves, and a prompt.submit bottom that records
// every prompt (text, context, origin).
const world = (
  on: On,
  env: Record<string, string>,
  lines: object[] = [],
  sidecar: () => Run | { deny: string } = () => sidecarSays(HANDLED),
) => {
  mock.env(on, { AGENT_SESSION_DIR: SDIR, ...env })
  const clock = mock.clock(on)
  const w = {
    clock,
    ran: [] as string[][],
    sidecars: [] as { argv: string[]; cwd?: string; env?: Record<string, string>; timeoutMs?: number }[],
    prompts: [] as { text: string; context?: readonly string[]; origin: string }[],
    toasts: [] as string[],
    spawned: 0,
  }
  on('command.register', () => ({ value: { command: 'mail' } }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.toast', (_, e) => {
    w.toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('fs.read', (_, e) => {
    if (e.path === `${SDIR}/launch.sh`) return { value: LAUNCH }
    throw new Error(`ENOENT ${e.path}`)
  })
  on('fs.exists', () => ({ value: false }))
  on('process.spawn', async function* () {
    w.spawned += 1
    if (w.spawned === 1 && lines.length) {
      yield { stream: 'stdout' as const, text: lines.map(l => JSON.stringify(l)).join('\n') + '\n' }
    }
    return { value: { code: 0, signal: null } }
  })
  on('process.run', (_, e) => {
    if (e.argv[0] === 'claude') {
      w.sidecars.push({ argv: [...e.argv], cwd: e.init?.cwd, env: e.init?.env, timeoutMs: e.init?.timeoutMs })
      const r = sidecar()
      return 'deny' in r ? r : { value: r }
    }
    w.ran.push([...e.argv])
    return { value: ran(0) }
  })
  on('prompt.submit', (_, e) => {
    w.prompts.push({ text: e.text, context: e.context, origin: e.origin?.kind ?? 'none' })
    return { text: e.text, context: e.context }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  return w
}

const boot = ($: Engine) => $.session.start({ cwd: SDIR, surface: 'terminal', isInteractive: true })
const userPrompt = ($: Engine, text: string) =>
  $.prompt.submit({ text, wait: false, origin: { kind: 'composer' } } as never)
const settle = async (w: { clock: { advance: (ms: number) => Promise<unknown> } }) => {
  await w.clock.advance(2000)
  for (let i = 0; i < 5; i++) await w.clock.advance(0)
}
const bandText = async ($: Engine) => {
  const band = await $.ui.mount({ plugin: 'tether-mail', surface: 'terminal', component: 'AbovePrompt', props: { hasSurvey: false } } as never)
  const texts = await band.findAll({ type: 'Text' })
  await band.unmount()
  return texts.map(t => t.text)
}
const paneHas = async ($: Engine, re: RegExp) => {
  const pane = await $.ui.mount({
    plugin: 'tether-mail', surface: 'terminal', component: 'Pane', requestId: 'tether-mail',
    props: { title: 'Mail', isFocused: false, bodyColumns: 80, placement: 'dock', scroll: { offset: 0, bodyRows: 20 }, view: {} },
  } as never)
  const found = await pane.find({ type: 'Text', text: re })
  await pane.unmount()
  return found !== undefined
}
const turns = (w: ReturnType<typeof world>) => w.prompts.filter(p => p.origin === 'plugin')

test('action mail goes to one sidecar, launched like the seat minus this plugin; the chat gets a band line, no turn', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN, TETHER_AGENT_LABEL: 'Archie', TETHER_AGENT_NAME: 'architect' }, [
    mail('a1', 'agent'),
    mail('a2', 'agent'),
    mail('f1', 'none'),
    mail('r1', 'none', { kind: 'ack' }),
  ])
  await boot($)
  await settle(w)

  expect(turns(w).length).toBe(0)
  expect(w.sidecars.length).toBe(1)
  const sc = w.sidecars[0]!
  expect(sc.cwd).toBe(SDIR)
  expect(sc.timeoutMs).toBe(600000)
  expect(sc.argv.slice(0, 9)).toEqual([
    'claude', '--setting-sources', 'project,local', '--settings', `${SDIR}/claude-settings.json`,
    '--strict-mcp-config', '--mcp-config', `${SDIR}/claude-mcp.json`, '--dangerously-skip-permissions',
  ])
  expect(sc.argv).not.toContain('/a/plugins/tether-mail/claude')
  expect(sc.argv).toContain('--json-schema')
  expect(sc.argv[sc.argv.indexOf('--model') + 1]).toBe('sonnet')
  const prompt = sc.argv[sc.argv.length - 1] ?? ''
  expect(prompt).toContain('Handle these Tether mail ids with the mailbox skill: a1, a2')
  expect(prompt).not.toContain('BODY-')
  expect(sc.env).toEqual(expect.objectContaining({
    TETHER_AGENT_URN: URN, TETHER_AGENT_LABEL: 'Archie', TETHER_AGENT_NAME: 'architect',
    TETHER_MAIL_CLI: 'tether-remote', TETHER_MAIL_SIDECAR_CHILD: '1',
  }))
  // The read ack is marked read by the mod; the action mail is the sidecar's to mark.
  expect(w.ran).toEqual([['tether-remote', 'messages', 'read', 'r1', '--as', URN]])

  const band = await bandText($)
  expect(band).toContain('📬 handled 2 mail: replied to @archie (skills list)')
  expect(band.some(t => t.includes('1 mail FYI'))).toBe(true)

  // The handled line has been seen once the user prompts again; the FYI rides along.
  await userPrompt($, 'hello')
  await w.clock.advance(0)
  expect(w.prompts.filter(p => p.origin === 'composer')[0]?.context?.[0]).toContain('(f1)')
  expect(await bandText($)).toEqual([])
})

test('TETHER_MAIL_SIDECAR_MODEL picks the sidecar model', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN, TETHER_MAIL_SIDECAR_MODEL: 'haiku' }, [mail('a1', 'agent')])
  await boot($)
  await settle(w)
  const argv = w.sidecars[0]?.argv ?? []
  expect(argv[argv.indexOf('--model') + 1]).toBe('haiku')
})

test('a failed sidecar falls back to one compact pointer turn; why is in the pane', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN }, [mail('a1', 'agent', { from_handle: 'archie' })], () => ran(1, '', 'boom'))
  await boot($)
  await settle(w)

  expect(w.sidecars.length).toBe(1)
  const t = turns(w)
  expect(t.length).toBe(1)
  expect(t[0]?.text).toBe('📬 subject a1 · from @archie · /mail')
  expect(t[0]?.context).toBeUndefined()
  expect(await paneHas($, /pointer sent to this session \(a1\): sidecar failed: exit 1: boom/)).toBe(true)
})

test('a timed-out sidecar falls back the same way', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN }, [mail('a1', 'agent')], () => ({ deny: 'process timed out' }))
  await boot($)
  await settle(w)
  expect(turns(w).length).toBe(1)
  expect(await paneHas($, /sidecar failed: timed out after 10 min/)).toBe(true)
})

test('needs_main_session makes a compact pointer turn', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN }, [mail('a1', 'agent')], () =>
    sidecarSays({ handled: false, summary: 'big refactor asked', needs_human: false, needs_main_session: true }))
  await boot($)
  await settle(w)
  const t = turns(w)
  expect(t.length).toBe(1)
  expect(t[0]?.text).toBe('📬 subject a1 · from @tether · /mail')
  expect(await paneHas($, /needs this session: big refactor asked/)).toBe(true)
})

test("needs_human from the sidecar is treated as human: band and toast, no turn", async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN }, [mail('a1', 'agent')], () =>
    sidecarSays({ handled: false, summary: 'wants a prod approval', needs_human: true, needs_main_session: false }))
  await boot($)
  await settle(w)
  expect(turns(w).length).toBe(0)
  expect(w.toasts.length).toBe(1)
  expect(await bandText($)).toContain('📬 [@tether → you] subject a1 · /mail')
})

test('human mail: band and toast, no turn, no sidecar; read only when opened in /mail', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN }, [mail('h1', 'human', { from_handle: 'pm' })])
  await boot($)
  await settle(w)

  expect(w.prompts.length).toBe(0)
  expect(w.sidecars.length).toBe(0)
  expect(w.toasts).toEqual(['Mail needs you: @pm: subject h1 · /mail'])
  expect(await bandText($)).toEqual(['📬 [@pm → you] subject h1 · /mail'])
  expect(w.ran).toEqual([])

  // A user prompt neither carries it nor marks it read.
  await userPrompt($, 'hello')
  expect(w.prompts[0]?.context).toBeUndefined()
  expect(w.ran).toEqual([])

  const r = await $.command.run({ command: 'mail', args: '' } as never)
  expect((r as { text?: string }).text).toContain('1 message for you marked read')
  expect(w.ran).toEqual([['tether-remote', 'messages', 'read', 'h1', '--as', URN]])
  expect(await bandText($)).toEqual([])
})

test('TETHER_MAIL_SIDECAR=0 keeps the compact pointer turn and starts no sidecar', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN, TETHER_MAIL_SIDECAR: '0' }, [mail('a1', 'agent'), mail('h1', 'human')])
  await boot($)
  await settle(w)
  expect(w.sidecars.length).toBe(0)
  const t = turns(w)
  expect(t.length).toBe(1)
  expect(t[0]?.text).toBe('📬 subject a1 · from @tether · /mail')
  expect(t[0]?.text).not.toContain('h1')
  expect(w.toasts.length).toBe(1)
})

test('nothing that reaches the main session is a boxed envelope', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN, TETHER_MAIL_SIDECAR: '0' }, [mail('a1', 'agent'), mail('h1', 'human'), mail('f1', 'none')])
  await boot($)
  await settle(w)
  await userPrompt($, 'hello')
  const all = [...w.prompts.flatMap(p => [p.text, ...(p.context ?? [])]), ...w.toasts, ...(await bandText($))]
  expect(all.length).toBeGreaterThan(2)
  for (const s of all) {
    expect(s).not.toContain("YOU'VE GOT MAIL")
    expect(s).not.toMatch(/[┌┐└┘│├┤]/)
    expect(s).not.toContain('BODY-')
  }
})

test('the pane logs each message and the band counts waiting FYIs', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN }, [mail('f1', 'none'), mail('f2', 'none'), mail('r1', 'none', { kind: 'ack' })])
  await boot($)
  await settle(w)
  expect(w.prompts.length).toBe(0)

  expect((await bandText($)).some(t => /2 mail FYIs .*next prompt/.test(t))).toBe(true)

  const pane = await $.ui.mount({
    plugin: 'tether-mail', surface: 'terminal', component: 'Pane', requestId: 'tether-mail',
    props: { title: 'Mail', isFocused: false, bodyColumns: 80, placement: 'dock', scroll: { offset: 0, bodyRows: 20 }, view: {} },
  } as never)
  expect(await pane.find({ type: 'Text', text: /fyi .*\(f2\)/ })).toBeDefined()
  expect(await pane.find({ type: 'Text', text: /read .*\(r1\)/ })).toBeDefined()
  await pane.unmount()
})

test('a model `read` is never marked read unseen; a pure ack is', async ($, on) => {
  on('model.complete', () => ({ value: { isAnswered: true, text: 'read | looks like thanks', usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }))
  const w = world(on, { TETHER_AGENT_URN: URN }, [
    { id: 'q1', from: 'msg://agent/agent-mux/tether', subject: 'thanks', body: 'thanks! also, can you rotate the token?', kind: 'request' },
    { id: 'k1', from: 'msg://agent/agent-mux/tether', subject: 'Re: x', body: 'Noted, thanks!', kind: 'response' },
  ])
  await boot($)
  await settle(w)

  expect(w.ran).toEqual([['tether-remote', 'messages', 'read', 'k1', '--as', URN]])
  expect(w.prompts.length).toBe(0)
  await userPrompt($, 'hello')
  expect(w.prompts[0]?.context?.[0]).toContain('(q1)')
  expect(w.prompts[0]?.context?.[0]).not.toContain('(k1)')
})

test('an FYI does not ride on a prompt a plugin submitted', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN }, [mail('f1', 'none')])
  await boot($)
  await settle(w)

  await $.prompt.submit({ text: 'x', wait: false } as never)

  expect(w.prompts.length).toBe(1)
  expect(w.prompts[0]?.context).toBeUndefined()
  expect(w.ran).toEqual([])
})

test('a hub-hosted session starts no watcher and attaches nothing', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN, TETHER_HOSTED_SESSION: 'sess-1' }, [mail('a1', 'agent')])
  await boot($)
  await settle(w)
  await userPrompt($, 'hello')

  expect(w.spawned).toBe(0)
  expect(w.prompts.length).toBe(1)
  expect(w.prompts[0]?.context).toBeUndefined()
})

test('inside a sidecar the mod stands down: no watcher, no recursion', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN, TETHER_MAIL_SIDECAR_CHILD: '1' }, [mail('a1', 'agent')])
  await boot($)
  await settle(w)
  expect(w.spawned).toBe(0)
  expect(w.sidecars.length).toBe(0)
  expect(w.prompts.length).toBe(0)
})
