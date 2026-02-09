import React, { useState } from 'react';
import { resetPassword } from '../api/client';

export const ResetPassword = () => {
    const [password, setPassword] = useState('');
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
        try {
            await resetPassword(token, password);
            setMsg('Password reset successfully! You can now log in.');
            setPassword('');
        } catch (err: any) {
            setError(err.message || 'Failed to reset password');
        }
    };

    if (!token) return (
        <div className="min-h-screen flex items-center justify-center bg-slate-50 p-4">
            <div className="text-center p-8 bg-white rounded-2xl shadow-xl">
                <p className="text-red-500 font-bold mb-4">Invalid or missing reset token.</p>
                <a href="/" className="text-indigo-600 font-bold hover:underline">Return to Home</a>
            </div>
        </div>
    );

    return (
        <div className="min-h-screen flex items-center justify-center bg-slate-50 p-4">
            <div className="max-w-md w-full bg-white p-8 rounded-2xl shadow-xl border border-slate-100">
                <div className="text-center mb-8">
                    <div className="inline-flex items-center justify-center w-12 h-12 bg-indigo-100 rounded-xl mb-4 text-indigo-600">
                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" /></svg>
                    </div>
                    <h2 className="text-2xl font-black text-slate-900">Set New Password</h2>
                    <p className="text-slate-500 text-sm mt-2">Enter your new password below to secure your account.</p>
                </div>

                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <input
                            type="password"
                            value={password}
                            onChange={e => setPassword(e.target.value)}
                            placeholder="New Password"
                            required
                            minLength={6}
                            className="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none transition-all font-medium"
                        />
                    </div>
                    <button type="submit" className="w-full py-3.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-bold shadow-lg shadow-indigo-200 transition-all active:scale-95">
                        Update Password
                    </button>
                </form>

                {msg && (
                    <div className="mt-6 p-4 bg-emerald-50 text-emerald-700 rounded-xl font-bold text-center text-sm border border-emerald-100 animate-in fade-in slide-in-from-bottom-2">
                        {msg}
                    </div>
                )}
                {error && (
                    <div className="mt-6 p-4 bg-red-50 text-red-700 rounded-xl font-bold text-center text-sm border border-red-100 animate-in fade-in slide-in-from-bottom-2">
                        {error}
                    </div>
                )}

                <div className="mt-8 text-center">
                    <a href="/" className="text-sm font-bold text-slate-400 hover:text-slate-600 transition-colors">← Back to Login</a>
                </div>
            </div>
        </div>
    );
}
