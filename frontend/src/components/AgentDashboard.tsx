import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArchiveX, ArrowDownUp, Box, ExternalLink, RefreshCw, Trash2 } from 'lucide-react';
import {
    clearApplications as clearSavedApplications,
    getErrorMessage,
    getApplicationSummary,
    getAuthHeaders,
    API_URL,
} from '../api/client';
import type { ApplicationSummary } from '../api/client';
import { ApplicationPackageModal } from './ApplicationPackageModal';
import { Button, ConfirmDialog, EmptyState, IconButton, Notice, StatusChip } from './ui';

interface Application {
    id: number;
    job_title: string;
    company: string;
    status: string;
    fit_score: number;
    created_at: string;
    job_url: string;
    source_url?: string | null;
    resolved_url?: string | null;
    source_type?: string | null;
    ats_type?: string | null;
    resolution_status?: string | null;
    resolution_notes?: string | null;
    explanation?: string;
    cover_letter?: string;
    matching_profile_id?: number | null;
    matching_profile_name?: string | null;
    matching_profile_min_match_score?: number | null;
    agent_run_id?: number | null;
    pre_screen_status?: string;
    pre_screen_reasons?: string[];
}

interface AgentDashboardProps {
    limit?: number;
    fullPage?: boolean;
    compact?: boolean;
    minMatchScore?: number;
    minMatchScoreLabel?: string;
    matchingProfileId?: number | null;
    profileFilterControl?: React.ReactNode;
    profileFilterSummary?: React.ReactNode;
}

type MatchView = 'strong' | 'below_threshold';

const matchViews: { key: MatchView; label: string }[] = [
    { key: 'strong', label: 'Strong matches' },
    { key: 'below_threshold', label: 'Below threshold' },
];

function formatRunDate(value?: string | null) {
    if (!value) return 'Not finished yet';
    return new Date(value).toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    });
}

function runStatusTone(status?: string): 'neutral' | 'accent' | 'success' | 'warning' | 'danger' {
    if (status === 'completed') return 'success';
    if (status === 'running' || status === 'queued') return 'accent';
    if (status === 'cancel_requested') return 'warning';
    if (status === 'failed' || status === 'canceled') return 'danger';
    return 'neutral';
}

function statusTone(status: string): 'neutral' | 'accent' | 'success' | 'warning' | 'danger' {
    if (status === 'Submitted' || status === 'Applied' || status === 'Offer') return 'success';
    if (status === 'Analyzed' || status === 'Interview' || status === 'Phone Screen') return 'accent';
    if (status === 'Needs Review' || status === 'Take-Home') return 'warning';
    if (status === 'Analysis Failed' || status === 'Rejected') return 'danger';
    if (status === 'Screened Out') return 'danger';
    return 'neutral';
}

function scoreTone(score: number): 'neutral' | 'accent' | 'success' | 'warning' {
    if (score > 0.8) return 'success';
    if (score > 0.6) return 'accent';
    if (score > 0.4) return 'warning';
    return 'neutral';
}

function resolutionTone(status?: string | null): 'neutral' | 'accent' | 'success' | 'warning' | 'danger' {
    if (status === 'resolved') return 'success';
    if (status === 'needs_resolution') return 'warning';
    if (status === 'login_required' || status === 'captcha') return 'warning';
    if (status === 'manual_review' || status === 'unsupported') return 'danger';
    return 'neutral';
}

function resolutionLabel(app: Application) {
    if (app.ats_type) return 'Official apply link';
    if (app.resolution_status === 'resolved') {
        return app.source_type === 'company_site' ? 'Company apply page' : 'Apply link ready';
    }
    if (app.resolution_status === 'unsupported') return 'External apply page';
    return 'Source page only';
}

function isScreenedOut(app: Application) {
    return app.pre_screen_status === 'reject' || app.status === 'Screened Out';
}

function isBelowThreshold(app: Application, minMatchScore: number) {
    return !isScreenedOut(app) && app.fit_score > 0 && app.fit_score * 100 < minMatchScore;
}

function appMinMatchScore(app: Application, fallback: number) {
    return app.matching_profile_min_match_score ?? fallback;
}

function actionBlockReason(app: Application, minMatchScore: number) {
    if (isScreenedOut(app)) return 'Screened-out jobs are review-only.';
    if (app.fit_score * 100 < minMatchScore) {
        return app.fit_score > 0
            ? `Below your ${minMatchScore}% minimum match score.`
            : 'Not analyzed yet.';
    }
    return null;
}

