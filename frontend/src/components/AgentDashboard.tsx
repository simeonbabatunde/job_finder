import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArchiveX, ArrowDownUp, Box, ExternalLink, RefreshCw, Trash2 } from 'lucide-react';
import { getAuthHeaders, API_URL } from '../api/client';
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

export const AgentDashboard: React.FC<AgentDashboardProps> = ({ limit, fullPage = false, compact = false }) => {
    const [applications, setApplications] = useState<Application[]>([]);
    const [loading, setLoading] = useState(true);
    const [clearing, setClearing] = useState(false);
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

    return (
        <div className="mt-5 min-w-0">
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
                        {fullPage ? 'All applications' : 'Recent matches'}
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

            {loading ? (
                <div className="flex justify-center rounded-lg border border-[var(--line)] bg-white py-10">
                    <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--line)] border-t-[var(--accent)]" />
                </div>
            ) : applications.length === 0 ? (
                <EmptyState
                    title="No matched jobs yet."
                    detail="Run the agent after uploading a resume and setting preferences."
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
                                {app.job_url ? (
                                    <a
                                        href={app.job_url}
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
                    <table className="w-full min-w-[760px] border-collapse text-left text-sm">
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
                                        <div className="flex items-center gap-2">
                                            <Button
                                                variant="secondary"
                                                size="sm"
                                                onClick={() => setSelectedApp(app)}
                                            >
                                                <Box size={15} />
                                                Package
                                            </Button>
                                            {app.job_url ? (
                                                <a
                                                    href={app.job_url}
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
