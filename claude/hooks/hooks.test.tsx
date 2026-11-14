import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

const URN = 'msg://agent/agent-mux/agt_me'

const mail = (id: string, attention: string, extra: object = {}) => ({
  id, from: 'msg://agent/agent-mux/tether', subject: `subject ${id}`, body: `BODY-${id} `.repeat(20), attention, ...extra,
})

// Stands for the engine beneath the mod in a plain local session: a fake watcher that
// prints `lines` once, a fake CLI that records its argv, a clock the test moves, and
// a prompt.submit bottom that records every prompt (text, context, origin).
const world = (on: On, env: Record<string, string>, lines: object[] = []) => {
  mock.env(on, env)
  const clock = mock.clock(on)
  const w = {
    clock,
    ran: [] as string[][],
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
  on('process.spawn', async function* () {
    w.spawned += 1
    if (w.spawned === 1 && lines.length) {
      yield { stream: 'stdout' as const, text: lines.map(l => JSON.stringify(l)).join('\n') + '\n' }
    }
    return { value: { code: 0, signal: null } }
  })
  on('process.run', (_, e) => {
    w.ran.push([...e.argv])
    return { value: { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('prompt.submit', (_, e) => {
    w.prompts.push({ text: e.text, context: e.context, origin: e.origin?.kind ?? 'none' })
    return { text: e.text, context: e.context }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  return w
}

const boot = ($: Engine) => $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
const userPrompt = ($: Engine, text: string) =>
  $.prompt.submit({ text, wait: false, origin: { kind: 'composer' } } as never)

test('a burst makes one pointer turn for action and human; FYI waits; read is marked read', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN }, [
    mail('a1', 'agent', { awaiting: '@archie' }),
    mail('h1', 'human'),
    mail('f1', 'none'),
    mail('r1', 'none', { kind: 'ack' }),
  ])
  await boot($)
  await w.clock.advance(2000)

  const turns = w.prompts.filter(p => p.origin === 'plugin')
  expect(turns.length).toBe(1)
  const turn = turns[0]?.text ?? ''
  expect(turn).toContain('2 new messages for this seat')
  expect(turn).toContain('Mail a1 from @tether → to @agt_me · attention: agent · awaiting: @archie')
  expect(turn).toContain('[HUMAN] Mail h1')
  for (const absent of ['f1', 'r1', 'BODY-', "YOU'VE GOT MAIL", 'mailbox skill']) {
    expect(turn).not.toContain(absent)
  }
  expect(w.ran).toEqual([['tether-remote', 'messages', 'read', 'r1', '--as', URN]])
  expect(w.toasts.length).toBe(1)
  expect(w.toasts[0]).toContain('Mail needs you')

  // The FYI rides on the user's next prompt as context (no turn), then is marked read.
  await userPrompt($, 'hello')
  await w.clock.advance(0)
  const mine = w.prompts.filter(p => p.origin === 'composer')
  expect(mine.length).toBe(1)
  expect(mine[0]?.context?.length).toBe(1)
  expect(mine[0]?.context?.[0]).toContain('kind="mailbox-fyi"')
  expect(mine[0]?.context?.[0]).toContain('@tether → @agt_me: subject f1 (f1)')
  expect(w.ran[1]).toEqual(['tether-remote', 'messages', 'read', 'f1', '--as', URN])

  // ...once: the prompt after carries nothing.
  await userPrompt($, 'again')
  expect(w.prompts.filter(p => p.origin === 'composer')[1]?.context).toBeUndefined()
})

test('the pane logs each message and the band counts waiting FYIs', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN }, [mail('f1', 'none'), mail('f2', 'none'), mail('r1', 'none', { kind: 'ack' })])
  await boot($)
  await w.clock.advance(2000)
  expect(w.prompts.length).toBe(0)

  const band = await $.ui.mount({ plugin: 'tether-mail', surface: 'terminal', component: 'AbovePrompt', props: { hasSurvey: false } } as never)
  expect((await band.find({ type: 'Text', text: /2 mail FYIs/ }))?.text).toContain('next prompt')
  await band.unmount()

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
  await w.clock.advance(2000)

  expect(w.ran).toEqual([['tether-remote', 'messages', 'read', 'k1', '--as', URN]])
  expect(w.prompts.length).toBe(0)
  await userPrompt($, 'hello')
  expect(w.prompts[0]?.context?.[0]).toContain('(q1)')
  expect(w.prompts[0]?.context?.[0]).not.toContain('(k1)')
})

test('an FYI does not ride on a prompt a plugin submitted', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN }, [mail('f1', 'none')])
  await boot($)
  await w.clock.advance(2000)

  await $.prompt.submit({ text: 'x', wait: false } as never)

  expect(w.prompts.length).toBe(1)
  expect(w.prompts[0]?.context).toBeUndefined()
  expect(w.ran).toEqual([])
})

test('a hub-hosted session starts no watcher and attaches nothing', async ($, on) => {
  const w = world(on, { TETHER_AGENT_URN: URN, TETHER_HOSTED_SESSION: 'sess-1' }, [mail('a1', 'agent')])
  await boot($)
  await w.clock.advance(2000)
  await userPrompt($, 'hello')

  expect(w.spawned).toBe(0)
  expect(w.prompts.length).toBe(1)
  expect(w.prompts[0]?.context).toBeUndefined()
})
