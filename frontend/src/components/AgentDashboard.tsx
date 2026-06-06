import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArchiveX, ArrowDownUp, Box, Camera, ClipboardCheck, Download, ExternalLink, Link2, RefreshCw, ShieldCheck, Trash2, X } from 'lucide-react';
import {
    checkApplicationSubmitReadiness,
    clearApplicationFillReviews,
    createApplicationSubmitConfirmation,
    fetchFillReviewArtifact,
    fillApplicationForReview,
    getApplicationAutomationAttempts,
    getApplicationFillReviews,
    getAuthHeaders,
    API_URL,
    resolveApplicationLink,
} from '../api/client';
import type { ApplicationFillReviewRecord, ApplicationFillReviewResult, ApplicationSubmitConfirmation, ApplicationSubmitReadiness, AutoApplyAttemptRecord } from '../api/client';
import { isSupportedFillReviewAts } from '../lib/supportedAts';
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
    pre_screen_status?: string;
    pre_screen_reasons?: string[];
}

interface AgentDashboardProps {
    limit?: number;
    fullPage?: boolean;
    compact?: boolean;
    minMatchScore?: number;
}

type MatchView = 'strong' | 'below_threshold';

const matchViews: { key: MatchView; label: string }[] = [
    { key: 'strong', label: 'Strong matches' },
    { key: 'below_threshold', label: 'Below threshold' },
];

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

function attemptTone(status: string): 'neutral' | 'accent' | 'success' | 'warning' | 'danger' {
    if (status.includes('ready') || status.includes('success') || status.includes('detected') || status.includes('completed')) return 'success';
    if (status.includes('blocked')) return 'warning';
    if (status.includes('failed')) return 'danger';
    if (status.includes('filling') || status.includes('confirming')) return 'accent';
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
    return app.resolution_status === 'resolved'
        && isSupportedFillReviewAts(app.ats_type);
}

function isScreenedOut(app: Application) {
    return app.pre_screen_status === 'reject' || app.status === 'Screened Out';
}

