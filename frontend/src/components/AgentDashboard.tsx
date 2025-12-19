import React, { useEffect, useState } from 'react';

interface Application {
    id: number;
    job_title: string;
    company: string;
    status: string;
    fit_score: number;
    created_at: string;
    job_url: string;
}

export const AgentDashboard: React.FC = () => {
    const [applications, setApplications] = useState<Application[]>([]);
    const [loading, setLoading] = useState(true);
    const [viewAll, setViewAll] = useState(false);

    const fetchApplications = async () => {
        try {
            const response = await fetch('http://localhost:8000/applications');
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
                <div className="overflow-hidden border border-slate-200 rounded-xl shadow-sm">
                    <table className="min-w-full divide-y divide-slate-200">
                        <thead className="bg-slate-50">
                            <tr>
                                <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Job</th>
                                <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Status</th>
                                <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Score</th>
                                <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Date</th>
                            </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-slate-200">
                            {displayedApps.map((app) => (
                                <tr key={app.id} className="hover:bg-slate-50 transition-colors">
                                    <td className="px-6 py-4 whitespace-nowrap">
                                        <div className="text-sm font-medium text-slate-900">{app.job_title}</div>
                                        <div className="text-sm text-slate-500">{app.company}</div>
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap">
                                        <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full 
                                            ${app.status === 'Applied' ? 'bg-green-100 text-green-800' : 'bg-amber-100 text-amber-800'}`}>
                                            {app.status}
                                        </span>
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-500">
                                        {(app.fit_score * 100).toFixed(0)}%
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-500">
                                        {new Date(app.created_at).toLocaleDateString()}
                                    </td>
                                </tr>
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
