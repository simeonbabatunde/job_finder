import React, { useState } from 'react';
import type { ResumeUploadHandle } from './ResumeUpload';
import type { JobPreferencesHandle } from './JobPreferences';

interface AgentControlsProps {
    onComplete: () => void;
    resumeRef: React.RefObject<ResumeUploadHandle | null>;
    prefsRef: React.RefObject<JobPreferencesHandle | null>;
}

export const AgentControls: React.FC<AgentControlsProps> = ({ onComplete, resumeRef, prefsRef }) => {
    const [isRunning, setIsRunning] = useState(false);
    const [status, setStatus] = useState<string>('');

    const startAgent = async () => {
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
            const response = await fetch('http://localhost:8000/agent/run', {
                method: 'POST',
            });
            const data = await response.json();
            if (response.ok) {
                const prefix = wasFileSelected ? "Resume uploaded! " : "";
                setStatus(`${prefix}Successfully applied to ${data.applications_count} jobs!`);
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
        <div className="bg-gradient-to-br from-indigo-50 to-purple-50 rounded-2xl p-5 border border-indigo-100 my-6">
            <div className="flex flex-col md:flex-row items-center justify-between gap-6">
                <div>
                    <h3 className="text-xl font-bold text-slate-800 mb-1">Apply Automatically</h3>
                    <p className="text-slate-600 text-sm">
                        This will upload your resume, save your preferences, and start the AI agent.
                    </p>
                </div>

                <button
                    onClick={startAgent}
                    disabled={isRunning}
                    className={`px-10 py-4 rounded-xl font-bold text-white shadow-lg transition-all transform hover:scale-105 active:scale-95 whitespace-nowrap
                        ${isRunning
                            ? 'bg-slate-400 cursor-not-allowed'
                            : 'bg-gradient-to-r from-indigo-600 to-purple-600 hover:shadow-indigo-200'}`}
                >
                    {isRunning ? (
                        <span className="flex items-center">
                            <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                            </svg>
                            Running...
                        </span>
                    ) : 'Start Auto-Apply'}
                </button>
            </div>

            {status && (
                <div className={`mt-4 p-3 rounded-lg text-sm font-medium ${status.startsWith('Error') ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}`}>
                    {status}
                </div>
            )}
        </div>
    );
};

