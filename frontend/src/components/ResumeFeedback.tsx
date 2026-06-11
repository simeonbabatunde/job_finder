import { useState } from 'react';
import {
    Check,
    ChevronDown,
    ChevronUp,
    LoaderCircle,
    RefreshCw,
    Search,
    Sparkles,
    X,
} from 'lucide-react';
import { getErrorMessage, getResumeFeedback } from '../api/client';
import { Button, IconButton, Notice, ProgressBar, StatusChip } from './ui';

interface Category {
    name: string;
    score: number;
    issues: string[];
    suggestions: string[];
}

interface FeedbackResult {
    overall_score: number;
    overall_assessment: string;
    categories: Category[];
    quick_wins: string[];
    missing_keywords: string[];
}

function scoreTone(score: number): 'success' | 'accent' | 'warning' {
    if (score >= 75) return 'success';
    if (score >= 50) return 'accent';
    return 'warning';
}

function ScoreRing({ score }: { score: number }) {
    const color = score >= 75 ? 'var(--positive)' : score >= 50 ? 'var(--accent)' : '#a16207';
    return (
        <div className="relative h-20 w-20 shrink-0">
            <svg viewBox="0 0 36 36" className="h-20 w-20 -rotate-90">
                <circle cx="18" cy="18" r="15.9" fill="none" stroke="#dce2ea" strokeWidth="3" />
                <circle
                    cx="18"
                    cy="18"
                    r="15.9"
                    fill="none"
                    stroke={color}
                    strokeWidth="3"
                    strokeDasharray={`${score} 100`}
                    strokeLinecap="round"
                />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-xl font-semibold text-[var(--ink)]">{score}</span>
                <span className="text-[10px] font-semibold text-[var(--muted)]">/100</span>
            </div>
        </div>
    );
}

function CategoryBar({ cat }: { cat: Category }) {
    const [open, setOpen] = useState(false);

    return (
        <div className="overflow-hidden rounded-lg border border-[var(--line)]">
            <button
                type="button"
                onClick={() => setOpen(!open)}
                className="flex w-full items-center gap-3 p-3 text-left transition-colors hover:bg-[var(--page)]"
            >
                <div className="min-w-0 flex-1">
                    <div className="mb-2 flex items-center justify-between gap-3">
                        <span className="truncate text-sm font-semibold text-[var(--ink)]">{cat.name}</span>
                        <StatusChip tone={scoreTone(cat.score)}>{cat.score}/100</StatusChip>
                    </div>
                    <ProgressBar value={cat.score} />
                </div>
                {open ? <ChevronUp size={17} className="text-[var(--muted)]" /> : <ChevronDown size={17} className="text-[var(--muted)]" />}
            </button>

            {open && (
                <div className="space-y-3 border-t border-[var(--line)] bg-white px-3 py-3">
                    {cat.issues.length > 0 && (
                        <div>
                            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--danger)]">Issues found</p>
                            <ul className="space-y-1.5">
                                {cat.issues.map((issue, i) => (
                                    <li key={`${issue}-${i}`} className="flex items-start gap-2 text-xs leading-5 text-[var(--muted)]">
                                        <X size={13} className="mt-1 shrink-0 text-[var(--danger)]" />
                                        {issue}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                    {cat.suggestions.length > 0 && (
                        <div>
                            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--positive)]">How to fix</p>
                            <ul className="space-y-1.5">
                                {cat.suggestions.map((suggestion, i) => (
                                    <li key={`${suggestion}-${i}`} className="flex items-start gap-2 text-xs leading-5 text-[var(--muted)]">
                                        <Check size={13} className="mt-1 shrink-0 text-[var(--positive)]" />
                                        {suggestion}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

export const ResumeFeedback: React.FC<{ hasResume: boolean }> = ({ hasResume }) => {
    const [feedback, setFeedback] = useState<FeedbackResult | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [open, setOpen] = useState(false);

    const analyze = async () => {
        setLoading(true);
        setError('');
        try {
            const result = await getResumeFeedback();
            setFeedback(result);
            setOpen(true);
        } catch (e) {
            setError(getErrorMessage(e, 'Failed to analyze resume'));
        } finally {
            setLoading(false);
        }
    };

    if (!hasResume) return null;

    return (
        <div className="mt-3">
            {!open && (
                <Button variant="secondary" onClick={analyze} disabled={loading}>
                    {loading ? <LoaderCircle className="animate-spin" size={16} /> : <Search size={16} />}
                    {loading ? 'Analyzing resume' : 'Analyze resume'}
                </Button>
            )}

            {error && (
                <Notice tone="error" className="mt-3">
                    {error}
                </Notice>
            )}

            {feedback && open && (
                <div className="mt-3 overflow-hidden rounded-lg border border-[var(--line)] bg-white">
                    <div className="flex items-start justify-between gap-3 border-b border-[var(--line)] bg-[var(--page)] px-4 py-3">
                        <div>
                            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--accent)]">AI resume matching analysis</p>
                            <p className="mt-1 text-sm text-[var(--muted)]">Focused fixes to improve match quality and ATS readability.</p>
                        </div>
                        <IconButton label="Collapse resume analysis" variant="ghost" size="sm" onClick={() => setOpen(false)}>
                            <X size={17} />
                        </IconButton>
                    </div>

                    <div className="space-y-4 p-4">
                        <div className="flex items-center gap-4 rounded-lg border border-[var(--line)] bg-[var(--page)] p-3">
                            <ScoreRing score={feedback.overall_score} />
                            <div>
                                <div className="mb-2 flex items-center gap-2">
                                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Overall score</p>
                                    <StatusChip tone={scoreTone(feedback.overall_score)}>{feedback.overall_score}/100</StatusChip>
                                </div>
                                <p className="text-sm leading-6 text-[var(--ink)]">{feedback.overall_assessment}</p>
                            </div>
                        </div>

                        {feedback.quick_wins?.length > 0 && (
                            <section>
                                <h4 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--warning)]">
                                    <Sparkles size={14} />
                                    Quick wins
                                </h4>
                                <ul className="space-y-2">
                                    {feedback.quick_wins.map((win, i) => (
                                        <li key={`${win}-${i}`} className="flex items-start gap-2 rounded-lg border border-[var(--line)] bg-white px-3 py-2 text-sm leading-6 text-[var(--ink)]">
                                            <Check size={15} className="mt-1 shrink-0 text-[var(--positive)]" />
                                            {win}
                                        </li>
                                    ))}
                                </ul>
                            </section>
                        )}

                        {feedback.categories?.length > 0 && (
                            <section>
                                <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Category breakdown</h4>
                                <div className="space-y-2">
                                    {[...feedback.categories].sort((a, b) => a.score - b.score).map((cat, i) => (
                                        <CategoryBar key={`${cat.name}-${i}`} cat={cat} />
                                    ))}
                                </div>
                            </section>
                        )}

                        {feedback.missing_keywords?.length > 0 && (
                            <section>
                                <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--danger)]">Missing keywords</h4>
                                <div className="flex flex-wrap gap-2">
                                    {feedback.missing_keywords.map((kw, i) => (
                                        <StatusChip key={`${kw}-${i}`} tone="danger">
                                            {kw}
                                        </StatusChip>
                                    ))}
                                </div>
                            </section>
                        )}

                        <Button variant="ghost" size="sm" onClick={analyze} disabled={loading}>
                            {loading ? <LoaderCircle className="animate-spin" size={14} /> : <RefreshCw size={14} />}
                            {loading ? 'Re-analyzing' : 'Re-analyze'}
                        </Button>
                    </div>
                </div>
            )}
        </div>
    );
};
