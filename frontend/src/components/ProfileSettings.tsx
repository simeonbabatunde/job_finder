import { useEffect, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import { AlertCircle, CheckCircle2, LoaderCircle, Save } from 'lucide-react';
import { getAuthHeaders, API_URL, saveProfile } from '../api/client';
import type { ProfilePayload } from '../api/client';
import { Button, Panel, TextField } from './ui';
import { ApplicationAnswers } from './ApplicationAnswers';
import { SubmissionSettings } from './SubmissionSettings';

const EMPTY_PROFILE: ProfilePayload = {
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    location: '',
    linkedin_url: '',
    portfolio_url: '',
    github_url: '',
    years_experience: 0,
    expected_salary: '',
};

export const ProfileSettings = () => {
    const [profile, setProfile] = useState<ProfilePayload>(EMPTY_PROFILE);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [status, setStatus] = useState('');

    useEffect(() => {
        const fetchProfile = async () => {
            try {
                const response = await fetch(`${API_URL}/profile`, {
                    headers: getAuthHeaders()
                });
                if (response.ok) {
                    const data = await response.json();
                    if (data) setProfile({ ...EMPTY_PROFILE, ...data });
                }
            } catch (error) {
                console.error('Error fetching profile:', error);
            } finally {
                setLoading(false);
            }
        };
        void fetchProfile();
    }, []);

    const handleChange = (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
        const { name, value } = e.target;
        setProfile(prev => ({ ...prev, [name]: name === 'years_experience' ? parseInt(value) || 0 : value }));
    };

    const handleSubmit = async (e: FormEvent) => {
        e.preventDefault();
        setSaving(true);
        setStatus('');
        try {
            await saveProfile(profile);
            setStatus('Profile saved successfully.');
        } catch (error) {
            console.error('Error saving profile:', error);
            setStatus('Failed to save profile.');
        } finally {
            setSaving(false);
        }
    };

    if (loading) {
        return (
            <Panel className="p-6">
                <div className="flex items-center gap-2 text-sm font-semibold text-[var(--muted)]">
                    <LoaderCircle className="animate-spin" size={16} />
                    Loading profile
                </div>
            </Panel>
        );
    }

    return (
        <Panel className="p-5">
            <form onSubmit={handleSubmit} className="space-y-5">
                <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--accent)]">Profile settings</p>
                    <h3 className="mt-1 text-xl font-semibold text-[var(--ink)]">Personal profile details</h3>
                    <p className="mt-1 text-sm leading-6 text-[var(--muted)]">
                        These details help the assistant fill applications and personalize generated materials.
                    </p>
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <TextField label="First name" name="first_name" value={profile.first_name} onChange={handleChange} required placeholder="John" />
                    <TextField label="Last name" name="last_name" value={profile.last_name} onChange={handleChange} required placeholder="Doe" />
                    <TextField label="Email address" name="email" type="email" value={profile.email} onChange={handleChange} required placeholder="john.doe@example.com" />
                    <TextField label="Phone number" name="phone" type="tel" value={profile.phone} onChange={handleChange} required placeholder="+1 (555) 000-0000" />
                    <TextField label="Location" name="location" value={profile.location} onChange={handleChange} required placeholder="City, State" containerClassName="md:col-span-2" />
                    <TextField label="LinkedIn URL" name="linkedin_url" type="url" value={profile.linkedin_url || ''} onChange={handleChange} placeholder="https://linkedin.com/in/username" />
                    <TextField label="Portfolio URL" name="portfolio_url" type="url" value={profile.portfolio_url || ''} onChange={handleChange} placeholder="https://portfolio.com" />
                    <TextField label="GitHub URL" name="github_url" type="url" value={profile.github_url || ''} onChange={handleChange} placeholder="https://github.com/username" />
                    <TextField label="Expected salary" name="expected_salary" value={profile.expected_salary || ''} onChange={handleChange} placeholder="$120k-$150k / $85/hr" />
                    <div>
                        <label className="mb-1 block text-sm font-semibold text-[var(--ink)]">Years of experience</label>
                        <select
                            name="years_experience"
                            value={profile.years_experience}
                            onChange={handleChange}
                            className="min-h-10 w-full rounded-md border border-[var(--line)] bg-white px-3 text-sm text-[var(--ink)] outline-none transition-colors focus:border-[var(--accent)]"
                        >
                            {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 20].map(y => (
                                <option key={y} value={y}>
                                    {y === 0 ? 'Less than 1 year' : y === 20 ? '20+ years' : `${y} year${y > 1 ? 's' : ''}`}
                                </option>
                            ))}
                        </select>
                    </div>
                </div>

                <div className="flex flex-col gap-3 border-t border-[var(--line)] pt-4 sm:flex-row sm:items-center sm:justify-between">
                    {status && (
                        <p className={`flex items-center gap-2 text-sm font-semibold ${status.startsWith('Failed') ? 'text-[var(--danger)]' : 'text-[var(--positive)]'}`}>
                            {status.startsWith('Failed') ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
                            {status}
                        </p>
                    )}
                    <Button type="submit" disabled={saving} className="sm:ml-auto">
                        {saving ? <LoaderCircle className="animate-spin" size={16} /> : <Save size={16} />}
                        {saving ? 'Saving' : 'Save profile details'}
                    </Button>
                </div>
            </form>
            <div className="mt-5 border-t border-[var(--line)] pt-5">
                <ApplicationAnswers />
            </div>
            <div className="mt-5 border-t border-[var(--line)] pt-5">
                <SubmissionSettings />
            </div>
        </Panel>
    );
};
