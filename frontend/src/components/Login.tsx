import React, { useState } from 'react';
import { login, register, socialLogin } from '../api/client';

interface LoginProps {
    onLoginSuccess: (user: any) => void;
    onClose?: () => void;
    initialMode?: 'login' | 'register';
}

export const Login: React.FC<LoginProps> = ({ onLoginSuccess, onClose, initialMode = 'login' }) => {
    const [mode, setMode] = useState<'login' | 'register'>(initialMode);
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

    const handleSocialLogin = async (provider: string) => {
        setLoading(true);
        setError('');
        try {
            // Mock social login
            const mockEmail = provider === 'google' ? 'google_user@gmail.com' : 'github_user@github.com';
            const data = await socialLogin(mockEmail, provider, 'Social', 'User');
            onLoginSuccess(data.user);
        } catch (err) {
            setError('Social login failed');
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

                    {/* Tabs */}
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

                    <form onSubmit={mode === 'login' ? handleLoginSubmit : handleRegisterSubmit} className="space-y-4">
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
                            </div>

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
                                mode === 'login' ? 'Sign In' : 'Create Account'
                            )}
                        </button>
                    </form>

                    <div className="relative my-6">
                        <div className="absolute inset-0 flex items-center">
                            <div className="w-full border-t border-slate-100"></div>
                        </div>
                        <div className="relative flex justify-center text-[10px] uppercase font-bold tracking-[0.15em]">
                            <span className="bg-white px-3 text-slate-400">Or</span>
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <button
                            onClick={() => handleSocialLogin('google')}
                            className="flex items-center justify-center gap-2 py-3 border border-slate-200 rounded-xl hover:bg-slate-50 transition-all font-bold text-slate-600 text-[13px]"
                        >
                            <svg className="w-4 h-4" viewBox="0 0 24 24">
                                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" />
                                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                            </svg>
                            Google
                        </button>
                        <button
                            onClick={() => handleSocialLogin('github')}
                            className="flex items-center justify-center gap-2 py-3 border border-slate-200 rounded-xl hover:bg-slate-50 transition-all font-bold text-slate-600 text-[13px]"
                        >
                            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                                <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
                            </svg>
                            GitHub
                        </button>
                    </div>

                    <p className="mt-6 text-center text-[9px] text-slate-400 font-bold uppercase tracking-widest leading-relaxed">
                        By continuing, you agree to our <br />
                        <span className="text-indigo-600 underline underline-offset-4 cursor-pointer">Terms of Service</span> and <span className="text-indigo-600 underline underline-offset-4 cursor-pointer">Privacy Policy</span>
                    </p>
                </div>
            </div>
        </div>
    );
};
