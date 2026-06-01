import { useState } from 'react';
import { AlertCircle, CheckCircle2, KeyRound, LoaderCircle } from 'lucide-react';
import { getErrorMessage, resetPassword } from '../api/client';
import { Button, PageShell, Panel, TextField } from './ui';

export const ResetPassword = () => {
    const [password, setPassword] = useState('');
    const [saving, setSaving] = useState(false);
    const [msg, setMsg] = useState('');
    const [error, setError] = useState('');

    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setMsg('');

        if (!token) {
            setError('Invalid or missing token');
            return;
        }

        setSaving(true);
        try {
            await resetPassword(token, password);
            setMsg('Password reset successfully. You can now log in.');
            setPassword('');
        } catch (err) {
            setError(getErrorMessage(err, 'Failed to reset password'));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="min-h-screen bg-[var(--page)] text-[var(--ink)]">
            <PageShell className="flex min-h-screen max-w-xl items-center">
                <Panel className="w-full p-6 sm:p-8">
                    <div className="mb-6 flex items-start gap-3">
                        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-[var(--accent-soft)] text-[var(--accent)]">
                            <KeyRound size={22} />
                        </span>
                        <div>
                            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--accent)]">Account access</p>
                            <h1 className="mt-1 text-2xl font-semibold text-[var(--ink)]">Set new password</h1>
                            <p className="mt-1 text-sm leading-6 text-[var(--muted)]">Enter a new password to secure your account.</p>
                        </div>
                    </div>

                    {!token ? (
                        <div className="rounded-lg border border-[var(--danger-soft)] bg-[var(--danger-soft)] p-4 text-sm font-semibold text-[var(--danger)]">
                            Invalid or missing reset token.
                        </div>
                    ) : (
                        <form onSubmit={handleSubmit} className="space-y-4">
                            <TextField
                                label="New password"
                                type="password"
                                value={password}
                                onChange={e => setPassword(e.target.value)}
                                placeholder="Enter new password"
                                required
                                minLength={6}
                                name="password"
                            />
                            <Button type="submit" disabled={saving} size="lg" className="w-full">
                                {saving ? <LoaderCircle className="animate-spin" size={17} /> : <KeyRound size={17} />}
                                {saving ? 'Updating password' : 'Update password'}
                            </Button>
                        </form>
                    )}

                    {msg && (
                        <div className="mt-5 flex items-start gap-2 rounded-lg border border-[var(--positive-soft)] bg-[var(--positive-soft)] p-3 text-sm font-semibold text-[var(--positive)]">
                            <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
                            {msg}
                        </div>
                    )}
                    {error && (
                        <div className="mt-5 flex items-start gap-2 rounded-lg border border-[var(--danger-soft)] bg-[var(--danger-soft)] p-3 text-sm font-semibold text-[var(--danger)]">
                            <AlertCircle size={16} className="mt-0.5 shrink-0" />
                            {error}
                        </div>
                    )}

                    <a href="/" className="mt-6 inline-flex text-sm font-semibold text-[var(--muted)] hover:text-[var(--accent)]">
                        Back to dashboard
                    </a>
                </Panel>
            </PageShell>
        </div>
    );
};
