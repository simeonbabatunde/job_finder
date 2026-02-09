import { useEffect, useState } from 'react';

export const OAuthCallback = () => {
    const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
    const [message, setMessage] = useState('Processing authentication...');

    useEffect(() => {
        const handleCallback = async () => {
            try {
                // Get the token/user data from URL params
                const urlParams = new URLSearchParams(window.location.search);
                const email = urlParams.get('email');
                const error = urlParams.get('error');

                if (error) {
                    setStatus('error');
                    setMessage(decodeURIComponent(error));
                    return;
                }

                if (email) {
                    // Store user email in localStorage
                    localStorage.setItem('user_email', email);
                    setStatus('success');
                    setMessage('Login successful! Redirecting...');

                    // Redirect to main app after a short delay
                    setTimeout(() => {
                        window.location.href = '/';
                    }, 1500);
                } else {
                    setStatus('error');
                    setMessage('Authentication failed: No user data received');
                }
            } catch (err) {
                setStatus('error');
                setMessage('An error occurred during authentication');
            }
        };

        handleCallback();
    }, []);

    return (
        <div className="min-h-screen flex items-center justify-center bg-slate-50">
            <div className="bg-white rounded-2xl shadow-xl p-8 max-w-md w-full text-center">
                <div className="mb-6">
                    {status === 'loading' && (
                        <div className="inline-flex items-center justify-center w-16 h-16 bg-indigo-100 rounded-full mb-4">
                            <svg className="animate-spin h-8 w-8 text-indigo-600" fill="none" viewBox="0 0 24 24">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                            </svg>
                        </div>
                    )}
                    {status === 'success' && (
                        <div className="inline-flex items-center justify-center w-16 h-16 bg-green-100 rounded-full mb-4">
                            <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                            </svg>
                        </div>
                    )}
                    {status === 'error' && (
                        <div className="inline-flex items-center justify-center w-16 h-16 bg-red-100 rounded-full mb-4">
                            <svg className="w-8 h-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </div>
                    )}
                </div>

                <h2 className="text-2xl font-bold text-slate-900 mb-2">
                    {status === 'loading' && 'Authenticating...'}
                    {status === 'success' && 'Success!'}
                    {status === 'error' && 'Authentication Failed'}
                </h2>

                <p className="text-slate-600 text-sm">
                    {message}
                </p>

                {status === 'error' && (
                    <button
                        onClick={() => window.location.href = '/'}
                        className="mt-6 px-6 py-2.5 bg-indigo-600 text-white rounded-lg font-semibold hover:bg-indigo-700 transition-colors"
                    >
                        Return to Login
                    </button>
                )}
            </div>
        </div>
    );
};
