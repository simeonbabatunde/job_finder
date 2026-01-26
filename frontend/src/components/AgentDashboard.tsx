import React, { useEffect, useState } from 'react';
import { getAuthHeaders } from '../api/client';

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

export const AgentDashboard: React.FC = () => {
    const [applications, setApplications] = useState<Application[]>([]);
    const [loading, setLoading] = useState(true);
    const [viewAll, setViewAll] = useState(false);
    const [expandedId, setExpandedId] = useState<number | null>(null);

    const fetchApplications = async () => {
        try {
            const response = await fetch('http://localhost:8000/applications', {
                headers: getAuthHeaders()
            });
            const data = await response.json();
            // Sort by date desc
            const sorted = data.sort((a: any, b: any) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
            setApplications(sorted);
        } catch (error) {
            console.error('Error fetching applications:', error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchApplications();
    }, []);

    const copyToClipboard = (text: string) => {
        navigator.clipboard.writeText(text);
        alert('Cover letter copied to clipboard!');
    };

    const displayedApps = viewAll ? applications : applications.slice(0, 5);

    return (
        <div className="mt-6">
            <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-medium text-slate-800 flex items-center">
                    <span className="mr-2">📋</span> Application History
                </h3>
                {applications.length > 5 && (
                    <button
                        onClick={() => setViewAll(!viewAll)}
                        className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 uppercase tracking-wider"
                    >
                        {viewAll ? 'Show Less' : `View All (${applications.length})`}
                    </button>
                )}
            </div>

            {loading ? (
                <div className="flex justify-center py-8">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
                </div>
            ) : applications.length === 0 ? (
                <div className="bg-slate-50 border border-dashed border-slate-200 rounded-xl p-8 text-center text-slate-500">
                    No applications submitted yet. Run the agent to get started!
                </div>
            ) : (
                <div className="overflow-hidden border border-slate-200 rounded-xl shadow-sm bg-white">
                    <table className="min-w-full divide-y divide-slate-200">
                        <thead className="bg-slate-50">
                            <tr>
                                <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Job</th>
                                <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Status</th>
                                <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Score</th>
                                <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-slate-200">
                            {displayedApps.map((app) => (
                                <React.Fragment key={app.id}>
                                    <tr className="hover:bg-slate-50 transition-colors">
                                        <td className="px-6 py-4">
                                            <div className="text-sm font-medium text-slate-900">{app.job_title}</div>
                                            <div className="text-sm text-slate-500">{app.company}</div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full 
                                                ${app.status === 'Applied' ? 'bg-green-100 text-green-800' : 'bg-amber-100 text-amber-800'}`}>
                                                {app.status}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <div className="flex items-center">
                                                <div className="text-sm text-slate-900 font-semibold">{(app.fit_score * 100).toFixed(0)}%</div>
                                                <div className="ml-2 w-12 bg-slate-100 rounded-full h-1.5 overflow-hidden hidden sm:block">
                                                    <div
                                                        className={`h-full rounded-full ${app.fit_score > 0.8 ? 'bg-emerald-500' : app.fit_score > 0.6 ? 'bg-indigo-500' : 'bg-amber-500'}`}
                                                        style={{ width: `${app.fit_score * 100}%` }}
                                                    ></div>
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                                            <div className="flex space-x-3">
                                                <a
                                                    href={app.job_url}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className="text-indigo-600 hover:text-indigo-900"
                                                >
                                                    Apply
                                                </a>
                                                {app.cover_letter && (
                                                    <button
                                                        onClick={() => setExpandedId(expandedId === app.id ? null : app.id)}
                                                        className="text-slate-600 hover:text-slate-900"
                                                    >
                                                        {expandedId === app.id ? 'Hide Letter' : 'View Letter'}
                                                    </button>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                    {expandedId === app.id && app.cover_letter && (
                                        <tr>
                                            <td colSpan={4} className="px-6 py-4 bg-slate-50">
                                                <div className="space-y-4">
                                                    {app.explanation && (
                                                        <div className="bg-indigo-50/50 border border-indigo-100 rounded-lg p-6 shadow-sm">
                                                            <h4 className="text-xs font-bold text-indigo-400 uppercase tracking-widest mb-3 flex items-center">
                                                                <span className="mr-2">🧠</span> AI Fit Analysis
                                                            </h4>
                                                            <p className="text-sm text-slate-700 leading-relaxed font-medium">
                                                                {app.explanation}
                                                            </p>
                                                        </div>
                                                    )}

                                                    {app.cover_letter && (
                                                        <div className="bg-white border border-slate-200 rounded-lg p-6 shadow-sm overflow-hidden relative">
                                                            <div className="flex justify-between items-center mb-4">
                                                                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest flex items-center">
                                                                    <span className="mr-2">✍️</span> Tailored Cover Letter
                                                                </h4>
                                                                <button
                                                                    onClick={() => copyToClipboard(app.cover_letter!)}
                                                                    className="text-xs font-medium text-indigo-600 hover:text-indigo-800 flex items-center"
                                                                >
                                                                    <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
                                                                    </svg>
                                                                    Copy
                                                                </button>
                                                            </div>
                                                            <div className="text-sm text-slate-700 whitespace-pre-wrap leading-relaxed font-serif">
                                                                {app.cover_letter}
                                                            </div>
                                                        </div>
                                                    )}
                                                </div>
                                            </td>
                                        </tr>
                                    )}
                                </React.Fragment>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            <button
                onClick={fetchApplications}
                className="mt-4 text-xs text-slate-400 hover:text-slate-600 font-medium transition-colors"
            >
                Refresh List
            </button>
        </div>
    );
};
