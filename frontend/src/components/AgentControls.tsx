import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, LoaderCircle, Play, ShieldAlert } from 'lucide-react';
import { getAuthHeaders, API_URL } from '../api/client';
import type { AgentQuotaStatus } from '../api/client';
import type { ResumeUploadHandle } from './ResumeUpload';
import type { JobPreferencesHandle } from './JobPreferences';
import { Button, StatusChip } from './ui';

interface AgentControlsProps {
    onComplete: () => void;
    resumeRef: React.RefObject<ResumeUploadHandle | null>;
    prefsRef: React.RefObject<JobPreferencesHandle | null>;
    isLoggedIn: boolean;
    quota?: AgentQuotaStatus | null;
    subscriptionTier?: string;
    userRole?: string;
    onAuthRequired: () => void;
}

export const AgentControls: React.FC<AgentControlsProps> = ({ onComplete, resumeRef, prefsRef, isLoggedIn, quota, subscriptionTier, userRole, onAuthRequired }) => {
    const [isRunning, setIsRunning] = useState(false);
    const [status, setStatus] = useState<string>('');
    const [autoApply, setAutoApply] = useState(false);
    const [quotaRemaining, setQuotaRemaining] = useState<number | null>(quota?.agent_runs_remaining ?? null);

    const canAutoApply = useMemo(() => {
        return Boolean(quota?.auto_apply_enabled || subscriptionTier === 'pro' || userRole === 'admin');
    }, [quota?.auto_apply_enabled, subscriptionTier, userRole]);

    useEffect(() => {
        setQuotaRemaining(quota?.agent_runs_remaining ?? null);
    }, [quota?.agent_runs_remaining]);

    const pollAgentRun = async (runId: number, shouldAutoApply: boolean, wasFileSelected: boolean) => {
        for (let attempt = 0; attempt < 90; attempt += 1) {
            await new Promise(resolve => window.setTimeout(resolve, attempt === 0 ? 800 : 2000));

            const response = await fetch(`${API_URL}/agent/runs/${runId}`, {
                headers: getAuthHeaders()
            });
            const run = await response.json();
            if (!response.ok) {
                setStatus(`Error: ${run.detail || 'Failed to read search status'}`);
                return;
            }

            if (run.status === 'failed') {
                setStatus(`Error: ${run.error || 'Search run failed'}`);
                return;
            }

            if (run.status !== 'queued' && run.status !== 'running') {
                const prefix = wasFileSelected ? 'Resume uploaded. ' : '';
                const msg = shouldAutoApply
                    ? `Auto-submit completed for ${run.applications_count} jobs.`
                    : `Matched and prepared ${run.applications_count} jobs for review.`;
                setStatus(`${prefix}${msg}`);
                onComplete();
                return;
            }

            setStatus(run.status === 'queued' ? 'Search assistant queued...' : 'Finding best-fit jobs...');
        }

        setStatus('Search is still running. Check application history again shortly.');
        onComplete();
    };

    const startAgent = async () => {
        if (!isLoggedIn) {
            setStatus('Please sign in or create an account to launch the search assistant.');
            onAuthRequired();
            return;
        }

        setIsRunning(true);
        setStatus('');

        try {
            if (!resumeRef.current?.hasFile) {
                resumeRef.current?.setError('Please select a resume first.');
                setIsRunning(false);
                return;
            }

            const wasFileSelected = resumeRef.current?.hasFile;
            const resumeSuccess = await resumeRef.current?.handleUpload(true);
            if (!resumeSuccess) {
                setStatus('Error: Failed to upload resume.');
                setIsRunning(false);
                return;
            }

            const prefsSuccess = await prefsRef.current?.submitPrefs(true);
            if (!prefsSuccess) {
                setStatus('Error: Failed to save preferences.');
                setIsRunning(false);
                return;
            }

            const shouldAutoApply = canAutoApply && autoApply;
            const response = await fetch(`${API_URL}/agent/run?auto_apply=${shouldAutoApply}`, {
                method: 'POST',
                headers: getAuthHeaders()
            });
            const data = await response.json();
            if (response.ok) {
                if (typeof data.quota_remaining === 'number') {
                    setQuotaRemaining(data.quota_remaining);
                }
                setStatus('Search assistant queued...');
                if (data.agent_run_id) {
                    await pollAgentRun(data.agent_run_id, shouldAutoApply, Boolean(wasFileSelected));
                } else {
                    onComplete();
                }
            } else {
                setStatus(`Error: ${data.detail || 'Failed to run search'}`);
            }
        } catch (error) {
            console.error('Error running search assistant:', error);
            setStatus('Failed to connect to backend.');
        } finally {
            setIsRunning(false);
        }
    };

    const isProblem = status.startsWith('Error') || status.includes('sign in') || status.includes('Failed');

    return (
        <div className="w-full">
            <div className="flex flex-col gap-3">
                <div>
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                        <StatusChip tone="accent">Match roles</StatusChip>
                        <StatusChip tone={autoApply ? 'warning' : 'neutral'}>
                            {canAutoApply && autoApply ? 'Auto-submit on' : 'Prepare only'}
                        </StatusChip>
                        {quota && (
                            <StatusChip tone={quotaRemaining === 0 ? 'danger' : 'neutral'}>
                                {quotaRemaining ?? quota.agent_runs_remaining} runs left
                            </StatusChip>
                        )}
                    </div>
                    <p className="text-sm leading-6 text-[var(--muted)]">
                        The assistant compares open roles with your resume and preferences, saves the strongest matches, and packages materials for review.
                    </p>
                </div>

                <label className="relative flex cursor-pointer items-start gap-3 rounded-lg border border-[var(--line)] bg-white p-3 transition-colors hover:border-[var(--accent)]">
                    <input
                        type="checkbox"
                        checked={canAutoApply && autoApply}
                        disabled={!canAutoApply}
                        onChange={(e) => setAutoApply(canAutoApply && e.target.checked)}
                        className="peer sr-only disabled:cursor-not-allowed"
                    />
                    <span className="mt-0.5 flex h-5 w-10 shrink-0 rounded-full bg-[var(--soft)] p-0.5 transition-colors peer-checked:bg-[var(--accent)] peer-disabled:opacity-60">
                        <span className="h-4 w-4 rounded-full bg-white transition-transform peer-checked:translate-x-5" />
                    </span>
                    <span>
                        <span className="flex items-center gap-2 text-sm font-semibold text-[var(--ink)]">
                            <ShieldAlert size={16} className="text-[var(--warning)]" />
                            Auto-submit matched applications
                        </span>
                        <span className="mt-1 block text-xs leading-5 text-[var(--muted)]">
                            {canAutoApply
                                ? 'Leave this off to review best-fit jobs and generated materials before submitting.'
                                : 'Pro plan required. Free accounts can match jobs and prepare packages for review.'}
                        </span>
                    </span>
                </label>

                <Button onClick={startAgent} disabled={isRunning} size="lg" className="w-full">
                    {isRunning ? <LoaderCircle className="animate-spin" size={18} /> : <Play size={18} />}
                    {isRunning ? 'Matching jobs' : 'Start matching'}
                </Button>
            </div>

            {status && (
                <div className={`mt-3 flex items-start gap-3 rounded-lg border p-3 text-sm font-semibold ${isProblem ? 'border-[var(--danger-soft)] bg-[var(--danger-soft)] text-[var(--danger)]' : 'border-[var(--positive-soft)] bg-[var(--positive-soft)] text-[var(--positive)]'}`}>
                    {isProblem ? <AlertTriangle size={17} className="mt-0.5 shrink-0" /> : <CheckCircle2 size={17} className="mt-0.5 shrink-0" />}
                    <span>{status}</span>
                </div>
            )}
        </div>
    );
};
