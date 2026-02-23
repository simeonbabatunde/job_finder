import React, { useState } from 'react';
import { login, register, forgotPassword } from '../api/client';

interface LoginProps {
    onLoginSuccess: (user: any) => void;
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
        } catch (err: any) {
            setError(err.message || 'Failed to log in. Please try again.');
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
        } catch (err: any) {
            setError(err.message || 'Failed to register. Please try again.');
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
        } catch (err: any) {
            setError(err.message || 'Failed to send reset link.');
        } finally {
            setLoading(false);
        }
    };


    const handleProfileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const { name, value } = e.target;
        setProfile(prev => ({ ...prev, [name]: value }));
    };

    return (
        <div className={onClose ? "fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-md animate-in fade-in duration-300" : "min-h-screen flex items-center justify-center p-4 bg-slate-50 relative overflow-hidden"}>
            {!onClose && (
                <>
                    <div className="absolute top-0 -left-4 w-72 h-72 bg-indigo-300 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-blob"></div>
                    <div className="absolute top-0 -right-4 w-72 h-72 bg-violet-300 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-blob animation-delay-2000"></div>
                    <div className="absolute -bottom-8 left-20 w-72 h-72 bg-pink-300 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-blob animation-delay-4000"></div>
                </>
            )}

            <div className="w-full max-w-xl relative z-10 animate-in zoom-in-95 duration-300">
                <div className="bg-white rounded-[2rem] shadow-2xl border border-slate-100 p-8 sm:p-10 relative overflow-hidden">
                    {onClose && (
                        <button
                            onClick={onClose}
                            className="absolute top-6 right-6 p-2 rounded-full hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-all z-20"
                        >
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    )}

                    <div className="text-center mb-8">
                        <div className="inline-flex items-center justify-center w-12 h-12 bg-gradient-to-br from-indigo-500 to-violet-600 rounded-xl shadow-xl mb-4">
                            <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                            </svg>
                        </div>
                        <h2 className="text-2xl font-black text-slate-900 tracking-tight">Job Hunter AI</h2>
                        <p className="text-slate-500 mt-1 text-sm font-medium">Your personal AI agent for autonomous job hunting</p>
                    </div>

                    {/* Tabs (Hidden in forgot mode) */}
                    {mode !== 'forgot' && (
                        <div className="flex bg-slate-100 p-1 rounded-xl mb-6">
                            <button
                                onClick={() => { setMode('login'); setError(''); }}
                                className={`flex-1 py-2 text-xs font-bold rounded-lg transition-all ${mode === 'login' ? 'bg-white text-indigo-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
                            >
                                Sign In
                            </button>
                            <button
                                onClick={() => { setMode('register'); setError(''); }}
                                className={`flex-1 py-2 text-xs font-bold rounded-lg transition-all ${mode === 'register' ? 'bg-white text-indigo-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
                            >
                                Create Account
                            </button>
                        </div>
                    )}

                    {/* HEADING for Forgot Mode */}
                    {mode === 'forgot' && (
                        <div className="mb-6 text-center">
                            <h3 className="text-lg font-bold text-slate-800">Reset Password</h3>
                            <p className="text-xs text-slate-500 mt-1">Enter your email to receive a reset link</p>
                        </div>
                    )}

                    <form onSubmit={mode === 'login' ? handleLoginSubmit : (mode === 'register' ? handleRegisterSubmit : handleForgotSubmit)} className="space-y-4">
                        <div className="space-y-3">
                            <div>
                                <label className="block text-[9px] font-black text-slate-400 uppercase tracking-[0.2em] mb-1.5 px-1">
                                    Email Address
                                </label>
                                <input
                                    type="email"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    required
                                    className="w-full px-4 py-3 bg-slate-50/50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500/10 focus:border-indigo-500 outline-none transition-all text-sm text-slate-800 font-medium placeholder:text-slate-300"
                                    placeholder="name@company.com"
                                />
                            </div>

                            {mode !== 'forgot' && (
                                <div>
                                    <label className="block text-[9px] font-black text-slate-400 uppercase tracking-[0.2em] mb-1.5 px-1">
                                        Password
                                    </label>
                                    <input
                                        type="password"
                                        value={password}
                                        onChange={(e) => setPassword(e.target.value)}
                                        required
                                        className="w-full px-4 py-3 bg-slate-50/50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500/10 focus:border-indigo-500 outline-none transition-all text-sm text-slate-800 font-medium placeholder:text-slate-300"
                                        placeholder="••••••••"
                                    />
                                    {mode === 'login' && (
                                        <div className="mt-2 text-right">
                                            <button
                                                type="button"
                                                onClick={() => { setMode('forgot'); setError(''); setSuccessMsg(''); }}
                                                className="text-xs font-bold text-indigo-600 hover:underline"
                                            >
                                                Forgot Password?
                                            </button>
                                        </div>
                                    )}
                                </div>
                            )}

                            {mode === 'register' && (
                                <div className="grid grid-cols-2 gap-3 animate-in fade-in slide-in-from-top-1 duration-200">
                                    <div className="col-span-1">
                                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-[0.2em] mb-1.5 px-1">First Name</label>
                                        <input
                                            type="text"
                                            name="first_name"
                                            value={profile.first_name}
                                            onChange={handleProfileChange}
                                            required
                                            className="w-full px-4 py-2.5 bg-slate-50/50 border border-slate-200 rounded-xl focus:border-indigo-500 outline-none transition-all text-sm"
                                            placeholder="John"
                                        />
                                    </div>
                                    <div className="col-span-1">
                                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-[0.2em] mb-1.5 px-1">Last Name</label>
                                        <input
                                            type="text"
                                            name="last_name"
                                            value={profile.last_name}
                                            onChange={handleProfileChange}
                                            required
                                            className="w-full px-4 py-2.5 bg-slate-50/50 border border-slate-200 rounded-xl focus:border-indigo-500 outline-none transition-all text-sm"
                                            placeholder="Doe"
                                        />
                                    </div>
                                    <div className="col-span-1">
                                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-[0.2em] mb-1.5 px-1">Phone</label>
                                        <input
                                            type="tel"
                                            name="phone"
                                            value={profile.phone}
                                            onChange={handleProfileChange}
                                            required
                                            className="w-full px-4 py-2.5 bg-slate-50/50 border border-slate-200 rounded-xl focus:border-indigo-500 outline-none transition-all text-sm"
                                            placeholder="+1 (555)"
                                        />
                                    </div>
                                    <div className="col-span-1">
                                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-[0.2em] mb-1.5 px-1">Location</label>
                                        <input
                                            type="text"
                                            name="location"
                                            value={profile.location}
                                            onChange={handleProfileChange}
                                            required
                                            className="w-full px-4 py-2.5 bg-slate-50/50 border border-slate-200 rounded-xl focus:border-indigo-500 outline-none transition-all text-sm"
                                            placeholder="NY / Remote"
                                        />
                                    </div>
                                </div>
                            )}
                        </div>

                        {error && (
                            <div className="text-red-500 text-[11px] font-bold bg-red-50 p-3 rounded-xl border border-red-100 flex items-center gap-2">
                                <span>⚠️</span> {error}
                            </div>
                        )}

                        {successMsg && (
                            <div className="text-emerald-700 text-[11px] font-bold bg-emerald-50 p-3 rounded-xl border border-emerald-100 flex items-center gap-2">
                                <span>✅</span> {successMsg}
                            </div>
                        )}

                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full py-3.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-black shadow-lg shadow-indigo-100 transition-all flex items-center justify-center gap-2 disabled:opacity-50 transform active:scale-95 text-sm"
                        >
                            {loading ? (
                                <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                </svg>
                            ) : (
                                mode === 'login' ? 'Sign In' : (mode === 'register' ? 'Create Account' : 'Send Reset Link')
                            )}
                        </button>

                        {mode === 'forgot' && (
                            <button
                                type="button"
                                onClick={() => { setMode('login'); setError(''); setSuccessMsg(''); }}
                                className="w-full py-2 text-slate-400 font-bold text-xs hover:text-slate-600 transition-colors"
                            >
                                Back to Login
                            </button>
                        )}
                    </form>


                </div>
            </div>
        </div>
    );
};
