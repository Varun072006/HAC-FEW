import { useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, unwrap } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Banner, Button, Field, Input } from '../components/ui'

export default function Login() {
  const { login } = useAuth()
  const cfg = useQuery({ queryKey: ['auth-config'], queryFn: () => unwrap(api.GET('/auth/config')), retry: false })
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setError(null)
    try { await login(username.trim(), password) } catch (err) { setError(err instanceof Error ? err.message : 'Sign-in failed.') } finally { setBusy(false) }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1fr_480px]">
      <section className="hidden flex-col justify-between bg-navy p-12 text-white lg:flex" aria-hidden>
        <div className="flex items-center gap-3">
          <svg width="32" height="32" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#fff" /><path d="M16 6l8 4.6v9.2L16 24.4 8 19.8v-9.2z" fill="none" stroke="#1E3A5F" strokeWidth="2" strokeLinejoin="round" /><circle cx="16" cy="15.2" r="2.4" fill="#1E3A5F" /></svg>
          <span className="mono text-lg tracking-tight">HAC-FEW</span>
        </div>
        <div className="max-w-md">
          <p className="text-3xl font-semibold leading-tight tracking-tight">Agent workflows that stop and ask before they act.</p>
          <p className="mt-4 text-[15px] text-white/80">A supervisor plans. Department agents execute. Policy decides what runs, what waits for a human, and what is refused. Every step is traced and audited.</p>
        </div>
        <p className="mono text-xs text-white/60">Open-source · governed · observable</p>
      </section>

      <main className="flex items-center justify-center bg-canvas px-6 py-12">
        <div className="w-full max-w-sm">
          <h1 className="text-2xl">Sign in</h1>
          <p className="mt-1 text-sm text-ink-2">Use your organization account.</p>
          <form onSubmit={submit} className="mt-6 space-y-4">
            <Field label="Username" htmlFor="username">
              <Input id="username" autoComplete="username" autoFocus value={username} onChange={(e) => setUsername(e.target.value)} required />
            </Field>
            <Field label="Password" htmlFor="password">
              <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </Field>
            {error && <Banner tone="error">{error}</Banner>}
            <Button type="submit" variant="primary" busy={busy} className="w-full">Sign in</Button>
          </form>

          {cfg.data?.environment === 'development' && (cfg.data.dev_accounts?.length ?? 0) > 0 && (
            <div className="mt-8 rounded-md border border-line bg-surface p-4">
              <p className="text-[13px] font-medium">Development accounts</p>
              <p className="mt-0.5 text-xs text-ink-2">Seeded only in development. The password is <span className="mono">HACFEW_DEV_PASSWORD</span> (default in the README).</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(cfg.data.dev_accounts ?? []).map((u) => (
                  <button key={u} type="button" onClick={() => { setUsername(u); document.getElementById('password')?.focus() }}
                    className="mono rounded-sm border border-line-strong px-2 py-0.5 text-xs hover:bg-navy-tint">{u}</button>
                ))}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
