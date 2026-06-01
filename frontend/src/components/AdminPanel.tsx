import React, { useEffect, useState } from 'react';
import { ArrowLeft, Plus, Save, Settings, Trash2 } from 'lucide-react';
import { getAuthHeaders, API_URL } from '../api/client';
import { cn } from '../lib/cn';
import { Button, PageShell, Panel, SectionHeader, StatusChip, TextField } from './ui';

export const AdminPanel: React.FC = () => {
    const [config, setConfig] = useState({
        site_names: [] as string[],
        results_wanted: 10,
        country_indeed: 'USA'
    });
    const [msg, setMsg] = useState('');
    const [availableSites, setAvailableSites] = useState(['linkedin', 'indeed', 'glassdoor', 'zip_recruiter', 'motion_recruitment']);
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
                    const defaults = ['linkedin', 'indeed', 'glassdoor', 'zip_recruiter', 'motion_recruitment'];
                    const custom = data.site_names.filter((s: string) => !defaults.includes(s));
                    if (custom.length > 0) {
                        setAvailableSites(prev => [...new Set([...prev, ...custom])]);
                    }
                }
            })
            .catch(() => setMsg('Error loading config'));
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
                if (res.ok) setMsg('Configuration saved successfully.');
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
        const site = newSite.toLowerCase().trim();
        if (site && !availableSites.includes(site)) {
            setAvailableSites([...availableSites, site]);
            setConfig(prev => ({ ...prev, site_names: [...prev.site_names, site] }));
            setNewSite('');
        }
    };

    return (
        <div className="min-h-screen bg-[var(--page)] text-[var(--ink)]">
            <header className="border-b border-[var(--line)] bg-white">
                <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4">
                    <a href="/" className="inline-flex items-center gap-2 text-sm font-semibold text-[var(--muted)] hover:text-[var(--accent)]">
                        <ArrowLeft size={16} />
                        Dashboard
                    </a>
                    <StatusChip tone="accent">Admin</StatusChip>
                </div>
            </header>

            <PageShell>
                <Panel className="p-5">
                    <SectionHeader
                        eyebrow="Configuration"
                        title="Scraper settings"
                        description="Choose job sources and result volume for agent searches."
                        action={<Settings size={21} className="text-[var(--accent)]" />}
                    />

                    <div className="mt-6 space-y-6">
                        <div>
                            <label className="mb-3 block text-sm font-semibold text-[var(--ink)]">Job boards to scrape</label>
                            <div className="grid overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--line)] sm:grid-cols-2">
                                {availableSites.map(site => {
                                    const isSelected = config.site_names.includes(site);
                                    return (
                                        <div key={site} className={cn('flex items-center justify-between gap-3 bg-white p-3', isSelected && 'bg-[var(--accent-soft)]/50')}>
                                            <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3">
                                                <input
                                                    type="checkbox"
                                                    checked={isSelected}
                                                    onChange={() => toggleSite(site)}
                                                    className="h-4 w-4 rounded border-[var(--line)] accent-[var(--accent)]"
                                                />
                                                <span className="truncate text-sm font-semibold text-[var(--ink)]">
                                                    {site.charAt(0).toUpperCase() + site.slice(1).replace('_', ' ')}
                                                </span>
                                            </label>

                                            <button
                                                type="button"
                                                onClick={() => {
                                                    setAvailableSites(prev => prev.filter(s => s !== site));
                                                    if (isSelected) toggleSite(site);
                                                }}
                                                className="rounded-md p-2 text-[var(--muted)] transition-colors hover:bg-[var(--danger-soft)] hover:text-[var(--danger)]"
                                                title="Remove board"
                                                aria-label={`Remove ${site}`}
                                            >
                                                <Trash2 size={15} />
                                            </button>
                                        </div>
                                    );
                                })}
                                {availableSites.length === 0 && (
                                    <div className="bg-white p-4 text-center text-sm text-[var(--muted)] sm:col-span-2">No job boards added.</div>
                                )}
                            </div>

                            <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                                <input
                                    type="text"
                                    value={newSite}
                                    onChange={e => setNewSite(e.target.value)}
                                    placeholder="Add job board, e.g. google"
                                    className="min-h-10 flex-1 rounded-md border border-[var(--line)] bg-white px-3 text-sm outline-none transition-colors focus:border-[var(--accent)]"
                                    onKeyDown={e => e.key === 'Enter' && handleAddSite()}
                                />
                                <Button onClick={handleAddSite} variant="secondary">
                                    <Plus size={16} />
                                    Add board
                                </Button>
                            </div>
                        </div>

                        <div className="grid gap-4 md:grid-cols-2">
                            <TextField
                                label="Max results per search"
                                type="number"
                                value={config.results_wanted}
                                onChange={e => setConfig({ ...config, results_wanted: parseInt(e.target.value) })}
                                name="results_wanted"
                                hint="Higher numbers will take longer to process."
                            />
                            <TextField
                                label="Indeed country code"
                                type="text"
                                value={config.country_indeed}
                                onChange={e => setConfig({ ...config, country_indeed: e.target.value })}
                                name="country_indeed"
                                placeholder="USA"
                            />
                        </div>

                        <div className="flex flex-col gap-3 border-t border-[var(--line)] pt-4 sm:flex-row sm:items-center sm:justify-between">
                            {msg && (
                                <div className={`rounded-lg border px-3 py-2 text-sm font-semibold ${msg.includes('Error') || msg.includes('Network') ? 'border-[var(--danger-soft)] bg-[var(--danger-soft)] text-[var(--danger)]' : 'border-[var(--positive-soft)] bg-[var(--positive-soft)] text-[var(--positive)]'}`}>
                                    {msg}
                                </div>
                            )}
                            <Button onClick={handleSave} className="sm:ml-auto">
                                <Save size={16} />
                                Save configuration
                            </Button>
                        </div>
                    </div>
                </Panel>
            </PageShell>
        </div>
    );
};
