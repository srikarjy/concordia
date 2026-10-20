import { createClient, type Session } from '@supabase/supabase-js';
import { useEffect, useState } from 'react';

export const supabase = createClient('https://zoosebdmsaflxcqtyyho.supabase.co', 'sb_publishable_rnbu2YnU10B0pOL3jHBr4A_54sdwAha');
export function useProteinSession() {
  const [session, setSession] = useState<Session | null>(null);
  useEffect(() => {
    let active = true;
    void supabase.auth.getSession().then(({ data }) => { if (active) setSession(data.session); });
    const { data } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => { active = false; data.subscription.unsubscribe(); };
  }, []);
  return session;
}
export function ProteinSignIn() {
  const session = useProteinSession();
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  if (session) return <p>Signed in as {session.user.email} <button type="button" onClick={() => void supabase.auth.signOut()}>Sign out</button></p>;
  return <form onSubmit={async e => {
    e.preventDefault(); setBusy(true);
    try {
      const { error } = await supabase.auth.signInWithOtp({ email: email.trim(), options: { emailRedirectTo: window.location.origin + window.location.pathname } });
      setMessage(error ? error.message : 'Open the sign-in link in your email, then return here.');
    } catch { setMessage('Sign-in service unavailable. Please try again later.'); }
    finally { setBusy(false); }
  }}><label>Email for protein workspace <input type="email" required value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" /></label><button disabled={busy}>{busy ? 'Sending…' : 'Email sign-in link'}</button><p role="status">{message}</p></form>;
}
