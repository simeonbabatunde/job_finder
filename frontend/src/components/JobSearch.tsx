import { useState } from 'react';
import { ExternalLink, LoaderCircle, MapPin, Search, Sparkles } from 'lucide-react';
import { API_URL, getAuthHeaders, searchJobs } from '../api/client';
import { Button, EmptyState, Panel, ProgressBar, StatusChip } from './ui';

interface Job {
    id: string;
    title: string;
    company: string;
    location: string;
    description: string;
    salary?: string;
    url?: string;
    analysis?: {
        score: number;
        explanation: string;
        cover_letter: string;
    };
    analyzing?: boolean;
}

export function JobSearch() {
    const [query, setQuery] = useState('');
    const [location, setLocation] = useState('');
    const [jobs, setJobs] = useState<Job[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [searched, setSearched] = useState(false);

    const handleSearch = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!query && !location) return;

        setLoading(true);
        setError('');
        setSearched(true);

        try {
            const results = await searchJobs(query, location);
            setJobs(results);
        } catch (err) {
            setError('Failed to fetch jobs. Please try again.');
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const handleAnalyze = async (jobId: string) => {
        const job = jobs.find(j => j.id === jobId);
        if (!job) return;

        setJobs(prev => prev.map(j => j.id === jobId ? { ...j, analyzing: true } : j));

        try {
            const response = await fetch(`${API_URL}/agent/analyze-single`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...getAuthHeaders()
                },
                body: JSON.stringify(job)
            });
            const analysis = await response.json();
            setJobs(prev => prev.map(j => j.id === jobId ? { ...j, analysis, analyzing: false } : j));
        } catch (err) {
            console.error('Analysis failed', err);
            setJobs(prev => prev.map(j => j.id === jobId ? { ...j, analyzing: false } : j));
        }
    };

    return (
        <div className="w-full">
            <form onSubmit={handleSearch} className="mb-5">
                <Panel className="p-3">
                    <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(220px,0.7fr)_auto]">
                        <input
                            type="text"
                            placeholder="Job title, keywords, or company"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            className="min-h-11 rounded-md border border-[var(--line)] bg-white px-3 text-sm outline-none transition-colors focus:border-[var(--accent)]"
                        />
                        <input
                            type="text"
                            placeholder="Location, e.g. New York or Remote"
                            value={location}
                            onChange={(e) => setLocation(e.target.value)}
                            className="min-h-11 rounded-md border border-[var(--line)] bg-white px-3 text-sm outline-none transition-colors focus:border-[var(--accent)]"
                        />
                        <Button type="submit" disabled={loading} className="md:min-w-36">
                            {loading ? <LoaderCircle className="animate-spin" size={16} /> : <Search size={16} />}
                            {loading ? 'Searching' : 'Search'}
                        </Button>
                    </div>
                </Panel>
            </form>

            {error && (
                <div className="mb-5 rounded-lg border border-[var(--danger-soft)] bg-[var(--danger-soft)] p-3 text-sm font-semibold text-[var(--danger)]">
                    {error}
                </div>
            )}

            <div className="space-y-4">
                {jobs.length > 0 ? (
                    jobs.map((job) => (
                        <Panel key={job.id} className="p-5">
                            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                                <div className="min-w-0">
                                    <h3 className="text-lg font-semibold text-[var(--ink)]">{job.title}</h3>
                                    <p className="mt-1 text-sm font-semibold text-[var(--muted)]">{job.company}</p>
                                    <p className="mt-2 flex items-center gap-1.5 text-sm text-[var(--muted)]">
                                        <MapPin size={15} />
                                        {job.location}
                                    </p>
                                </div>
                                {job.salary && <StatusChip tone="success">{job.salary}</StatusChip>}
                            </div>

                            <p className="mt-4 line-clamp-3 text-sm leading-6 text-[var(--muted)]">{job.description}</p>

                            <div className="mt-5 flex flex-wrap items-center gap-2">
                                {job.url && (
                                    <a
                                        href={job.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="inline-flex min-h-10 items-center gap-2 rounded-md border border-[var(--line)] bg-white px-4 text-sm font-semibold text-[var(--ink)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
                                    >
                                        <ExternalLink size={16} />
                                        Open job
                                    </a>
                                )}
                                <Button
                                    variant="secondary"
                                    onClick={() => handleAnalyze(job.id)}
                                    disabled={job.analyzing}
                                >
                                    {job.analyzing ? <LoaderCircle className="animate-spin" size={16} /> : <Sparkles size={16} />}
                                    {job.analyzing ? 'Analyzing' : job.analysis ? 'Re-analyze fit' : 'Analyze fit'}
                                </Button>
                            </div>

                            {job.analysis && (
                                <div className="mt-5 border-t border-[var(--line)] pt-5">
                                    <div className="mb-3 flex items-center gap-3">
                                        <StatusChip tone={job.analysis.score >= 0.75 ? 'success' : job.analysis.score >= 0.5 ? 'accent' : 'warning'}>
                                            {(job.analysis.score * 100).toFixed(0)}% fit
                                        </StatusChip>
                                        <div className="min-w-0 flex-1">
                                            <ProgressBar value={job.analysis.score * 100} />
                                        </div>
                                    </div>
                                    <div className="rounded-lg border border-[var(--line)] bg-[var(--page)] p-4">
                                        <h4 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--accent)]">
                                            <Sparkles size={14} />
                                            AI fit analysis
                                        </h4>
                                        <p className="text-sm leading-6 text-[var(--ink)]">{job.analysis.explanation}</p>
                                    </div>
                                </div>
                            )}
                        </Panel>
                    ))
                ) : (
                    searched && !loading && (
                        <EmptyState
                            title="No jobs found"
                            detail="Try adjusting your search keywords or location."
                        />
                    )
                )}
            </div>
        </div>
    );
}
