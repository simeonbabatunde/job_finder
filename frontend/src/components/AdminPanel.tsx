import React, { useEffect, useState } from 'react';
import { getAuthHeaders, API_URL } from '../api/client';

export const AdminPanel: React.FC = () => {
    const [config, setConfig] = useState({
        site_names: [] as string[],
        results_wanted: 10,
        country_indeed: 'USA'
    });
    const [msg, setMsg] = useState('');
    const [availableSites, setAvailableSites] = useState(['linkedin', 'indeed', 'glassdoor', 'zip_recruiter']);
    const [newSite, setNewSite] = useState('');

    useEffect(() => {
        fetch(`${API_URL}/admin/config`, { headers: getAuthHeaders() })
            .then(res => res.json())
            .then(data => {
                if (data.site_names) {
                    setConfig({
                        site_names: data.site_names,
                        results_wanted: data.results_wanted || 20,
                        country_indeed: data.country_indeed || 'USA'
                    });
                    // Add any custom sites from DB to available list
                    const defaults = ['linkedin', 'indeed', 'glassdoor', 'zip_recruiter'];
                    const custom = data.site_names.filter((s: string) => !defaults.includes(s));
                    if (custom.length > 0) {
                        setAvailableSites(prev => [...new Set([...prev, ...custom])]);
                    }
                }
            })
            .catch(_err => setMsg('Error loading config'));
    }, []);

    const handleSave = () => {
        fetch(`${API_URL}/admin/config`, {
            method: 'PUT',
            headers: {
                ...getAuthHeaders(),
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(config)
        })
            .then(res => {
                if (res.ok) setMsg('Configuration saved successfully!');
                else setMsg('Error saving configuration.');
            })
            .catch(() => setMsg('Network error.'));
    };

    const toggleSite = (site: string) => {
        setConfig(prev => {
            const sites = prev.site_names.includes(site)
                ? prev.site_names.filter(s => s !== site)
                : [...prev.site_names, site];
            return { ...prev, site_names: sites };
        });
    };

    const handleAddSite = () => {
        if (newSite && !availableSites.includes(newSite.toLowerCase())) {
            const s = newSite.toLowerCase().trim();
            setAvailableSites([...availableSites, s]);
            // Auto-select it
            toggleSite(s);
            setNewSite('');
        }
    };

    return (
        <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
            <div className="max-w-xl w-full bg-white rounded-2xl shadow-xl p-8 border border-slate-200">
                <div className="flex items-center justify-between mb-8">
                    <h1 className="text-2xl font-black text-slate-900 tracking-tight">Admin Settings</h1>
                    <span className="bg-indigo-100 text-indigo-700 text-xs font-bold px-2 py-1 rounded-full uppercase">Super User</span>
                </div>

                <div className="space-y-6">
                    <div>
                        <label className="block text-sm font-bold text-slate-700 mb-3">Job Boards to Scrape</label>

                        {/* Compact List (2 Columns) */}
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-px bg-slate-200 border border-slate-200 rounded-xl overflow-hidden mb-4">
                            {availableSites.map(site => {
                                const isSelected = config.site_names.includes(site);
                                return (
                                    <div key={site} className={`flex items-center justify-between p-3 hover:bg-white transition-colors ${isSelected ? 'bg-indigo-50' : 'bg-slate-50'}`}>
                                        <label className="flex items-center gap-3 cursor-pointer flex-1">
                                            <div className={`w-5 h-5 rounded border flex items-center justify-center transition-colors ${isSelected ? 'bg-indigo-600 border-indigo-600' : 'bg-white border-slate-300'}`}>
                                                {isSelected && (
                                                    <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" /></svg>
                                                )}
                                            </div>
                                            <input
                                                type="checkbox"
                                                checked={isSelected}
                                                onChange={() => toggleSite(site)}
                                                className="hidden"
                                            />
                                            <span className={`font-medium text-sm ${isSelected ? 'text-indigo-900' : 'text-slate-600'}`}>
                                                {site.charAt(0).toUpperCase() + site.slice(1).replace('_', ' ')}
                                            </span>
                                        </label>

                                        <button
                                            onClick={() => {
                                                setAvailableSites(prev => prev.filter(s => s !== site));
                                                // Also deselect if selected
                                                if (isSelected) toggleSite(site);
                                            }}
                                            className="text-slate-400 hover:text-red-500 p-1 rounded-md hover:bg-red-50 transition-colors"
                                            title="Remove board"
                                        >
                                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                                        </button>
                                    </div>
                                );
                            })}
                            {availableSites.length === 0 && (
                                <div className="p-4 text-center text-sm text-slate-400 italic col-span-2 bg-slate-50">No job boards added.</div>
                            )}
                        </div>

                        {/* Add Custom Site */}
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={newSite}
                                onChange={e => setNewSite(e.target.value)}
                                placeholder="Add job board (e.g. google)"
                                className="flex-1 px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 outline-none"
                                onKeyDown={e => e.key === 'Enter' && handleAddSite()}
                            />
                            <button
                                onClick={handleAddSite}
                                className="bg-slate-800 hover:bg-slate-900 text-white px-4 py-2 rounded-lg text-sm font-bold transition-all"
                            >
                                Add Board
                            </button>
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-bold text-slate-700 mb-2">Max Results Per Search</label>
                        <input
                            type="number"
                            value={config.results_wanted}
                            onChange={e => setConfig({ ...config, results_wanted: parseInt(e.target.value) })}
                            className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500 font-medium"
                        />
                        <p className="text-xs text-slate-400 mt-1">Higher numbers will take longer to process.</p>
                    </div>

                    <div>
                        <label className="block text-sm font-bold text-slate-700 mb-2">Indeed Country Code</label>
                        <input
                            type="text"
                            value={config.country_indeed}
                            onChange={e => setConfig({ ...config, country_indeed: e.target.value })}
                            className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500 font-medium uppercase"
                            placeholder="USA"
                        />
                    </div>

                    <button
                        onClick={handleSave}
                        className="w-full bg-slate-900 hover:bg-slate-800 text-white font-bold py-4 rounded-xl transition-all shadow-lg mt-4 active:scale-95"
                    >
                        Save Configuration
                    </button>

                    {msg && (
                        <div className={`text-center text-sm font-bold p-3 rounded-lg ${msg.includes('Error') ? 'bg-red-50 text-red-600' : 'bg-emerald-50 text-emerald-600'}`}>
                            {msg}
                        </div>
                    )}
                </div>

                <a href="/" className="block mt-8 text-center text-sm font-bold text-slate-400 hover:text-slate-600 transition-colors">
                    ← Back to Dashboard
                </a>
            </div>
        </div>
    );
};
