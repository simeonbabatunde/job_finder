import React, { useState } from 'react';
import { getAuthHeaders } from '../api/client';
import type { ResumeUploadHandle } from './ResumeUpload';
import type { JobPreferencesHandle } from './JobPreferences';

interface AgentControlsProps {
    onComplete: () => void;
    resumeRef: React.RefObject<ResumeUploadHandle | null>;
    prefsRef: React.RefObject<JobPreferencesHandle | null>;
    isLoggedIn: boolean;
    onAuthRequired: () => void;
}

export const AgentControls: React.FC<AgentControlsProps> = ({ onComplete, resumeRef, prefsRef, isLoggedIn, onAuthRequired }) => {
    const [isRunning, setIsRunning] = useState(false);
    const [status, setStatus] = useState<string>('');
    const [autoApply, setAutoApply] = useState(false);

    const startAgent = async () => {
        // Check if user is logged in
        if (!isLoggedIn) {
            setStatus('Please sign in or create an account to launch the agent.');
            onAuthRequired();
            return;
        }

        setIsRunning(true);
        setStatus('');

        try {
            // 0. Validate Resume Presence
            if (!resumeRef.current?.hasFile) {
                resumeRef.current?.setError('Please select a resume first.');
                setIsRunning(false);
                return;
            }

            // 1. Trigger Resume Upload (if any new file)
            const wasFileSelected = resumeRef.current?.hasFile;
            const resumeSuccess = await resumeRef.current?.handleUpload(true);
            if (!resumeSuccess) {
                setStatus('Error: Failed to upload resume.');
                setIsRunning(false);
                return;
            }

            // 2. Trigger Preferences Save (silent)
            const prefsSuccess = await prefsRef.current?.submitPrefs(true);
            if (!prefsSuccess) {
                setStatus('Error: Failed to save preferences.');
                setIsRunning(false);
                return;
            }

            // 3. Run the Agent
            const response = await fetch(`http://localhost:8000/agent/run?auto_apply=${autoApply}`, {
                method: 'POST',
                headers: getAuthHeaders()
            });
            const data = await response.json();
            if (response.ok) {
                const prefix = wasFileSelected ? "Resume uploaded! " : "";
                const msg = autoApply
                    ? `Successfully auto-filled ${data.applications_count} jobs!`
                    : `Discovered and analyzed ${data.applications_count} jobs! Check history below.`;
                setStatus(`${prefix}${msg}`);
                onComplete();
            } else {
                setStatus(`Error: ${data.detail || 'Failed to run agent'}`);
            }
        } catch (error) {
            console.error('Error running agent:', error);
            setStatus('Failed to connect to backend.');
        } finally {
            setIsRunning(false);
        }
    };

    return (
        <div className="bg-gradient-to-br from-indigo-50 to-purple-50 rounded-3xl p-8 border border-indigo-100 shadow-sm">
            <div className="flex flex-col lg:flex-row items-start lg:items-center gap-6 lg:gap-8">
                {/* Left: Description */}
                <div className="flex-1 space-y-4">
                    <div>
                        <h3 className="text-2xl font-black text-slate-900 mb-2">Start Your Job Hunt</h3>
                        <p className="text-slate-600 leading-relaxed">
                            Our AI will search across job boards, match roles to your resume, generate custom cover letters, and track everything in your dashboard.
                        </p>
                    </div>

                    <label className="relative inline-flex items-center cursor-pointer bg-white/60 px-4 py-2.5 rounded-xl border border-indigo-100/80 hover:bg-white/80 transition-all">
                        <input
                            type="checkbox"
                            checked={autoApply}
                            onChange={(e) => setAutoApply(e.target.checked)}
                            className="sr-only peer"
                        />
                        <div className="w-10 h-5 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[10px] after:left-[18px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-600"></div>
                        <span className="ml-3 text-sm font-bold text-slate-700">Auto-submit applications (BETA)</span>
                    </label>
                </div>

                {/* Right: Action Button */}
                <div className="w-full lg:w-auto">
                    <button
                        onClick={startAgent}
                        disabled={isRunning}
                        className={`w-full lg:w-auto px-12 py-5 rounded-2xl font-black text-white shadow-xl transition-all transform hover:scale-105 active:scale-95 text-lg
                            ${isRunning
                                ? 'bg-slate-400 cursor-not-allowed opacity-80'
                                : 'bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 shadow-indigo-200'}`}
                    >
                        {isRunning ? (
                            <span className="flex items-center justify-center">
                                <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                </svg>
                                Agent Working...
                            </span>
                        ) : (
                            <span className="flex items-center justify-center gap-2">
                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                                </svg>
                                Find Jobs Now
                            </span>
                        )}
                    </button>
                </div>
            </div>

            {status && (
                <div className={`mt-6 p-4 rounded-xl text-sm font-bold flex items-center gap-3 animate-in fade-in slide-in-from-top-2 duration-300 ${status.startsWith('Error') || status.includes('sign in') ? 'bg-red-50 text-red-600 border border-red-100' : 'bg-emerald-50 text-emerald-700 border border-emerald-100'}`}>
                    {status.startsWith('Error') || status.includes('sign in') ? '⚠️' : '✅'}
                    {status}
                </div>
            )}
        </div>
    );
};

