import { useState } from 'react';
import { searchJobs } from '../api/client';

interface Job {
    id: string;
    title: string;
    company: string;
    location: string;
    description: string;
    salary: string;
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
            const email = localStorage.getItem('user_email');
            const response = await fetch('http://localhost:8000/agent/analyze-single', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-User-Email': email || ''
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
            <form onSubmit={handleSearch} className="mb-8">
                <div className="flex flex-col md:flex-row gap-4">
                    <div className="flex-1">
                        <input
                            type="text"
                            placeholder="Job Title, Keywords, or Company"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            className="w-full px-4 py-3 rounded-lg border border-gray-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                        />
                    </div>
                    <div className="flex-1">
                        <input
                            type="text"
                            placeholder="Location (e.g. New York, Remote)"
                            value={location}
                            onChange={(e) => setLocation(e.target.value)}
                            className="w-full px-4 py-3 rounded-lg border border-gray-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                        />
                    </div>
                    <button
                        type="submit"
                        disabled={loading}
                        className="px-8 py-3 bg-slate-900 text-white font-bold rounded-lg hover:bg-black focus:ring-4 focus:ring-slate-300 transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg"
                    >
                        {loading ? 'Searching...' : 'Search Jobs'}
                    </button>
                </div>
            </form>

            {error && (
                <div className="p-4 mb-6 bg-red-50 text-red-700 rounded-lg">
                    {error}
                </div>
            )}

            <div className="space-y-6">
                {jobs.length > 0 ? (
                    jobs.map((job) => (
                        <div key={job.id} className="p-8 bg-white border border-slate-100 rounded-2xl shadow-sm hover:shadow-xl hover:border-indigo-100 transition-all group">
                            <div className="flex justify-between items-start mb-4">
                                <div>
                                    <h3 className="text-xl font-bold text-slate-900 group-hover:text-indigo-600 transition-colors">{job.title}</h3>
                                    <p className="text-slate-600 font-semibold">{job.company}</p>
                                </div>
                                {job.salary && (
                                    <span className="bg-emerald-50 text-emerald-700 text-xs font-bold px-3 py-1 rounded-full border border-emerald-100">
                                        {job.salary}
                                    </span>
                                )}
                            </div>
                            <div className="flex items-center text-sm text-slate-400 mb-4 font-medium">
                                <svg className="w-4 h-4 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                                </svg>
                                {job.location}
                            </div>
                            <p className="text-slate-500 text-sm line-clamp-3 mb-6 leading-relaxed">{job.description}</p>

                            <div className="flex flex-wrap items-center gap-4">
                                {job.url && (
                                    <a
                                        href={job.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="text-white bg-indigo-600 px-6 py-2 rounded-xl text-sm font-bold hover:bg-indigo-700 transition-all shadow-md shadow-indigo-100"
                                    >
                                        Apply on Site
                                    </a>
                                )}
                                <button
                                    onClick={() => handleAnalyze(job.id)}
                                    disabled={job.analyzing}
                                    className="text-indigo-600 border border-indigo-200 px-6 py-2 rounded-xl text-sm font-bold hover:bg-indigo-50 transition-all"
                                >
                                    {job.analyzing ? 'Analyzing...' : job.analysis ? 'Re-Analyze Fit' : 'Analyze Fit with AI'}
                                </button>
                            </div>

                            {job.analysis && (
                                <div className="mt-8 pt-8 border-t border-slate-50 animate-in fade-in slide-in-from-top-4 duration-500">
                                    <div className="flex items-center mb-4">
                                        <div className="text-2xl font-black text-indigo-600 mr-4">
                                            {(job.analysis.score * 100).toFixed(0)}%
                                        </div>
                                        <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                                            <div
                                                className="h-full bg-indigo-500 rounded-full transition-all duration-1000"
                                                style={{ width: `${job.analysis.score * 100}%` }}
                                            ></div>
                                        </div>
                                    </div>
                                    <div className="bg-indigo-50/50 rounded-xl p-5 border border-indigo-100">
                                        <h4 className="text-xs font-bold text-indigo-400 uppercase tracking-widest mb-2 flex items-center">
                                            <span className="mr-2">🧠</span> AI Fit Analysis
                                        </h4>
                                        <p className="text-sm text-slate-700 leading-relaxed">
                                            {job.analysis.explanation}
                                        </p>
                                    </div>
                                </div>
                            )}
                        </div>
                    ))
                ) : (
                    searched && !loading && (
                        <div className="text-center py-20 bg-slate-50 rounded-3xl border border-dashed border-slate-200">
                            <div className="text-4xl mb-4">🔍</div>
                            <h3 className="text-lg font-bold text-slate-800">No jobs found</h3>
                            <p className="text-slate-500">Try adjusting your search keywords or location.</p>
                        </div>
                    )
                )}
            </div>
        </div>
    );
}
