// The mod's $.state contract (claude plugin validate holds the module to it).

export type MailClass = 'read' | 'fyi' | 'action' | 'human'

// One FYI waiting to ride along on the user's next prompt.
export type FyiItem = { id: string; line: string }

// One row of the mail pane's log.
export type LogRow = { at: number; cls: MailClass | 'note'; text: string }

declare module 'claude-code' {
  interface PluginState {
    'tether-mail': { fyi: Shaped<FyiItem[]>; log: Shaped<LogRow[]> }
  }
}
