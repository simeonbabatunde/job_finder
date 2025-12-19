import { useState } from 'react';
import { searchJobs } from '../api/client';

interface Job {
    id: string;
    title: string;
    company: string;
    location: string;
    description: string;
    salary: string;
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
                        className="px-8 py-3 bg-gray-700 text-white font-semibold rounded-lg hover:bg-gray-800 focus:ring-4 focus:ring-gray-300 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
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

            <div className="space-y-4">
                {jobs.length > 0 ? (
                    jobs.map((job) => (
                        <div key={job.id} className="p-6 bg-white border border-gray-100 rounded-xl shadow-sm hover:shadow-md transition-shadow">
                            <div className="flex justify-between items-start mb-2">
                                <div>
                                    <h3 className="text-lg font-bold text-gray-900">{job.title}</h3>
                                    <p className="text-gray-600 font-medium">{job.company}</p>
                                </div>
                                {job.salary && (
                                    <span className="bg-green-100 text-green-800 text-xs font-semibold px-2.5 py-0.5 rounded">
                                        {job.salary}
                                    </span>
                                )}
                            </div>
                            <div className="flex items-center text-sm text-gray-500 mb-3">
                                <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                                </svg>
                                {job.location}
                            </div>
                            <p className="text-gray-600 text-sm line-clamp-2">{job.description}</p>
                            <button className="mt-4 text-indigo-600 font-semibold text-sm hover:text-indigo-800">
                                View Details →
                            </button>
                        </div>
                    ))
                ) : (
                    searched && !loading && (
                        <div className="text-center py-12 text-gray-500">
                            No jobs found. Try adjusting your search criteria.
                        </div>
                    )
                )}
            </div>
        </div>
    );
}
