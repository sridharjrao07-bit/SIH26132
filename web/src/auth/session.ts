// Auth: Supabase issues tokens, FastAPI verifies them (API_CONTRACT §1). The backend never
// issues tokens. supabase-js is loaded lazily so the public price flow never downloads it.
//
// Dev mode (VITE_DEV_AUTH=1): the mock's /__dev/token mints a JWT-shaped token for a role.
// That token is only accepted by the mock, never by the real API.
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { SupabaseClient } from '@supabase/supabase-js';

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const SUPABASE_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;
export const supabaseConfigured = Boolean(SUPABASE_URL && SUPABASE_KEY);
export const devAuthEnabled = import.meta.env.VITE_DEV_AUTH === '1';

let client: Promise<SupabaseClient> | null = null;
export function supabase(): Promise<SupabaseClient> {
  if (!supabaseConfigured) return Promise.reject(new Error('Supabase is not configured'));
  client ??= import('@supabase/supabase-js').then(({ createClient }) => {
    const c = createClient(SUPABASE_URL!, SUPABASE_KEY!, { auth: { persistSession: true, autoRefreshToken: true } });
    c.auth.onAuthStateChange((_e, s) => useSession.getState()._set(s ? { userId: s.user.id, mode: 'supabase' } : null));
    return c;
  });
  return client;
}

interface SessionState {
  userId: string | null;
  mode: 'supabase' | 'dev' | null;
  devToken: string | null;
  _set: (s: { userId: string; mode: 'supabase' | 'dev'; devToken?: string } | null) => void;
}

export const useSession = create<SessionState>()(
  persist(
    (set) => ({
      userId: null, mode: null, devToken: null,
      _set: (s) => set(s ? { userId: s.userId, mode: s.mode, devToken: s.devToken ?? null } : { userId: null, mode: null, devToken: null }),
    }),
    { name: 'kb-session', version: 1 },
  ),
);

export async function getToken(): Promise<string | null> {
  const { mode, devToken } = useSession.getState();
  if (mode === 'dev') return devToken;
  if (mode === 'supabase') {
    const { data } = await (await supabase()).auth.getSession();
    return data.session?.access_token ?? null;
  }
  return null;
}

/** Called once on a 401: refresh, and tell the client whether to retry. */
export async function refreshSession(): Promise<boolean> {
  if (useSession.getState().mode !== 'supabase') return false;
  const { data, error } = await (await supabase()).auth.refreshSession();
  if (error || !data.session) { useSession.getState()._set(null); return false; }
  return true;
}

export async function signInWithPassword(email: string, password: string) {
  const { data, error } = await (await supabase()).auth.signInWithPassword({ email, password });
  if (error) throw error;
  useSession.getState()._set({ userId: data.user.id, mode: 'supabase' });
}

/** Sign-up can only ever produce a farmer (API_CONTRACT §1 Roles). */
export async function signUp(email: string, password: string) {
  const { data, error } = await (await supabase()).auth.signUp({ email, password });
  if (error) throw error;
  if (data.session && data.user) useSession.getState()._set({ userId: data.user.id, mode: 'supabase' });
  return { needsConfirmation: !data.session };
}

export async function devSignIn(role: 'farmer' | 'buyer' | 'fpo') {
  const res = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? ''}/__dev/token?role=${role}`);
  if (!res.ok) throw new Error(`dev token failed (${res.status})`);
  const { token, sub } = (await res.json()) as { token: string; sub: string };
  useSession.getState()._set({ userId: sub, mode: 'dev', devToken: token });
}

export async function signOut() {
  if (useSession.getState().mode === 'supabase') await (await supabase()).auth.signOut();
  useSession.getState()._set(null);
}
