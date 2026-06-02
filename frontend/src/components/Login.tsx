import React, { useState } from 'react';
import { AlertCircle, CheckCircle2, LoaderCircle, Lock, Mail, UserRound, X } from 'lucide-react';
import { getErrorMessage, login, register, forgotPassword } from '../api/client';
import type { AppUser } from '../api/client';
import { Button, IconButton, TextField } from './ui';

interface LoginProps {
    onLoginSuccess: (user: AppUser) => void;
    onClose?: () => void;
    initialMode?: 'login' | 'register';
}

export const Login: React.FC<LoginProps> = ({ onLoginSuccess, onClose, initialMode = 'login' }) => {
    const [mode, setMode] = useState<'login' | 'register' | 'forgot'>(initialMode);
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [profile, setProfile] = useState({
        first_name: '',
        last_name: '',
        phone: '',
        location: '',
        linkedin_url: '',
    });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [successMsg, setSuccessMsg] = useState('');

    const handleLoginSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading(true);
        setError('');

        try {
            const data = await login(email, password);
            onLoginSuccess(data.user);
        } catch (err) {
            setError(getErrorMessage(err, 'Failed to log in. Please try again.'));
        } finally {
            setLoading(false);
        }
    };

    const handleRegisterSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading(true);
        setError('');

        try {
            const data = await register(email, password, profile);
            onLoginSuccess(data.user);
        } catch (err) {
            setError(getErrorMessage(err, 'Failed to register. Please try again.'));
        } finally {
            setLoading(false);
        }
    };

    const handleForgotSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading(true);
        setError('');
        setSuccessMsg('');

        try {
            const res = await forgotPassword(email);
            setSuccessMsg(res.message);
        } catch (err) {
            setError(getErrorMessage(err, 'Failed to send reset link.'));
        } finally {
            setLoading(false);
        }
    };

    const handleProfileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const { name, value } = e.target;
        setProfile(prev => ({ ...prev, [name]: value }));
    };

    const setAuthMode = (nextMode: 'login' | 'register' | 'forgot') => {
        setMode(nextMode);
        setError('');
        setSuccessMsg('');
    };

    const title = mode === 'login' ? 'Sign in' : mode === 'register' ? 'Create account' : 'Reset password';
    const subtitle = mode === 'forgot'
        ? 'Enter your email and we will send a reset link.'
        : 'Access your smart job search assistant, matched roles, and generated application materials.';

    return (
        <div className={onClose ? 'fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm' : 'flex min-h-screen items-center justify-center bg-[var(--page)] p-4'}>
            <div className="relative z-10 w-full max-w-xl">
                <div className="relative overflow-hidden rounded-lg border border-[var(--line)] bg-white p-6 shadow-2xl sm:p-8">
                    {onClose && (
                        <IconButton
                            label="Close authentication"
                            variant="ghost"
                            size="sm"
                            onClick={onClose}
                            className="absolute right-4 top-4"
                        >
                            <X size={18} />
                        </IconButton>
                    )}

                    <div className="mb-6 flex items-start gap-3">
                        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-[var(--accent-soft)] text-[var(--accent)]">
                            <UserRound size={22} />
                        </span>
                        <div>
                            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--accent)]">
                                Job Finder
                            </p>
                            <h2 className="mt-1 text-2xl font-semibold text-[var(--ink)]">{title}</h2>
                            <p className="mt-1 text-sm leading-6 text-[var(--muted)]">{subtitle}</p>
                        </div>
                    </div>

                    {mode !== 'forgot' && (
                        <div className="mb-5 grid grid-cols-2 gap-1 rounded-lg bg-[var(--soft)] p-1">
                            <button
                                type="button"
                                onClick={() => setAuthMode('login')}
                                className={`min-h-10 rounded-md text-sm font-semibold transition-colors ${mode === 'login' ? 'bg-white text-[var(--accent)] shadow-sm' : 'text-[var(--muted)] hover:text-[var(--ink)]'}`}
                            >
                                Sign in
                            </button>
                            <button
                                type="button"
                                onClick={() => setAuthMode('register')}
                                className={`min-h-10 rounded-md text-sm font-semibold transition-colors ${mode === 'register' ? 'bg-white text-[var(--accent)] shadow-sm' : 'text-[var(--muted)] hover:text-[var(--ink)]'}`}
                            >
                                Create account
                            </button>
                        </div>
                    )}

                    <form onSubmit={mode === 'login' ? handleLoginSubmit : (mode === 'register' ? handleRegisterSubmit : handleForgotSubmit)} className="space-y-4">
                        <TextField
                            label="Email address"
                            type="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                            placeholder="name@company.com"
                            name="email"
                        />

                        {mode !== 'forgot' && (
                            <div>
                                <TextField
                                    label="Password"
                                    type="password"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    required
                                    placeholder="Enter your password"
                                    name="password"
                                />
                                {mode === 'login' && (
                                    <div className="mt-2 text-right">
                                        <button
                                            type="button"
                                            onClick={() => setAuthMode('forgot')}
                                            className="text-xs font-semibold text-[var(--accent)] hover:underline"
                                        >
                                            Forgot password?
                                        </button>
                                    </div>
                                )}
                            </div>
                        )}

                        {mode === 'register' && (
                            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                                <TextField label="First name" name="first_name" value={profile.first_name} onChange={handleProfileChange} required placeholder="John" />
                                <TextField label="Last name" name="last_name" value={profile.last_name} onChange={handleProfileChange} required placeholder="Doe" />
                                <TextField label="Phone" name="phone" type="tel" value={profile.phone} onChange={handleProfileChange} required placeholder="+1 (555)" />
                                <TextField label="Location" name="location" value={profile.location} onChange={handleProfileChange} required placeholder="NY / Remote" />
                            </div>
                        )}

                        {error && (
                            <div className="flex items-start gap-2 rounded-lg border border-[var(--danger-soft)] bg-[var(--danger-soft)] p-3 text-sm font-semibold text-[var(--danger)]">
                                <AlertCircle size={17} className="mt-0.5 shrink-0" />
                                {error}
                            </div>
                        )}

                        {successMsg && (
                            <div className="flex items-start gap-2 rounded-lg border border-[var(--positive-soft)] bg-[var(--positive-soft)] p-3 text-sm font-semibold text-[var(--positive)]">
                                <CheckCircle2 size={17} className="mt-0.5 shrink-0" />
                                {successMsg}
                            </div>
                        )}

                        <Button type="submit" disabled={loading} size="lg" className="w-full">
                            {loading ? <LoaderCircle className="animate-spin" size={17} /> : mode === 'forgot' ? <Mail size={17} /> : <Lock size={17} />}
                            {loading ? 'Working' : mode === 'login' ? 'Sign in' : mode === 'register' ? 'Create account' : 'Send reset link'}
                        </Button>

                        {mode === 'forgot' && (
                            <Button
                                type="button"
                                variant="ghost"
                                onClick={() => setAuthMode('login')}
                                className="w-full"
                            >
                                Back to sign in
                            </Button>
                        )}
                    </form>
                </div>
            </div>
        </div>
    );
};
