import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArchiveX, ArrowDownUp, Box, ClipboardCheck, ExternalLink, Link2, RefreshCw, Trash2, X } from 'lucide-react';
import {
    clearApplicationFillReviews,
    fillApplicationForReview,
    getApplicationFillReviews,
    getAuthHeaders,
    API_URL,
    resolveApplicationLink,
} from '../api/client';
import type { ApplicationFillReviewRecord, ApplicationFillReviewResult } from '../api/client';
import { ApplicationPackageModal } from './ApplicationPackageModal';
import { Button, EmptyState, IconButton, StatusChip } from './ui';

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
}

interface AgentDashboardProps {
    limit?: number;
    fullPage?: boolean;
    compact?: boolean;
}

function statusTone(status: string): 'neutral' | 'accent' | 'success' | 'warning' | 'danger' {
    if (status === 'Submitted' || status === 'Applied' || status === 'Offer') return 'success';
    if (status === 'Analyzed' || status === 'Interview' || status === 'Phone Screen') return 'accent';
    if (status === 'Analysis Failed' || status === 'Rejected') return 'danger';
    if (status === 'Take-Home') return 'warning';
    return 'neutral';
}

function scoreTone(score: number): 'neutral' | 'accent' | 'success' | 'warning' {
    if (score > 0.8) return 'success';
    if (score > 0.6) return 'accent';
    if (score > 0.4) return 'warning';
    return 'neutral';
}