function isBelowThreshold(app: Application, minMatchScore: number) {
    return !isScreenedOut(app) && app.fit_score > 0 && app.fit_score * 100 < minMatchScore;
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

export const AgentDashboard: React.FC<AgentDashboardProps> = ({ limit, fullPage = false, compact = false, minMatchScore = 70 }) => {
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
    const [artifactPreviewUrl, setArtifactPreviewUrl] = useState<string | null>(null);
    const [artifactLoadingId, setArtifactLoadingId] = useState<number | null>(null);
    const [automationAttempts, setAutomationAttempts] = useState<AutoApplyAttemptRecord[]>([]);
    const [submitReadiness, setSubmitReadiness] = useState<ApplicationSubmitReadiness | null>(null);
    const [submitReadinessLoading, setSubmitReadinessLoading] = useState(false);
    const [submitConfirmation, setSubmitConfirmation] = useState<ApplicationSubmitConfirmation | null>(null);
    const [submitConfirmationLoading, setSubmitConfirmationLoading] = useState(false);
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
    }, [fullPage, limit, matchView, sortBy, sortDir]);

    useEffect(() => {
        void fetchApplications();
    }, [fetchApplications]);

    useEffect(() => {
        return () => {
            if (artifactPreviewUrl) {
                URL.revokeObjectURL(artifactPreviewUrl);
            }
        };
    }, [artifactPreviewUrl]);

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
    const currentEmpty = emptyStateCopy(fullPage ? matchView : 'strong');
    const pipelineCountLabel = matchView === 'below_threshold'
        ? `${applications.length} below-threshold role${applications.length === 1 ? '' : 's'}`
        : `${applications.length} strong match${applications.length === 1 ? '' : 'es'}`;

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
        setArtifactPreviewUrl(null);
        setAutomationAttempts([]);
        setSubmitReadiness(null);
        setSubmitConfirmation(null);
        try {
            const result = await fillApplicationForReview(app.id);
            const history = await getApplicationFillReviews(app.id).catch(() => []);
            const attempts = await getApplicationAutomationAttempts(app.id).catch(() => []);
            const updatedApp = { ...app, status: result.application_status };
            setApplications(prev => prev.map(item => item.id === app.id ? updatedApp : item));
            setSelectedApp(prev => prev?.id === app.id ? updatedApp : prev);
            setAutomationAttempts(attempts);
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
            setArtifactPreviewUrl(null);
            const attempts = await getApplicationAutomationAttempts(fillReview.app.id).catch(() => []);
            setAutomationAttempts(attempts);
        } catch (error) {
            setLinkError(error instanceof Error ? error.message : 'Failed to clear fill-review history');
        }
    };

    const closeFillReview = () => {
        setFillReview(null);
        setArtifactPreviewUrl(null);
        setAutomationAttempts([]);
        setSubmitReadiness(null);
        setSubmitConfirmation(null);
    };

    const handleCheckSubmitReadiness = async () => {
        if (!fillReview) return;

        setSubmitReadinessLoading(true);
        setLinkError(null);
        setSubmitConfirmation(null);
        try {
            const result = await checkApplicationSubmitReadiness(fillReview.app.id);
            setSubmitReadiness(result);
        } catch (error) {
            setLinkError(error instanceof Error ? error.message : 'Failed to check final-submit readiness');
        } finally {
            setSubmitReadinessLoading(false);
        }
    };

    const handleCreateSubmitConfirmation = async () => {
        if (!fillReview) return;

        setSubmitConfirmationLoading(true);
        setLinkError(null);
        try {
            const result = await createApplicationSubmitConfirmation(fillReview.app.id);
            setSubmitConfirmation(result);
            setSubmitReadiness(result.readiness);
            const attempts = await getApplicationAutomationAttempts(fillReview.app.id).catch(() => []);
            setAutomationAttempts(attempts);
        } catch (error) {
            setLinkError(error instanceof Error ? error.message : 'Failed to prepare final confirmation');
        } finally {
            setSubmitConfirmationLoading(false);
        }
    };

    const handleViewFillReviewScreenshot = async (record: ApplicationFillReviewRecord) => {
        if (!record.screenshot_url) return;

        setArtifactLoadingId(record.id);
        setLinkError(null);
        try {
            const blob = await fetchFillReviewArtifact(record.screenshot_url);
            setArtifactPreviewUrl(URL.createObjectURL(blob));
        } catch (error) {
            setLinkError(error instanceof Error ? error.message : 'Failed to load saved screenshot');
        } finally {
            setArtifactLoadingId(null);
        }
    };

    const handleDownloadFillReviewTrace = async (record: ApplicationFillReviewRecord) => {
        if (!record.trace_url) return;

        setArtifactLoadingId(record.id);
        setLinkError(null);
        try {
            const blob = await fetchFillReviewArtifact(record.trace_url);
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement('a');
            anchor.href = url;
            anchor.download = `fill-review-${record.id}-trace.zip`;
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
            URL.revokeObjectURL(url);
        } catch (error) {
            setLinkError(error instanceof Error ? error.message : 'Failed to download trace');
        } finally {
            setArtifactLoadingId(null);
        }
    };

    const fillReviewPreviewSrc = fillReview
        ? artifactPreviewUrl || (fillReview.result.screenshot_base64
            ? `data:image/png;base64,${fillReview.result.screenshot_base64}`
            : null)
        : null;

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
                                onClick={closeFillReview}
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
                        {fillReviewPreviewSrc && (
                            <div className="border-t border-[var(--line)] px-5 py-4">
                                <h4 className="mb-2 text-sm font-semibold text-[var(--ink)]">Prepared form preview</h4>
                                <div className="max-h-[360px] overflow-auto rounded-md border border-[var(--line)] bg-[var(--page)]">
                                    <img
                                        src={fillReviewPreviewSrc}
                                        alt="Prepared application form preview"
                                        className="w-full"
                                    />
                                </div>
                            </div>
                        )}
                        {submitReadiness && (
                            <div className="border-t border-[var(--line)] px-5 py-4">
                                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                                    <h4 className="text-sm font-semibold text-[var(--ink)]">Final-submit readiness</h4>
                                    <StatusChip tone={submitReadiness.ready ? 'success' : 'warning'}>
                                        {submitReadiness.status.replaceAll('_', ' ')}
                                    </StatusChip>
                                </div>
                                <p className="text-sm leading-6 text-[var(--muted)]">{submitReadiness.message}</p>
                                {submitReadiness.blockers.length > 0 && (
                                    <div className="mt-3">
                                        <p className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-[var(--warning)]">Blockers</p>
                                        <ul className="space-y-1 text-sm">
                                            {submitReadiness.blockers.map(item => (
                                                <li key={item} className="rounded-md bg-[var(--warning-soft)] px-2 py-1 text-[var(--warning)]">{item}</li>
                                            ))}
                                        </ul>
                                    </div>
                                )}
                                {submitReadiness.checks.length > 0 && (
                                    <div className="mt-3">
                                        <p className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-[var(--positive)]">Passed checks</p>
                                        <ul className="space-y-1 text-sm">
                                            {submitReadiness.checks.map(item => (
                                                <li key={item} className="rounded-md bg-[var(--positive-soft)] px-2 py-1 text-[var(--positive)]">{item}</li>
                                            ))}
                                        </ul>
                                    </div>
                                )}
                                {submitReadiness.warnings.length > 0 && (
                                    <p className="mt-3 rounded-md bg-[var(--soft)] px-3 py-2 text-xs font-semibold leading-5 text-[var(--muted)]">
                                        {submitReadiness.warnings[0]}
                                    </p>
                                )}
                            </div>
                        )}
                        {submitConfirmation && (
                            <div className="border-t border-[var(--line)] px-5 py-4">
                                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                                    <h4 className="text-sm font-semibold text-[var(--ink)]">Final confirmation</h4>
                                    <StatusChip tone={submitConfirmation.ready ? 'success' : 'warning'}>
                                        {submitConfirmation.status.replaceAll('_', ' ')}
                                    </StatusChip>
                                </div>
                                <p className="text-sm leading-6 text-[var(--muted)]">{submitConfirmation.message}</p>
                                <div className="mt-3 grid gap-2 sm:grid-cols-3">
                                    <div className="rounded-md border border-[var(--line)] bg-[var(--page)] px-3 py-2">
                                        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">Control</p>
                                        <p className="mt-1 truncate text-sm font-semibold text-[var(--ink)]">
                                            {submitConfirmation.submit_control.label || 'Not detected'}
                                        </p>
                                    </div>
                                    <div className="rounded-md border border-[var(--line)] bg-[var(--page)] px-3 py-2">
                                        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">Confidence</p>
                                        <p className="mt-1 text-sm font-semibold text-[var(--ink)]">
                                            {(submitConfirmation.submit_control.confidence * 100).toFixed(0)}%
                                        </p>
                                    </div>
                                    <div className="rounded-md border border-[var(--line)] bg-[var(--page)] px-3 py-2">
                                        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">Selector</p>
                                        <p className="mt-1 truncate text-sm font-semibold text-[var(--ink)]">
                                            {submitConfirmation.submit_control.selector || 'Unavailable'}
                                        </p>
                                    </div>
                                </div>
                                {submitConfirmation.blockers.length > 0 && (
                                    <div className="mt-3">
                                        <p className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-[var(--warning)]">Blockers</p>
                                        <ul className="space-y-1 text-sm">
                                            {submitConfirmation.blockers.map(item => (
                                                <li key={item} className="rounded-md bg-[var(--warning-soft)] px-2 py-1 text-[var(--warning)]">{item}</li>
                                            ))}
                                        </ul>
                                    </div>
                                )}
                                {submitConfirmation.checks.length > 0 && (
                                    <div className="mt-3">
                                        <p className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-[var(--positive)]">Passed checks</p>
                                        <ul className="space-y-1 text-sm">
                                            {submitConfirmation.checks.map(item => (
                                                <li key={item} className="rounded-md bg-[var(--positive-soft)] px-2 py-1 text-[var(--positive)]">{item}</li>
                                            ))}
                                        </ul>
                                    </div>
                                )}
                                {submitConfirmation.warnings.length > 0 && (
                                    <p className="mt-3 rounded-md bg-[var(--soft)] px-3 py-2 text-xs font-semibold leading-5 text-[var(--muted)]">
                                        {submitConfirmation.warnings[0]}
                                    </p>
                                )}
                            </div>
                        )}
                        {automationAttempts.length > 0 && (
                            <div className="border-t border-[var(--line)] px-5 py-4">
                                <div className="mb-2 flex items-center justify-between gap-2">
                                    <h4 className="text-sm font-semibold text-[var(--ink)]">Automation timeline</h4>
                                    <StatusChip tone="neutral">{automationAttempts.length}</StatusChip>
                                </div>
                                <div className="space-y-2">
                                    {automationAttempts.slice(0, 4).map(attempt => (
                                        <div key={attempt.id} className="rounded-md border border-[var(--line)] bg-[var(--page)] px-3 py-2">
                                            <div className="flex flex-wrap items-center justify-between gap-2">
                                                <p className="text-sm font-semibold text-[var(--ink)]">
                                                    {attempt.mode.replaceAll('_', ' ')}
                                                </p>
                                                <StatusChip tone={attemptTone(attempt.status)}>
                                                    {attempt.status.replaceAll('_', ' ')}
                                                </StatusChip>
                                            </div>
                                            <p className="mt-1 text-xs text-[var(--muted)]">
                                                {new Date(attempt.updated_at).toLocaleString('en-US', {
                                                    month: 'short',
                                                    day: 'numeric',
                                                    hour: 'numeric',
                                                    minute: '2-digit',
                                                })}
                                                {' '}· confidence {(attempt.confidence_score * 100).toFixed(0)}%
                                            </p>
                                            {attempt.blocked_reason && (
                                                <p className="mt-2 rounded-md bg-[var(--warning-soft)] px-2 py-1 text-xs font-semibold text-[var(--warning)]">
                                                    {attempt.blocked_reason}
                                                </p>
                                            )}
                                            {attempt.steps?.length ? (
                                                <div className="mt-2 space-y-1 border-t border-[var(--line)] pt-2">
                                                    {attempt.steps.slice(-3).map(step => (
                                                        <div key={`${attempt.id}-${step.name}-${step.at}`} className="flex items-start justify-between gap-2">
                                                            <div className="min-w-0">
                                                                <p className="truncate text-xs font-semibold text-[var(--ink)]">
                                                                    {step.name.replaceAll('_', ' ')}
                                                                </p>
                                                                {step.message && (
                                                                    <p className="mt-0.5 line-clamp-2 text-xs leading-5 text-[var(--muted)]">
                                                                        {step.message}
                                                                    </p>
                                                                )}
                                                            </div>
                                                            <StatusChip tone={attemptTone(step.status)} className="min-h-6 shrink-0 px-2">
                                                                {step.status.replaceAll('_', ' ')}
                                                            </StatusChip>
                                                        </div>
                                                    ))}
                                                </div>
                                            ) : null}
                                        </div>
                                    ))}
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
                                            {(record.screenshot_url || record.trace_url) && (
                                                <div className="mt-2 flex flex-wrap gap-2">
                                                    {record.screenshot_url && (
                                                        <Button
                                                            variant="secondary"
                                                            size="sm"
                                                            disabled={artifactLoadingId === record.id}
                                                            onClick={() => void handleViewFillReviewScreenshot(record)}
                                                        >
                                                            <Camera size={14} />
                                                            Screenshot
                                                        </Button>
                                                    )}
                                                    {record.trace_url && (
                                                        <Button
                                                            variant="secondary"
                                                            size="sm"
                                                            disabled={artifactLoadingId === record.id}
                                                            onClick={() => void handleDownloadFillReviewTrace(record)}
                                                        >
                                                            <Download size={14} />
                                                            Trace
                                                        </Button>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                        <div className="flex flex-col gap-2 border-t border-[var(--line)] p-5 sm:flex-row sm:justify-end">
                            <Button variant="secondary" disabled={submitReadinessLoading} onClick={() => void handleCheckSubmitReadiness()}>
                                {submitReadinessLoading ? <RefreshCw className="animate-spin" size={16} /> : <ClipboardCheck size={16} />}
                                Check final readiness
                            </Button>
                            {submitReadiness?.ready && (
                                <Button variant="secondary" disabled={submitConfirmationLoading} onClick={() => void handleCreateSubmitConfirmation()}>
                                    {submitConfirmationLoading ? <RefreshCw className="animate-spin" size={16} /> : <ShieldCheck size={16} />}
                                    {submitConfirmationLoading ? 'Inspecting' : 'Inspect final step'}
                                </Button>
                            )}
                            <Button variant="secondary" onClick={closeFillReview}>
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
                            ? pipelineCountLabel
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
            {fullPage && (
                <div className="mb-4 flex flex-col gap-3 rounded-lg border border-[var(--line)] bg-white p-3 lg:flex-row lg:items-center lg:justify-between">
                    <div className="flex flex-wrap gap-2">
                        {matchViews.map(view => (
                            <Button
                                key={view.key}
                                variant={matchView === view.key ? 'primary' : 'secondary'}
                                size="sm"
                                onClick={() => setMatchView(view.key)}
                            >
                                {view.label}
                            </Button>
                        ))}
                    </div>
                    <p className="text-xs font-semibold text-[var(--muted)]">
                        Minimum match score: {minMatchScore}%
                    </p>
                </div>
            )}
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
                    title={currentEmpty.title}
                    detail={currentEmpty.detail}
                />
            ) : useCompactList ? (
                <div className="space-y-2">
                    {displayedApps.map((app) => {
                        const blockReason = actionBlockReason(app, minMatchScore);
                        return (
                            <article key={app.id} className="rounded-lg border border-[var(--line)] bg-white p-3">
                                <div className="flex items-start justify-between gap-3">
                                    <div className="min-w-0">
                                        <p className="truncate text-sm font-semibold text-[var(--ink)]">{app.job_title}</p>
                                        <p className="mt-1 truncate text-xs text-[var(--muted)]">{app.company}</p>
                                    </div>
                                    {scoreOrScreenChip(app, minMatchScore)}
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
                                    {canFillReview(app) && !blockReason && (
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
                        );
                    })}
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
                            {displayedApps.map((app) => {
                                const blockReason = actionBlockReason(app, minMatchScore);
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
                                        <td className="px-4 py-4 align-middle">
                                            <StatusChip tone={statusTone(app.status)}>{app.status}</StatusChip>
                                        </td>
                                        <td className="px-4 py-4 align-middle">
                                            {scoreOrScreenChip(app, minMatchScore)}
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
                                                {canFillReview(app) && !blockReason && (
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
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};