function scoreOrScreenChip(app: Application, minMatchScore: number) {
    if (isScreenedOut(app)) {
        return <StatusChip tone="danger">Screened out</StatusChip>;
    }
    if (isBelowThreshold(app, minMatchScore)) {
        return <StatusChip tone="warning">{(app.fit_score * 100).toFixed(0)}%</StatusChip>;
    }
    return (
        <StatusChip tone={scoreTone(app.fit_score)}>
            {(app.fit_score * 100).toFixed(0)}%
        </StatusChip>
    );
}

function emptyStateCopy(matchView: MatchView) {
    if (matchView === 'below_threshold') {
        return {
            title: 'No below-threshold jobs.',
            detail: 'Jobs that were analyzed but did not clear your minimum score will appear here for review.',
        };
    }
    return {
        title: 'No strong matches yet.',
        detail: 'Start matching to find roles that clear your minimum score and are ready for application packaging.',
    };
}

export const AgentDashboard: React.FC<AgentDashboardProps> = ({
    limit,
    fullPage = false,
    compact = false,
    minMatchScore = 70,
    minMatchScoreLabel,
    matchingProfileId,
    profileFilterControl,
    profileFilterSummary,
}) => {
    const [applications, setApplications] = useState<Application[]>([]);
    const [loading, setLoading] = useState(true);
    const [summary, setSummary] = useState<ApplicationSummary | null>(null);
    const [clearing, setClearing] = useState(false);
    const [clearDialogOpen, setClearDialogOpen] = useState(false);
    const [clearNotice, setClearNotice] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
    const [sortBy, setSortBy] = useState<'date' | 'score'>('date');
    const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
    const [selectedApp, setSelectedApp] = useState<Application | null>(null);
    const [matchView, setMatchView] = useState<MatchView>('strong');

    const fetchApplications = useCallback(async () => {
        setLoading(true);
        try {
            const requestedMatchView: MatchView = fullPage ? matchView : 'strong';
            const params = new URLSearchParams({
                sort: fullPage ? sortBy : 'date',
                direction: fullPage ? sortDir : 'desc',
                match_bucket: requestedMatchView,
            });
            if (limit) {
                params.set('limit', String(limit));
            }
            if (matchingProfileId) {
                params.set('matching_profile_id', String(matchingProfileId));
            }

            const [appsResult, summaryResult] = await Promise.allSettled([
                fetch(`${API_URL}/applications?${params.toString()}`, {
                    headers: getAuthHeaders()
                }),
                getApplicationSummary(matchingProfileId),
            ]);

            if (appsResult.status === 'rejected') {
                throw appsResult.reason;
            }
            if (!appsResult.value.ok) {
                throw new Error('Failed to fetch applications');
            }
            const data = await appsResult.value.json();
            setApplications(data);

            if (summaryResult.status === 'fulfilled') {
                setSummary(summaryResult.value);
            } else {
                console.warn('Error fetching application summary:', summaryResult.reason);
            }
        } catch (error) {
            console.error('Error fetching applications:', error);
        } finally {
            setLoading(false);
        }
    }, [fullPage, limit, matchView, sortBy, sortDir, matchingProfileId]);

    useEffect(() => {
        void fetchApplications();
    }, [fetchApplications]);

    const handleClearApplications = async () => {
        setClearing(true);
        setClearNotice(null);
        try {
            const result = await clearSavedApplications();
            setApplications([]);
            setSummary(prev => prev ? {
                ...prev,
                strong_count: 0,
                below_threshold_count: 0,
                visible_count: 0,
            } : prev);
            setSelectedApp(null);
            setClearDialogOpen(false);
            setClearNotice({
                type: 'success',
                message: result.message || 'Application history cleared across all profiles.',
            });
        } catch (error) {
            console.error('Error clearing applications:', error);
            setClearNotice({
                type: 'error',
                message: getErrorMessage(error, 'Failed to clear application history. Please try again.'),
            });
        } finally {
            setClearing(false);
        }
    };

    const toggleSort = (field: 'date' | 'score') => {
        if (sortBy === field) {
            setSortDir(prev => prev === 'asc' ? 'desc' : 'asc');
        } else {
            setSortBy(field);
            setSortDir('desc');
        }
    };

    const sortedApplications = useMemo(() => {
        return [...applications].sort((a, b) => {
            if (sortBy === 'score') {
                return sortDir === 'asc' ? a.fit_score - b.fit_score : b.fit_score - a.fit_score;
            }
            const dateA = new Date(a.created_at).getTime();
            const dateB = new Date(b.created_at).getTime();
            return sortDir === 'asc' ? dateA - dateB : dateB - dateA;
        });
    }, [applications, sortBy, sortDir]);

    const displayedApps = limit ? sortedApplications.slice(0, limit) : sortedApplications;
    const useCompactList = compact && !fullPage;
    const currentEmpty = emptyStateCopy(fullPage ? matchView : 'strong');
    const strongCount = summary?.strong_count ?? (matchView === 'strong' ? applications.length : 0);
    const belowThresholdCount = summary?.below_threshold_count ?? (matchView === 'below_threshold' ? applications.length : 0);
    const visibleCount = summary?.visible_count ?? applications.length;
    const currentViewCount = matchView === 'below_threshold' ? belowThresholdCount : strongCount;
    const pipelineCountLabel = matchView === 'below_threshold'
        ? `${currentViewCount} below-threshold role${currentViewCount === 1 ? '' : 's'}`
        : `${currentViewCount} strong match${currentViewCount === 1 ? '' : 'es'}`;
    const latestRun = summary?.latest_run;

    const handleStatusChange = (appId: number, status: string) => {
        setApplications(prev =>
            prev.map(a => a.id === appId ? { ...a, status } : a)
        );
    };

    return (
        <div className={fullPage ? "min-w-0" : "mt-5 min-w-0"}>
            <ConfirmDialog
                open={clearDialogOpen}
                title="Clear all application history?"
                description="This removes saved matches and generated packages across every matching profile on this account. Your resumes, saved profiles, preferences, and account settings stay in place."
                cancelLabel="Keep history"
                confirmLabel="Clear all"
                loadingLabel="Clearing all"
                iconTone="error"
                loading={clearing}
                onCancel={() => setClearDialogOpen(false)}
                onConfirm={() => void handleClearApplications()}
            />
            {selectedApp && (
                <ApplicationPackageModal
                    app={selectedApp}
                    onClose={() => setSelectedApp(null)}
                    onStatusChange={handleStatusChange}
                />
            )}

            {fullPage ? (
                <div className="mb-3 rounded-lg border border-[var(--line)] bg-white p-3 shadow-sm">
                    <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                        <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                                <h3 className="text-lg font-semibold text-[var(--ink)]">Application pipeline</h3>
                                <StatusChip tone="accent">{pipelineCountLabel}</StatusChip>
                            </div>
                            {profileFilterSummary && (
                                <div className="mt-2">
                                    {profileFilterSummary}
                                </div>
                            )}
                        </div>
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-end">
                            {profileFilterControl}
                            <div className="flex flex-wrap items-center gap-2 sm:pb-0.5">
                                <Button variant="secondary" size="sm" onClick={() => void fetchApplications()}>
                                    <RefreshCw size={15} />
                                    Refresh
                                </Button>
                                <Button
                                    variant="danger"
                                    size="sm"
                                    onClick={() => setClearDialogOpen(true)}
                                    disabled={clearing || loading}
                                >
                                    <Trash2 size={15} />
                                    {clearing ? 'Clearing all' : 'Clear all'}
                                </Button>
                            </div>
                        </div>
                    </div>
                    <div className="mt-3 flex flex-col gap-3 border-t border-[var(--line)] pt-3 lg:flex-row lg:items-center lg:justify-between">
                        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 text-xs text-[var(--muted)]">
                            <span className="font-semibold uppercase tracking-[0.12em]">Latest run</span>
                            {latestRun ? (
                                <StatusChip tone={runStatusTone(latestRun.status)}>
                                    {latestRun.status.replaceAll('_', ' ')}
                                </StatusChip>
                            ) : (
                                <StatusChip tone="neutral">No run yet</StatusChip>
                            )}
                            <span className="font-semibold text-[var(--ink)]">
                                {latestRun
                                    ? formatRunDate(latestRun.completed_at || latestRun.started_at)
                                    : 'Start matching to populate this pipeline'}
                            </span>
                            <span>Found <strong className="text-[var(--ink)]">{latestRun?.found_jobs_count ?? 0}</strong></span>
                            <span>Visible <strong className="text-[var(--ink)]">{visibleCount}</strong></span>
                            <span>Strong <strong className="text-[var(--ink)]">{strongCount}</strong></span>
                        </div>
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
                            <div className="flex flex-wrap gap-2">
                                {matchViews.map(view => (
                                    <Button
                                        key={view.key}
                                        variant={matchView === view.key ? 'primary' : 'secondary'}
                                        size="sm"
                                        onClick={() => setMatchView(view.key)}
                                    >
                                        {view.label}
                                        {summary ? ` (${view.key === 'strong' ? strongCount : belowThresholdCount})` : ''}
                                    </Button>
                                ))}
                            </div>
                            <p className="whitespace-nowrap text-xs font-semibold text-[var(--muted)]">
                                {minMatchScoreLabel || `Minimum match score: ${minMatchScore}%`}
                            </p>
                        </div>
                    </div>
                    {latestRun?.error && (
                        <p className="mt-2 text-xs leading-5 text-[var(--danger)]">{latestRun.error}</p>
                    )}
                </div>
            ) : (
                <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                        <h3 className="text-lg font-semibold text-[var(--ink)]">Latest best-fit matches</h3>
                        <p className="text-sm text-[var(--muted)]">
                            {`${displayedApps.length} recent role${displayedApps.length === 1 ? '' : 's'}`}
                        </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        {applications.length > 0 && (
                            <Button variant="secondary" size="sm" onClick={() => { window.location.href = '/applications'; }}>
                                View all
                            </Button>
                        )}
                        <Button variant="secondary" size="sm" onClick={() => void fetchApplications()}>
                            <RefreshCw size={15} />
                            Refresh
                        </Button>
                    </div>
                </div>
            )}
            {clearNotice && (
                <Notice tone={clearNotice.type === 'success' ? 'success' : 'error'} className="mb-3">
                    {clearNotice.message}
                </Notice>
            )}

            {loading ? (
                <div className="flex justify-center rounded-lg border border-[var(--line)] bg-white py-10">
                    <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--line)] border-t-[var(--accent)]" />
                </div>
            ) : applications.length === 0 ? (
                <EmptyState
                    title={currentEmpty.title}
                    detail={currentEmpty.detail}
                />
            ) : useCompactList ? (
                <div className="space-y-2">
                    {displayedApps.map((app) => {
                        const rowMinMatchScore = appMinMatchScore(app, minMatchScore);
                        const blockReason = actionBlockReason(app, rowMinMatchScore);
                        return (
                            <article key={app.id} className="rounded-lg border border-[var(--line)] bg-white p-3">
                                <div className="flex items-start justify-between gap-3">
                                    <div className="min-w-0">
                                        <p className="truncate text-sm font-semibold text-[var(--ink)]">{app.job_title}</p>
                                        <p className="mt-1 truncate text-xs text-[var(--muted)]">{app.company}</p>
                                        {app.matching_profile_name && (
                                            <p className="mt-1 truncate text-xs font-semibold text-[var(--accent)]">{app.matching_profile_name}</p>
                                        )}
                                    </div>
                                    {scoreOrScreenChip(app, rowMinMatchScore)}
                                </div>
                                {app.pre_screen_reasons?.length ? (
                                    <p className="mt-2 text-xs leading-5 text-[var(--muted)]">
                                        {app.pre_screen_reasons[0]}
                                    </p>
                                ) : null}
                                <div className="mt-3 flex flex-wrap items-center gap-2">
                                    <StatusChip tone={statusTone(app.status)}>{app.status}</StatusChip>
                                    <StatusChip tone={resolutionTone(app.resolution_status)} title={app.resolution_notes || undefined}>
                                        {resolutionLabel(app)}
                                    </StatusChip>
                                    <span className="text-xs text-[var(--muted)]">
                                        {new Date(app.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                                    </span>
                                </div>
                                <div className="mt-3 flex flex-wrap items-center gap-2">
                                    <Button
                                        variant="secondary"
                                        size="sm"
                                        onClick={() => setSelectedApp(app)}
                                        disabled={Boolean(blockReason)}
                                        title={blockReason || undefined}
                                    >
                                        <Box size={15} />
                                        Package
                                    </Button>
                                    {app.job_url ? (
                                        <a
                                            href={app.resolved_url || app.job_url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-[var(--line)] bg-white px-3 text-xs font-semibold text-[var(--muted)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
                                        >
                                            <ExternalLink size={14} />
                                            Open
                                        </a>
                                    ) : (
                                        <IconButton label="No job URL" variant="ghost" size="sm" disabled>
                                            <ArchiveX size={15} />
                                        </IconButton>
                                    )}
                                </div>
                            </article>
                        );
                    })}
                </div>
            ) : (
                <div className="w-full max-w-full overflow-x-auto rounded-lg border border-[var(--line)] bg-white">
                    <table className="w-full min-w-[1000px] border-collapse text-left text-sm">
                        <thead className="bg-[var(--soft)] text-xs uppercase text-[var(--muted)]">
                            <tr>
                                <th className="px-4 py-3">Role</th>
                                <th className="px-4 py-3">Profile</th>
                                <th className="px-4 py-3">Status</th>
                                <th className="px-4 py-3">
                                    <button
                                        type="button"
                                        onClick={() => toggleSort('score')}
                                        className="inline-flex items-center gap-1 font-semibold hover:text-[var(--accent)]"
                                    >
                                        Fit <ArrowDownUp size={13} />
                                    </button>
                                </th>
                                <th className="px-4 py-3">
                                    <button
                                        type="button"
                                        onClick={() => toggleSort('date')}
                                        className="inline-flex items-center gap-1 font-semibold hover:text-[var(--accent)]"
                                    >
                                        Date <ArrowDownUp size={13} />
                                    </button>
                                </th>
                                <th className="px-4 py-3">Link</th>
                                <th className="px-4 py-3">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {displayedApps.map((app) => {
                                const rowMinMatchScore = appMinMatchScore(app, minMatchScore);
                                const blockReason = actionBlockReason(app, rowMinMatchScore);
                                return (
                                    <tr key={app.id} className="border-t border-[var(--line)] hover:bg-[var(--page)]">
                                        <td className="px-4 py-4 align-middle">
                                            <div className="max-w-[320px]">
                                                <p className="truncate font-semibold text-[var(--ink)]">{app.job_title}</p>
                                                <p className="mt-1 truncate text-sm text-[var(--muted)]">{app.company}</p>
                                                {app.pre_screen_reasons?.length ? (
                                                    <p className="mt-1 line-clamp-2 text-xs leading-5 text-[var(--muted)]">
                                                        {app.pre_screen_reasons[0]}
                                                    </p>
                                                ) : null}
                                            </div>
                                        </td>
                                        <td className="px-4 py-4 align-middle text-[var(--muted)]">
                                            <span className="inline-block max-w-[160px] truncate text-sm" title={app.matching_profile_name || undefined}>
                                                {app.matching_profile_name || 'Default profile'}
                                            </span>
                                        </td>
                                        <td className="px-4 py-4 align-middle">
                                            <StatusChip tone={statusTone(app.status)}>{app.status}</StatusChip>
                                        </td>
                                        <td className="px-4 py-4 align-middle">
                                            {scoreOrScreenChip(app, rowMinMatchScore)}
                                        </td>
                                        <td className="px-4 py-4 align-middle text-[var(--muted)]">
                                            {new Date(app.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                                        </td>
                                        <td className="px-4 py-4 align-middle">
                                            <StatusChip tone={resolutionTone(app.resolution_status)} title={app.resolution_notes || undefined}>
                                                {resolutionLabel(app)}
                                            </StatusChip>
                                        </td>
                                        <td className="px-4 py-4 align-middle">
                                            <div className="flex flex-wrap items-center gap-2">
                                                <Button
                                                    variant="secondary"
                                                    size="sm"
                                                    onClick={() => setSelectedApp(app)}
                                                    disabled={Boolean(blockReason)}
                                                    title={blockReason || undefined}
                                                >
                                                    <Box size={15} />
                                                    Package
                                                </Button>
                                                {app.job_url ? (
                                                    <a
                                                        href={app.resolved_url || app.job_url}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-[var(--line)] bg-white px-3 text-xs font-semibold text-[var(--muted)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
                                                    >
                                                        <ExternalLink size={14} />
                                                        Open
                                                    </a>
                                                ) : (
                                                    <IconButton label="No job URL" variant="ghost" size="sm" disabled>
                                                        <ArchiveX size={15} />
                                                    </IconButton>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};
