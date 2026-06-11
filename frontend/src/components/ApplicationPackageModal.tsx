import React, { useState } from 'react';
import {
    AlignLeft,
    Building2,
    Check,
    Clipboard,
    Copy,
    Download,
    ExternalLink,
    FileText,
    HelpCircle,
    LoaderCircle,
    MessageSquareText,
    RefreshCw,
    Sparkles,
    Target,
    X,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { getErrorMessage, prepareApplication, downloadCoverLetterPdf, updateApplicationStatus } from '../api/client';
import { cn } from '../lib/cn';
import { Button, IconButton, Notice, StatusChip } from './ui';

interface QAItem { question: string; answer: string; }
interface InterviewQuestion { question: string; suggested_answer: string; }
interface CompanyBrief {
    overview?: string;
    mission?: string;
    culture_signals?: string[];
    questions_to_ask?: string[];
}
interface ApplicationPackage {
    cover_letter?: string;
    tailored_summary?: string;
    talking_points?: string[];
    qa_answers?: QAItem[];
    interview_questions?: InterviewQuestion[];
    company_brief?: CompanyBrief;
}

interface Props {
    app: {
        id: number;
        job_title: string;
        company: string;
        job_url: string;
        status: string;
        cover_letter?: string;
    };
    onClose: () => void;
    onStatusChange: (appId: number, status: string) => void;
}

type Tab = 'cover_letter' | 'summary' | 'talking_points' | 'qa' | 'interview' | 'company';

const STATUS_PIPELINE = [
    { key: 'Applied', label: 'Applied', tone: 'success' },
    { key: 'Phone Screen', label: 'Phone screen', tone: 'accent' },
    { key: 'Interview', label: 'Interview', tone: 'accent' },
    { key: 'Take-Home', label: 'Take-home', tone: 'warning' },
    { key: 'Offer', label: 'Offer', tone: 'success' },
    { key: 'Rejected', label: 'Rejected', tone: 'danger' },
    { key: 'No Response', label: 'No response', tone: 'neutral' },
] as const;

type StatusTone = (typeof STATUS_PIPELINE)[number]['tone'];

function toneForStatus(status: string): StatusTone {
    return STATUS_PIPELINE.find(s => s.key === status)?.tone ?? 'neutral';
}

function StatusPipeline({ current, onChange, saving }: { current: string; onChange: (s: string) => void; saving: boolean }) {
    return (
        <div className="border-b border-[var(--line)] bg-white px-5 py-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Application status</p>
            <div className="flex flex-wrap gap-2">
                {STATUS_PIPELINE.map((s) => (
                    <button
                        key={s.key}
                        type="button"
                        onClick={() => onChange(s.key)}
                        className={cn(
                            'rounded-md border px-2.5 py-1.5 text-xs font-semibold transition-colors',
                            current === s.key
                                ? 'border-transparent bg-[var(--accent)] text-white'
                                : 'border-[var(--line)] bg-white text-[var(--muted)] hover:border-[var(--accent)] hover:text-[var(--accent)]',
                        )}
                    >
                        {s.label}{saving && current === s.key ? '...' : ''}
                    </button>
                ))}
            </div>
        </div>
    );
}

const tabs: { key: Tab; label: string; Icon: LucideIcon; requiresPkg?: boolean }[] = [
    { key: 'cover_letter', label: 'Cover letter', Icon: FileText },
    { key: 'summary', label: 'Summary', Icon: AlignLeft, requiresPkg: true },
    { key: 'talking_points', label: 'Talking points', Icon: Sparkles, requiresPkg: true },
    { key: 'qa', label: 'Application Q&A', Icon: MessageSquareText, requiresPkg: true },
    { key: 'interview', label: 'Interview', Icon: Target, requiresPkg: true },
    { key: 'company', label: 'Company', Icon: Building2, requiresPkg: true },
];

function safeFilenamePart(value: string) {
    const cleaned = value
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
    return cleaned.slice(0, 64) || 'application';
}

function downloadTextFile(filename: string, content: string, type = 'text/markdown;charset=utf-8') {
    const blob = new Blob([content], { type });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
}

function listBlock(items?: string[]) {
    if (!items?.length) return '';
    return items.map(item => `- ${item}`).join('\n');
}

function buildPackageMarkdown(app: Props['app'], pkg: ApplicationPackage, coverLetter?: string | null) {
    const sections: string[] = [
        `# Application Package: ${app.job_title}`,
        `Company: ${app.company}`,
        app.job_url ? `Job URL: ${app.job_url}` : '',
        `Generated: ${new Date().toLocaleString()}`,
    ].filter(Boolean);

    if (coverLetter) {
        sections.push(`## Cover Letter\n\n${coverLetter}`);
    }

    if (pkg.tailored_summary) {
        sections.push(`## Tailored Resume Summary\n\n${pkg.tailored_summary}`);
    }

    if (pkg.talking_points?.length) {
        sections.push(`## Talking Points\n\n${listBlock(pkg.talking_points)}`);
    }

    if (pkg.qa_answers?.length) {
        sections.push([
            '## Application Q&A',
            ...pkg.qa_answers.map((qa, index) => `### ${index + 1}. ${qa.question}\n\n${qa.answer}`),
        ].join('\n\n'));
    }

    if (pkg.interview_questions?.length) {
        sections.push([
            '## Interview Prep',
            ...pkg.interview_questions.map((q, index) => `### ${index + 1}. ${q.question}\n\n${q.suggested_answer}`),
        ].join('\n\n'));
    }

    if (pkg.company_brief) {
        const companySections = ['## Company Brief'];
        if (pkg.company_brief.overview) {
            companySections.push(`### Overview\n\n${pkg.company_brief.overview}`);
        }
        if (pkg.company_brief.mission) {
            companySections.push(`### Mission and Values\n\n${pkg.company_brief.mission}`);
        }
        if (pkg.company_brief.culture_signals?.length) {
            companySections.push(`### Culture Signals\n\n${listBlock(pkg.company_brief.culture_signals)}`);
        }
        if (pkg.company_brief.questions_to_ask?.length) {
            companySections.push(`### Questions to Ask\n\n${listBlock(pkg.company_brief.questions_to_ask)}`);
        }
        if (companySections.length > 1) {
            sections.push(companySections.join('\n\n'));
        }
    }

    return `${sections.join('\n\n')}\n`;
}

export const ApplicationPackageModal: React.FC<Props> = ({ app, onClose, onStatusChange }) => {
    const [pkg, setPkg] = useState<ApplicationPackage | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [activeTab, setActiveTab] = useState<Tab>('cover_letter');
    const [copiedKey, setCopiedKey] = useState<string | null>(null);
    const [downloading, setDownloading] = useState(false);
    const [currentStatus, setCurrentStatus] = useState(app.status);
    const [savingStatus, setSavingStatus] = useState(false);
    const [coverLetterOverride] = useState<string | null>(app.cover_letter || null);

    const generate = async () => {
        setLoading(true);
        setError('');
        try {
            const result = await prepareApplication({
                app_id: app.id,
                title: app.job_title,
                company: app.company,
            });
            setPkg(result);
            setActiveTab('cover_letter');
        } catch (e) {
            setError(getErrorMessage(e, 'Failed to generate package'));
        } finally {
            setLoading(false);
        }
    };

    const handleStatusChange = async (newStatus: string) => {
        if (newStatus === currentStatus) return;
        setSavingStatus(true);
        try {
            await updateApplicationStatus(app.id, newStatus);
            setCurrentStatus(newStatus);
            onStatusChange(app.id, newStatus);
        } catch {
            setError('Failed to update status');
        } finally {
            setSavingStatus(false);
        }
    };

    const copyText = (text: string, key: string) => {
        navigator.clipboard.writeText(text);
        setCopiedKey(key);
        setTimeout(() => setCopiedKey(null), 2000);
    };

    const handleDownloadPdf = async () => {
        setDownloading(true);
        try {
            await downloadCoverLetterPdf(app.id);
        } catch {
            setError('PDF download failed. Generate the package first.');
        } finally {
            setDownloading(false);
        }
    };

    const handleDownloadPackage = () => {
        if (!pkg) return;
        const filename = [
            'application-package',
            safeFilenamePart(app.company),
            safeFilenamePart(app.job_title),
        ].join('-');
        downloadTextFile(`${filename}.md`, buildPackageMarkdown(app, pkg, pkg.cover_letter || coverLetterOverride));
    };

    const coverLetter = pkg?.cover_letter || coverLetterOverride;
    const visibleTabs = tabs.filter(t => !t.requiresPkg || !!pkg);

    const CopySmallButton = ({ text, id, label = 'Copy' }: { text: string; id: string; label?: string }) => (
        <Button variant="ghost" size="sm" onClick={() => copyText(text, id)}>
            {copiedKey === id ? <Check size={14} /> : <Copy size={14} />}
            {copiedKey === id ? 'Copied' : label}
        </Button>
    );

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm"
            onClick={e => { if (e.target === e.currentTarget) onClose(); }}
        >
            <div className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg border border-[var(--line)] bg-white shadow-2xl">
                <div className="flex shrink-0 items-start justify-between gap-4 border-b border-[var(--line)] bg-white px-5 py-5">
                    <div className="min-w-0">
                        <div className="mb-2 flex flex-wrap items-center gap-2">
                            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--accent)]">
                                Generated application kit
                            </p>
                            <StatusChip tone={toneForStatus(currentStatus)}>
                                {currentStatus}{savingStatus ? '...' : ''}
                            </StatusChip>
                        </div>
                        <h2 className="truncate text-xl font-semibold text-[var(--ink)]">{app.job_title}</h2>
                        <p className="mt-1 text-sm text-[var(--muted)]">{app.company}</p>
                    </div>
                    <IconButton label="Close package" variant="ghost" size="sm" onClick={onClose}>
                        <X size={18} />
                    </IconButton>
                </div>

                <StatusPipeline current={currentStatus} onChange={handleStatusChange} saving={savingStatus} />

                <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[var(--line)] bg-[var(--page)] px-5 py-3">
                    <Button onClick={generate} disabled={loading}>
                        {loading ? <LoaderCircle className="animate-spin" size={16} /> : <Sparkles size={16} />}
                        {pkg ? 'Regenerate kit' : 'Generate application kit'}
                    </Button>

                    {coverLetter && (
                        <Button variant="secondary" onClick={() => copyText(coverLetter, 'cover_bar')}>
                            {copiedKey === 'cover_bar' ? <Check size={16} /> : <Clipboard size={16} />}
                            {copiedKey === 'cover_bar' ? 'Copied' : 'Copy letter'}
                        </Button>
                    )}

                    {pkg && (
                        <Button variant="secondary" onClick={handleDownloadPackage}>
                            <Download size={16} />
                            Download package
                        </Button>
                    )}

                    {coverLetter && (
                        <Button variant="secondary" onClick={handleDownloadPdf} disabled={downloading}>
                            {downloading ? <LoaderCircle className="animate-spin" size={16} /> : <Download size={16} />}
                            Cover PDF
                        </Button>
                    )}

                    <a
                        href={app.job_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="ml-auto inline-flex min-h-10 items-center gap-2 rounded-md border border-[var(--line)] bg-white px-4 text-sm font-semibold text-[var(--ink)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
                    >
                        <ExternalLink size={16} />
                        Open job
                    </a>
                </div>

                {error && (
                    <Notice tone="error" className="mx-5 mt-3 shrink-0">
                        {error}
                    </Notice>
                )}

                {(pkg || coverLetter) && (
                    <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-[var(--line)] bg-white px-5 pt-3">
                        {visibleTabs.map(tab => {
                            const Icon = tab.Icon;
                            return (
                                <button
                                    key={tab.key}
                                    onClick={() => setActiveTab(tab.key)}
                                    className={cn(
                                        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-t-md border-b-2 px-3 py-2 text-xs font-semibold transition-colors',
                                        activeTab === tab.key
                                            ? 'border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]'
                                            : 'border-transparent text-[var(--muted)] hover:text-[var(--ink)]',
                                    )}
                                >
                                    <Icon size={14} />
                                    {tab.label}
                                </button>
                            );
                        })}
                    </div>
                )}

                <div className="flex-1 overflow-y-auto p-5">
                    {!pkg && !coverLetter && !loading && (
                        <div className="flex min-h-60 flex-col items-center justify-center rounded-lg border border-dashed border-[var(--line)] bg-[var(--page)] p-8 text-center">
                            <HelpCircle size={36} className="mb-3 text-[var(--accent)]" />
                            <p className="text-lg font-semibold text-[var(--ink)]">Turn this match into application-ready materials</p>
                            <p className="mt-2 max-w-md text-sm leading-6 text-[var(--muted)]">
                                Generate a cover letter, tailored summary, application Q&A, interview prep, and company brief built from your resume and this role.
                            </p>
                        </div>
                    )}

                    {loading && (
                        <div className="flex min-h-60 flex-col items-center justify-center text-center">
                            <LoaderCircle size={36} className="mb-3 animate-spin text-[var(--accent)]" />
                            <p className="text-sm font-semibold text-[var(--ink)]">Packaging this application</p>
                            <p className="mt-1 text-xs text-[var(--muted)]">Matching your resume, preferences, and job details.</p>
                        </div>
                    )}

                    {!loading && activeTab === 'cover_letter' && coverLetter && (
                        <div>
                            <div className="mb-3 flex items-center justify-between gap-3">
                                <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Cover letter</h3>
                                <CopySmallButton text={coverLetter} id="cl" />
                            </div>
                            <div className="whitespace-pre-wrap rounded-lg border border-[var(--line)] bg-[var(--page)] p-5 font-serif text-sm leading-7 text-[var(--ink)]">
                                {coverLetter}
                            </div>
                        </div>
                    )}

                    {!loading && activeTab === 'summary' && pkg?.tailored_summary && (
                        <div>
                            <div className="mb-3 flex items-center justify-between gap-3">
                                <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Tailored resume summary</h3>
                                <CopySmallButton text={pkg.tailored_summary} id="summary" />
                            </div>
                            <div className="rounded-lg border border-[var(--line)] bg-[var(--page)] p-5 text-sm leading-6 text-[var(--ink)]">
                                {pkg.tailored_summary}
                            </div>
                        </div>
                    )}

                    {!loading && activeTab === 'talking_points' && pkg?.talking_points && (
                        <div>
                            <div className="mb-3 flex items-center justify-between gap-3">
                                <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Talking points</h3>
                                <CopySmallButton text={pkg.talking_points.map(p => `- ${p}`).join('\n')} id="talking-points" label="Copy all" />
                            </div>
                            <div className="space-y-2">
                                {pkg.talking_points.map((point, i) => (
                                    <div key={`${point}-${i}`} className="flex items-start gap-3 rounded-lg border border-[var(--line)] bg-white p-3">
                                        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[var(--accent-soft)] text-xs font-semibold text-[var(--accent)]">{i + 1}</span>
                                        <p className="flex-1 text-sm leading-6 text-[var(--ink)]">{point}</p>
                                        <IconButton label="Copy talking point" variant="ghost" size="sm" onClick={() => copyText(point, `point-${i}`)}>
                                            {copiedKey === `point-${i}` ? <Check size={14} /> : <Copy size={14} />}
                                        </IconButton>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {!loading && activeTab === 'qa' && pkg?.qa_answers && (
                        <div className="space-y-3">
                            <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Pre-written Q&A answers</h3>
                            {pkg.qa_answers.map((qa, i) => (
                                <div key={`${qa.question}-${i}`} className="overflow-hidden rounded-lg border border-[var(--line)]">
                                    <div className="flex items-start justify-between gap-3 bg-[var(--soft)] px-4 py-3">
                                        <p className="text-sm font-semibold text-[var(--ink)]">{qa.question}</p>
                                        <IconButton label="Copy answer" variant="ghost" size="sm" onClick={() => copyText(qa.answer, `qa-${i}`)}>
                                            {copiedKey === `qa-${i}` ? <Check size={14} /> : <Copy size={14} />}
                                        </IconButton>
                                    </div>
                                    <p className="p-4 text-sm leading-6 text-[var(--ink)]">{qa.answer}</p>
                                </div>
                            ))}
                        </div>
                    )}

                    {!loading && activeTab === 'interview' && pkg?.interview_questions && (
                        <div className="space-y-3">
                            <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Likely interview questions</h3>
                            {pkg.interview_questions.map((q, i) => (
                                <div key={`${q.question}-${i}`} className="overflow-hidden rounded-lg border border-[var(--line)]">
                                    <div className="flex items-start justify-between gap-3 bg-[var(--soft)] px-4 py-3">
                                        <p className="text-sm font-semibold text-[var(--ink)]">{q.question}</p>
                                        <IconButton label="Copy answer" variant="ghost" size="sm" onClick={() => copyText(q.suggested_answer, `interview-${i}`)}>
                                            {copiedKey === `interview-${i}` ? <Check size={14} /> : <Copy size={14} />}
                                        </IconButton>
                                    </div>
                                    <p className="p-4 text-sm leading-6 text-[var(--ink)]">{q.suggested_answer}</p>
                                </div>
                            ))}
                        </div>
                    )}

                    {!loading && activeTab === 'company' && pkg?.company_brief && (
                        <div className="space-y-5">
                            {pkg.company_brief.overview && (
                                <section>
                                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Company overview</h3>
                                    <p className="rounded-lg border border-[var(--line)] bg-[var(--page)] p-4 text-sm leading-6 text-[var(--ink)]">
                                        {pkg.company_brief.overview}
                                    </p>
                                </section>
                            )}

                            {pkg.company_brief.mission && (
                                <section>
                                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Mission and values</h3>
                                    <p className="rounded-lg border border-[var(--line)] bg-white p-4 text-sm leading-6 text-[var(--ink)]">
                                        {pkg.company_brief.mission}
                                    </p>
                                </section>
                            )}

                            {pkg.company_brief.culture_signals && pkg.company_brief.culture_signals.length > 0 && (
                                <section>
                                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Culture signals</h3>
                                    <div className="flex flex-wrap gap-2">
                                        {pkg.company_brief.culture_signals.map((signal, i) => (
                                            <StatusChip key={`${signal}-${i}`} tone="accent">{signal}</StatusChip>
                                        ))}
                                    </div>
                                </section>
                            )}

                            {pkg.company_brief.questions_to_ask && pkg.company_brief.questions_to_ask.length > 0 && (
                                <section>
                                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Questions to ask</h3>
                                    <div className="space-y-2">
                                        {pkg.company_brief.questions_to_ask.map((q, i) => (
                                            <div key={`${q}-${i}`} className="flex items-start gap-3 rounded-lg border border-[var(--line)] bg-white p-3">
                                                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[var(--accent-soft)] text-xs font-semibold text-[var(--accent)]">{i + 1}</span>
                                                <p className="flex-1 text-sm leading-6 text-[var(--ink)]">{q}</p>
                                                <IconButton label="Copy question" variant="ghost" size="sm" onClick={() => copyText(q, `question-${i}`)}>
                                                    {copiedKey === `question-${i}` ? <Check size={14} /> : <Copy size={14} />}
                                                </IconButton>
                                            </div>
                                        ))}
                                    </div>
                                </section>
                            )}
                        </div>
                    )}

                    {!loading && pkg && (
                        <Button variant="ghost" size="sm" onClick={generate} className="mt-5">
                            <RefreshCw size={14} />
                            Refresh package
                        </Button>
                    )}
                </div>
            </div>
        </div>
    );
};