function formatSourceLabel(value?: string | null) {
    if (!value) return '';
    return value
        .split('_')
        .filter(Boolean)
        .map(part => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');
}

function resolutionTone(status?: string | null): 'neutral' | 'accent' | 'success' | 'warning' | 'danger' {
    if (status === 'resolved') return 'success';
    if (status === 'needs_resolution') return 'warning';
    if (status === 'login_required' || status === 'captcha') return 'warning';
    if (status === 'manual_review' || status === 'unsupported') return 'danger';
    return 'neutral';
}

function resolutionLabel(app: Application) {
    if (app.ats_type) return `ATS: ${formatSourceLabel(app.ats_type)}`;
    if (app.resolution_status === 'resolved') {
        return app.source_type === 'company_site' ? 'Company page' : 'Link ready';
    }
    if (app.resolution_status === 'needs_resolution') {
        return `${formatSourceLabel(app.source_type) || 'Source'} link`;
    }
    if (app.resolution_status === 'login_required') return 'Login needed';
    if (app.resolution_status === 'captcha') return 'Captcha';
    if (app.resolution_status === 'manual_review') return 'Review link';
    if (app.resolution_status === 'unsupported') return 'Unsupported';
    return 'Check link';
}

function canResolveLink(app: Application) {
    return Boolean(app.job_url) && app.resolution_status !== 'resolved';
}

function canFillReview(app: Application) {
    return app.resolution_status === 'resolved' && (app.ats_type === 'greenhouse' || app.ats_type === 'lever');
}

export const AgentDashboard: React.FC<AgentDashboardProps> = ({ limit, fullPage = false, compact = false }) => {
    const [applications, setApplications] = useState<Application[]>([]);
    const [loading, setLoading] = useState(true);
    const [clearing, setClearing] = useState(false);
    const [resolvingId, setResolvingId] = useState<number | null>(null);
    const [fillingId, setFillingId] = useState<number | null>(null);
    const [linkError, setLinkError] = useState<string | null>(null);
    const [fillReview, setFillReview] = useState<{
        app: Application;
        result: ApplicationFillReviewResult;
        history: ApplicationFillReviewRecord[];
    } | null>(null);
    const [sortBy, setSortBy] = useState<'date' | 'score'>('date');
    const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
    const [selectedApp, setSelectedApp] = useState<Application | null>(null);

    const fetchApplications = useCallback(async () => {
        setLoading(true);
        try {
            const params = new URLSearchParams({
                sort: fullPage ? sortBy : 'date',
                direction: fullPage ? sortDir : 'desc',
            });
            if (limit) {
                params.set('limit', String(limit));
            }

            const response = await fetch(`${API_URL}/applications?${params.toString()}`, {
                headers: getAuthHeaders()
            });
            if (!response.ok) {
                throw new Error('Failed to fetch applications');
            }
            const data = await response.json();
            setApplications(data);
        } catch (error) {
            console.error('Error fetching applications:', error);
        } finally {
            setLoading(false);
        }
    }, [fullPage, limit, sortBy, sortDir]);

    useEffect(() => {
        void fetchApplications();
    }, [fetchApplications]);

    const clearApplications = async () => {
        if (!confirm('Clear all application history? This cannot be undone.')) return;
        setClearing(true);
        try {
            await fetch(`${API_URL}/applications`, {
                method: 'DELETE',
                headers: getAuthHeaders()
            });
            setApplications([]);
            setSelectedApp(null);
        } catch (error) {
            console.error('Error clearing applications:', error);
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

    const handleStatusChange = (appId: number, status: string) => {
        setApplications(prev =>
            prev.map(a => a.id === appId ? { ...a, status } : a)
        );
    };

    const handleResolveLink = async (appId: number) => {
        setResolvingId(appId);
        setLinkError(null);
        try {
            const updatedApp = await resolveApplicationLink(appId) as Application;
            setApplications(prev => prev.map(app => app.id === appId ? updatedApp : app));
            setSelectedApp(prev => prev?.id === appId ? updatedApp : prev);
        } catch (error) {
            setLinkError(error instanceof Error ? error.message : 'Failed to resolve application link');
        } finally {
            setResolvingId(null);
        }
    };

    const handleFillReview = async (app: Application) => {
        setFillingId(app.id);
        setLinkError(null);
        try {
            const result = await fillApplicationForReview(app.id);
            const history = await getApplicationFillReviews(app.id).catch(() => []);
            const updatedApp = { ...app, status: result.application_status };
            setApplications(prev => prev.map(item => item.id === app.id ? updatedApp : item));
            setSelectedApp(prev => prev?.id === app.id ? updatedApp : prev);
            setFillReview({ app: updatedApp, result, history });
        } catch (error) {
            setLinkError(error instanceof Error ? error.message : 'Failed to prepare fill review');
        } finally {
            setFillingId(null);
        }
    };

    const handleClearFillHistory = async () => {
        if (!fillReview) return;
        if (!confirm('Clear saved fill-review attempts for this application?')) return;

        try {
            await clearApplicationFillReviews(fillReview.app.id);
            setFillReview(prev => prev ? { ...prev, history: [] } : prev);
        } catch (error) {
            setLinkError(error instanceof Error ? error.message : 'Failed to clear fill-review history');
        }
    };

    return (
        <div className="mt-5 min-w-0">
            {fillReview && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4">
                    <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-[var(--line)] bg-white shadow-xl">
                        <div className="flex items-start justify-between gap-4 border-b border-[var(--line)] p-5">
                            <div>
                                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--accent)]">Fill review</p>
                                <h3 className="mt-1 text-lg font-semibold text-[var(--ink)]">{fillReview.app.job_title}</h3>
                                <p className="mt-1 text-sm text-[var(--muted)]">{fillReview.result.message}</p>
                            </div>
                            <button
                                type="button"
                                onClick={() => setFillReview(null)}
                                className="rounded-md p-1.5 text-[var(--muted)] hover:bg-[var(--soft)] hover:text-[var(--ink)]"
                                aria-label="Close fill review"
                            >
                                <X size={18} />
                            </button>
                        </div>
                        <div className="grid gap-4 p-5 md:grid-cols-2">
                            <div>
                                <div className="mb-2 flex items-center justify-between gap-2">
                                    <h4 className="text-sm font-semibold text-[var(--ink)]">Filled fields</h4>
                                    <StatusChip tone="success">{fillReview.result.fields_filled.length}</StatusChip>
                                </div>
                                <ul className="space-y-1 text-sm text-[var(--muted)]">
                                    {fillReview.result.fields_filled.length ? fillReview.result.fields_filled.map(field => (
                                        <li key={field} className="rounded-md bg-[var(--positive-soft)] px-2 py-1 text-[var(--positive)]">{field}</li>
                                    )) : <li>No fields were filled.</li>}
                                </ul>
                            </div>
                            <div>
                                <div className="mb-2 flex items-center justify-between gap-2">
                                    <h4 className="text-sm font-semibold text-[var(--ink)]">Needs review</h4>
                                    <StatusChip tone={fillReview.result.fields_missing.length || fillReview.result.blockers.length ? 'warning' : 'success'}>
                                        {fillReview.result.fields_missing.length + fillReview.result.blockers.length}
                                    </StatusChip>
                                </div>
                                <ul className="space-y-1 text-sm text-[var(--muted)]">
                                    {[...fillReview.result.fields_missing, ...fillReview.result.blockers].length ? (
                                        [...fillReview.result.fields_missing, ...fillReview.result.blockers].map(item => (
                                            <li key={item} className="rounded-md bg-[var(--warning-soft)] px-2 py-1 text-[var(--warning)]">{item}</li>
                                        ))
                                    ) : (
                                        <li>No blockers found.</li>
                                    )}
                                </ul>
                            </div>
                        </div>
                        {fillReview.result.screenshot_base64 && (
                            <div className="border-t border-[var(--line)] px-5 py-4">
                                <h4 className="mb-2 text-sm font-semibold text-[var(--ink)]">Prepared form preview</h4>
                                <div className="max-h-[360px] overflow-auto rounded-md border border-[var(--line)] bg-[var(--page)]">
                                    <img
                                        src={`data:image/png;base64,${fillReview.result.screenshot_base64}`}
                                        alt="Prepared application form preview"
                                        className="w-full"
                                    />
                                </div>
                            </div>
                        )}
                        {fillReview.history.length > 0 && (
                            <div className="border-t border-[var(--line)] px-5 py-4">
                                <div className="mb-2 flex items-center justify-between gap-2">
                                    <h4 className="text-sm font-semibold text-[var(--ink)]">Saved review attempts</h4>
                                    <div className="flex items-center gap-2">
                                        <StatusChip tone="neutral">{fillReview.history.length}</StatusChip>
                                        <Button variant="danger" size="sm" onClick={() => void handleClearFillHistory()}>
                                            Clear
                                        </Button>
                                    </div>
                                </div>
                                <div className="space-y-2">
                                    {fillReview.history.slice(0, 5).map(record => (
                                        <div key={record.id} className="rounded-md border border-[var(--line)] bg-[var(--page)] px-3 py-2">
                                            <div className="flex flex-wrap items-center justify-between gap-2">
                                                <p className="text-sm font-semibold text-[var(--ink)]">
                                                    {new Date(record.created_at).toLocaleString('en-US', {
                                                        month: 'short',
                                                        day: 'numeric',
                                                        hour: 'numeric',
                                                        minute: '2-digit',
                                                    })}
                                                </p>
                                                <StatusChip tone={record.blockers.length ? 'warning' : 'success'}>
                                                    {record.status.replaceAll('_', ' ')}
                                                </StatusChip>
                                            </div>
                                            <p className="mt-1 text-xs text-[var(--muted)]">
                                                {record.fields_filled.length} filled / {record.fields_missing.length + record.blockers.length} needs review
                                            </p>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                        <div className="flex flex-col gap-2 border-t border-[var(--line)] p-5 sm:flex-row sm:justify-end">
                            <Button variant="secondary" onClick={() => setFillReview(null)}>
                                Close
                            </Button>
                            <a
                                href={fillReview.result.application_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-[var(--line)] bg-white px-4 text-sm font-semibold text-[var(--ink)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
                            >
                                <ExternalLink size={16} />
                                Open form
                            </a>
                        </div>
                    </div>
                </div>
            )}
            {selectedApp && (
                <ApplicationPackageModal
                    app={selectedApp}
                    onClose={() => setSelectedApp(null)}
                    onStatusChange={handleStatusChange}
                />
            )}

            <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                    <h3 className="text-lg font-semibold text-[var(--ink)]">
                        {fullPage ? 'Application pipeline' : 'Latest best-fit matches'}
                    </h3>
                    <p className="text-sm text-[var(--muted)]">
                        {fullPage
                            ? `${applications.length} tracked role${applications.length === 1 ? '' : 's'}`
                            : `${displayedApps.length} recent role${displayedApps.length === 1 ? '' : 's'}`}
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    {!fullPage && applications.length > 0 && (
                        <Button variant="secondary" size="sm" onClick={() => { window.location.href = '/applications'; }}>
                            View all
                        </Button>
                    )}
                    <Button variant="secondary" size="sm" onClick={() => void fetchApplications()}>
                        <RefreshCw size={15} />
                        Refresh
                    </Button>
                    {applications.length > 0 && fullPage && (
                        <Button
                            variant="danger"
                            size="sm"
                            onClick={clearApplications}
                            disabled={clearing}
                        >
                            <Trash2 size={15} />
                            {clearing ? 'Clearing' : 'Clear'}
                        </Button>
                    )}
                </div>
            </div>
            {linkError && (
                <p className="mb-3 rounded-md border border-[var(--danger-soft)] bg-[var(--danger-soft)] px-3 py-2 text-xs font-semibold text-[var(--danger)]">
                    {linkError}
                </p>
            )}

            {loading ? (
                <div className="flex justify-center rounded-lg border border-[var(--line)] bg-white py-10">
                    <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--line)] border-t-[var(--accent)]" />
                </div>
            ) : applications.length === 0 ? (
                <EmptyState
                    title="No best-fit jobs yet."
                    detail="Upload your resume, set preferences, then start matching to find roles that align with your background."
                />
            ) : useCompactList ? (
                <div className="space-y-2">
                    {displayedApps.map((app) => (
                        <article key={app.id} className="rounded-lg border border-[var(--line)] bg-white p-3">
                            <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                    <p className="truncate text-sm font-semibold text-[var(--ink)]">{app.job_title}</p>
                                    <p className="mt-1 truncate text-xs text-[var(--muted)]">{app.company}</p>
                                </div>
                                <StatusChip tone={scoreTone(app.fit_score)}>
                                    {(app.fit_score * 100).toFixed(0)}%
                                </StatusChip>
                            </div>
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
                                >
                                    <Box size={15} />
                                    Package
                                </Button>
                                {canResolveLink(app) && (
                                    <Button
                                        variant="secondary"
                                        size="sm"
                                        onClick={() => void handleResolveLink(app.id)}
                                        disabled={resolvingId === app.id}
                                    >
                                        {resolvingId === app.id ? (
                                            <RefreshCw size={14} className="animate-spin" />
                                        ) : (
                                            <Link2 size={14} />
                                        )}
                                        {resolvingId === app.id ? 'Resolving' : 'Resolve link'}
                                    </Button>
                                )}
                                {canFillReview(app) && (
                                    <Button
                                        variant="secondary"
                                        size="sm"
                                        onClick={() => void handleFillReview(app)}
                                        disabled={fillingId === app.id}
                                    >
                                        {fillingId === app.id ? (
                                            <RefreshCw size={14} className="animate-spin" />
                                        ) : (
                                            <ClipboardCheck size={14} />
                                        )}
                                        {fillingId === app.id ? 'Preparing' : 'Fill review'}
                                    </Button>
                                )}
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
                    ))}
                </div>
            ) : (
                <div className="w-full max-w-full overflow-x-auto rounded-lg border border-[var(--line)] bg-white">
                    <table className="w-full min-w-[900px] border-collapse text-left text-sm">
                        <thead className="bg-[var(--soft)] text-xs uppercase text-[var(--muted)]">
                            <tr>
                                <th className="px-4 py-3">Role</th>
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
                            {displayedApps.map((app) => (
                                <tr key={app.id} className="border-t border-[var(--line)] hover:bg-[var(--page)]">
                                    <td className="px-4 py-4 align-middle">
                                        <div className="max-w-[320px]">
                                            <p className="truncate font-semibold text-[var(--ink)]">{app.job_title}</p>
                                            <p className="mt-1 truncate text-sm text-[var(--muted)]">{app.company}</p>
                                        </div>
                                    </td>
                                    <td className="px-4 py-4 align-middle">
                                        <StatusChip tone={statusTone(app.status)}>{app.status}</StatusChip>
                                    </td>
                                    <td className="px-4 py-4 align-middle">
                                        <StatusChip tone={scoreTone(app.fit_score)}>
                                            {(app.fit_score * 100).toFixed(0)}%
                                        </StatusChip>
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
                                            >
                                                <Box size={15} />
                                                Package
                                            </Button>
                                            {canResolveLink(app) && (
                                                <Button
                                                    variant="secondary"
                                                    size="sm"
                                                    onClick={() => void handleResolveLink(app.id)}
                                                    disabled={resolvingId === app.id}
                                                >
                                                    {resolvingId === app.id ? (
                                                        <RefreshCw size={14} className="animate-spin" />
                                                    ) : (
                                                        <Link2 size={14} />
                                                    )}
                                                    {resolvingId === app.id ? 'Resolving' : 'Resolve link'}
                                                </Button>
                                            )}
                                            {canFillReview(app) && (
                                                <Button
                                                    variant="secondary"
                                                    size="sm"
                                                    onClick={() => void handleFillReview(app)}
                                                    disabled={fillingId === app.id}
                                                >
                                                    {fillingId === app.id ? (
                                                        <RefreshCw size={14} className="animate-spin" />
                                                    ) : (
                                                        <ClipboardCheck size={14} />
                                                    )}
                                                    {fillingId === app.id ? 'Preparing' : 'Fill review'}
                                                </Button>
                                            )}
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
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};
