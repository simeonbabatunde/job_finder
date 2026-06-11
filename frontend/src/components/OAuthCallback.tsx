import { useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, LoaderCircle } from 'lucide-react';
import { saveOAuthSession } from '../api/client';
import { Button, PageShell, Panel } from './ui';

export const OAuthCallback = () => {
    const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
    const [message, setMessage] = useState('Processing authentication...');

    useEffect(() => {
        const handleCallback = async () => {
            try {
                const urlParams = new URLSearchParams(window.location.search);
                const email = urlParams.get('email');
                const token = urlParams.get('token');
                const refreshToken = urlParams.get('refresh_token');
                const error = urlParams.get('error');

                if (error) {
                    setStatus('error');
                    setMessage(decodeURIComponent(error));
                    return;
                }

                if (token) {
                    saveOAuthSession(token, refreshToken, email);
                    window.history.replaceState({}, document.title, window.location.pathname);
                    setStatus('success');
                    setMessage('Login successful. Redirecting...');

                    window.setTimeout(() => {
                        window.location.href = '/';
                    }, 1500);
                } else {
                    setStatus('error');
                    setMessage('Authentication failed: no access token received.');
                }
            } catch {
                setStatus('error');
                setMessage('An error occurred during authentication.');
            }
        };

        void handleCallback();
    }, []);

    const icon = {
        loading: <LoaderCircle className="animate-spin text-[var(--accent)]" size={30} />,
        success: <CheckCircle2 className="text-[var(--positive)]" size={30} />,
        error: <AlertCircle className="text-[var(--danger)]" size={30} />,
    }[status];

    const title = {
        loading: 'Authenticating',
        success: 'Signed in',
        error: 'Authentication failed',
    }[status];

    return (
        <div className="min-h-screen bg-[var(--page)] text-[var(--ink)]">
            <PageShell className="flex min-h-screen max-w-lg items-center">
                <Panel className="w-full p-8 text-center">
                    <span className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-lg bg-[var(--soft)]">
                        {icon}
                    </span>
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--accent)]">JobMatchHero</p>
                    <h1 className="mt-2 text-2xl font-semibold text-[var(--ink)]">{title}</h1>
                    <p className="mt-2 text-sm leading-6 text-[var(--muted)]">{message}</p>

                    {status === 'error' && (
                        <Button className="mt-6" onClick={() => { window.location.href = '/'; }}>
                            Return to dashboard
                        </Button>
                    )}
                </Panel>
            </PageShell>
        </div>
    );
};
