import React, { useEffect, useState } from 'react';
import { LoaderCircle, Play, Square } from 'lucide-react';
import { getAuthHeaders, API_URL } from '../api/client';
import type { AgentQuotaStatus } from '../api/client';
import type { ResumeUploadHandle } from './ResumeUpload';
import type { JobPreferencesHandle } from './JobPreferences';
import { Button, Notice, StatusChip } from './ui';

interface AgentControlsProps {
    onComplete: () => void;
    resumeRef: React.RefObject<ResumeUploadHandle | null>;
    prefsRef: React.RefObject<JobPreferencesHandle | null>;
    isLoggedIn: boolean;
    quota?: AgentQuotaStatus | null;
    matchingProfileId?: number | null;
    onAuthRequired: () => void;
}

const STOP_PENDING_MESSAGE = 'Stop requested. Matching will stop after the current step finishes.';
const STOPPED_MESSAGE = 'Matching stopped. No more jobs will be processed.';

export const AgentControls: React.FC<AgentControlsProps> = ({ onComplete, resumeRef, prefsRef, isLoggedIn, quota, matchingProfileId, onAuthRequired }) => {
    const [isRunning, setIsRunning] = useState(false);
    const [isStopping, setIsStopping] = useState(false);
    const [activeRunId, setActiveRunId] = useState<number | null>(null);
    const [status, setStatus] = useState<string>('');
    const [quotaRemaining, setQuotaRemaining] = useState<number | null>(quota?.agent_runs_remaining ?? null);

    useEffect(() => {
        setQuotaRemaining(quota?.agent_runs_remaining ?? null);
    }, [quota?.agent_runs_remaining]);

    const pollAgentRun = async (runId: number) => {
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

            if (run.status === 'canceled') {
                setStatus(STOPPED_MESSAGE);
                onComplete();
                return;
            }

            if (run.status === 'cancel_requested') {
                setStatus(STOP_PENDING_MESSAGE);
                continue;
            }

            if (run.status !== 'queued' && run.status !== 'running') {
                const foundCount = Number(run.found_jobs_count || 0);
                const readyCount = Number(run.applications_count || 0);
                const logs = Array.isArray(run.logs) ? run.logs : [];
                const funnelLog = [...logs].reverse().find((log: string) => log.startsWith('AI scored '));
                const msg = `Found ${foundCount} application-ready roles. ${readyCount} cleared your minimum score and ${readyCount === 1 ? 'is' : 'are'} ready for review.`;
                setStatus(funnelLog ? `${msg} ${funnelLog}` : msg);
                onComplete();
                return;
            }

            setStatus(run.status === 'queued' ? 'Matching workflow queued...' : 'Finding best-fit jobs...');
        }

        setStatus('Search is still running. Check application history again shortly.');
        onComplete();
    };

    const stopAgent = async () => {
        if (!activeRunId) return;

        setIsStopping(true);
        setStatus(STOP_PENDING_MESSAGE);

        try {
            const response = await fetch(`${API_URL}/agent/runs/${activeRunId}/cancel`, {
                method: 'POST',
                headers: getAuthHeaders()
            });
            const data = await response.json().catch(() => ({}));

            if (!response.ok) {
                if (response.status === 400) {
                    setStatus('Matching has already finished. Refreshing your results...');
                    onComplete();
                    return;
                }
                setStatus(`Error: ${data.detail || 'Failed to stop matching'}`);
                setIsStopping(false);
                return;
            }

            if (data.status === 'canceled') {
                setStatus(STOPPED_MESSAGE);
                onComplete();
            } else {
                setStatus(STOP_PENDING_MESSAGE);
            }
        } catch (error) {
            console.error('Error stopping matching workflow:', error);
            setStatus('Failed to connect to backend.');
            setIsStopping(false);
        }
    };

    const startAgent = async () => {
        if (!isLoggedIn) {
            setStatus('Please sign in or create an account to start matching.');
            onAuthRequired();
            return;
        }

        setIsRunning(true);
        setIsStopping(false);
        setActiveRunId(null);
        setStatus('');

        try {
            const resumeSuccess = resumeRef.current
                ? await resumeRef.current.handleUpload(true)
                : true;
            if (!resumeSuccess) {
                setStatus('Error: Failed to upload resume. No matching run was started.');
                return;
            }

            const prefsSuccess = await prefsRef.current?.submitPrefs(true);
            if (!prefsSuccess) {
                setStatus('Error: Failed to save preferences. No matching run was started.');
                return;
            }

            const runParams = new URLSearchParams();
            if (matchingProfileId) {
                runParams.set('matching_profile_id', String(matchingProfileId));
            }
            const runQuery = runParams.toString();
            const response = await fetch(`${API_URL}/agent/run${runQuery ? `?${runQuery}` : ''}`, {
                method: 'POST',
                headers: getAuthHeaders()
            });
            const data = await response.json().catch(() => ({}));
            if (response.ok) {
                if (typeof data.quota_remaining === 'number') {
                    setQuotaRemaining(data.quota_remaining);
                }
                setStatus('Matching workflow queued...');
                if (data.agent_run_id) {
                    setActiveRunId(data.agent_run_id);
                    await pollAgentRun(data.agent_run_id);
                } else {
                    onComplete();
                }
            } else {
                setStatus(`Error: ${data.detail || 'Failed to run search'}. No matching run was started.`);
            }
        } catch (error) {
            console.error('Error running matching workflow:', error);
            setStatus('Failed to connect to backend.');
        } finally {
            setIsRunning(false);
            setIsStopping(false);
            setActiveRunId(null);
        }
    };

    const isProblem = status.startsWith('Error') || status.includes('sign in') || status.includes('Failed');
    const isProgress = status.includes('queued') || status.includes('Finding') || status.includes('still running') || status.includes('Stop requested');
    const isStopped = status === STOPPED_MESSAGE;
    const noticeTone = isProblem ? 'error' : isProgress ? 'info' : 'success';
    const noticeTitle = isProblem ? 'Something needs attention' : isStopped ? 'Matching stopped' : isProgress ? 'Matching update' : 'Matching complete';

    return (
        <div className="w-full">
            <div className="flex flex-col gap-3">
                <div>
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                        <StatusChip tone="accent">Match roles</StatusChip>
                        <StatusChip tone="neutral">Package materials</StatusChip>
                        {quota && (
                            <StatusChip tone={quotaRemaining === 0 ? 'danger' : 'neutral'}>
                                {quotaRemaining ?? quota.agent_runs_remaining} runs left
                            </StatusChip>
                        )}
                    </div>
                    <p className="text-sm leading-6 text-[var(--muted)]">
                        JobMatchKit compares open roles with your resume and preferences, saves the strongest matches, and packages materials for review.
                    </p>
                </div>

                <div className={isRunning && activeRunId ? 'grid gap-2 sm:grid-cols-[1fr_auto]' : ''}>
                    <Button onClick={startAgent} disabled={isRunning} size="lg" className="w-full">
                        {isRunning ? <LoaderCircle className="animate-spin" size={18} /> : <Play size={18} />}
                        {isRunning ? 'Matching jobs' : 'Start matching'}
                    </Button>
                    {isRunning && activeRunId && (
                        <Button
                            onClick={stopAgent}
                            disabled={isStopping}
                            variant="danger"
                            size="lg"
                            className="w-full sm:w-auto sm:min-w-36"
                        >
                            {isStopping ? <LoaderCircle className="animate-spin" size={18} /> : <Square size={16} />}
                            {isStopping ? 'Stopping' : 'Stop matching'}
                        </Button>
                    )}
                </div>
            </div>

            {status && (
                <Notice tone={noticeTone} title={noticeTitle} className="mt-3">
                    {status}
                </Notice>
            )}
        </div>
    );
};
