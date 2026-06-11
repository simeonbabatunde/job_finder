import { useState, forwardRef, useImperativeHandle, useEffect } from 'react';
import type { ChangeEvent } from 'react';
import { ChevronDown } from 'lucide-react';
import type { JobPreferencesPayload } from '../api/client';
import { savePreferences } from '../api/client';
import { cn } from '../lib/cn';
import { Notice, ProgressBar } from './ui';

export interface JobPreferencesHandle {
    submitPrefs: (silent?: boolean) => Promise<boolean>;
}

export interface JobPreferencesProps {
    initialData?: Partial<JobPreferencesPayload> | null;
}

const fieldClass = 'min-h-10 w-full rounded-md border border-[var(--line)] bg-white px-3 text-sm text-[var(--ink)] outline-none transition-colors placeholder:text-slate-400 focus:border-[var(--accent)]';
const labelClass = 'mb-1 block text-sm font-semibold text-[var(--ink)]';
const hintClass = 'mt-1 text-xs text-[var(--muted)]';

export const JobPreferences = forwardRef<JobPreferencesHandle, JobPreferencesProps>((props, ref) => {
    const [formData, setFormData] = useState({
        role: props.initialData?.role?.join(', ') || '',
        experience_level: props.initialData?.experience_level || ['Intermediate'],
        location: props.initialData?.location?.join(', ') || '',
        job_type: props.initialData?.job_type || ['Full-time'],
        target_companies: props.initialData?.target_companies?.join(', ') || '',
        min_match_score: props.initialData?.min_match_score || 70,
        posted_within_days: props.initialData?.posted_within_days || 7,
    });
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState('');
    const [openDropdown, setOpenDropdown] = useState<'experience_level' | 'job_type' | null>(null);

    useEffect(() => {
        if (props.initialData) {
            setFormData({
                role: props.initialData.role?.join(', ') || '',
                experience_level: props.initialData.experience_level || ['Intermediate'],
                location: props.initialData.location?.join(', ') || '',
                job_type: props.initialData.job_type || ['Full-time'],
                target_companies: props.initialData.target_companies?.join(', ') || '',
                min_match_score: props.initialData.min_match_score || 70,
                posted_within_days: props.initialData.posted_within_days || 7,
            });
        }
    }, [props.initialData]);

    useImperativeHandle(ref, () => ({
        submitPrefs: async (silent: boolean = false) => {
            setSaving(true);
            setMessage('');
            try {
                const payload = {
                    ...formData,
                    role: formData.role.split(',').map((s: string) => s.trim()).filter((s: string) => s !== ''),
                    location: formData.location.split(',').map((s: string) => s.trim()).filter((s: string) => s !== ''),
                    target_companies: formData.target_companies.split(',').map((s: string) => s.trim()).filter((s: string) => s !== ''),
                };
                await savePreferences(payload);
                if (!silent) {
                    setMessage('Preferences saved successfully.');
                }
                return true;
            } catch (error) {
                setMessage('Error saving preferences.');
                console.error(error);
                return false;
            } finally {
                setSaving(false);
            }
        }
    }));

    const handleChange = (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
        const { name, value } = e.target;
        setFormData(prev => {
            if (name === 'min_match_score' || name === 'posted_within_days') {
                return { ...prev, [name]: parseInt(value) || 0 };
            }
            return { ...prev, [name]: value };
        });
    };

    const handleCheckboxChange = (name: 'job_type' | 'experience_level', value: string) => {
        setFormData(prev => {
            const currentArray = prev[name] as string[];
            const newArray = currentArray.includes(value)
                ? currentArray.filter(item => item !== value)
                : [...currentArray, value];
            return {
                ...prev,
                [name]: newArray
            };
        });
    };

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as HTMLElement;
            if (!target.closest('[data-preferences-dropdown]')) {
                setOpenDropdown(null);
            }
        };

        if (openDropdown) {
            document.addEventListener('mousedown', handleClickOutside);
        }

        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [openDropdown]);

    const dropdownButtonClass = 'flex min-h-10 w-full cursor-pointer items-center justify-between rounded-md border border-[var(--line)] bg-white px-3 text-sm text-[var(--ink)] transition-colors hover:border-[var(--accent)]';
    const dropdownMenuClass = 'absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-[var(--line)] bg-white py-1 shadow-lg';

    return (
        <div className="w-full">
            <div className="space-y-3">
                <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                    <div>
                        <label className={labelClass}>Target role</label>
                        <input
                            type="text"
                            name="role"
                            value={formData.role}
                            onChange={handleChange}
                            className={fieldClass}
                            required
                            placeholder="Software Engineer, Data Scientist"
                        />
                        <p className={hintClass}>Separate multiple roles with commas.</p>
                    </div>

                    <div className="relative" data-preferences-dropdown>
                        <label className={labelClass}>Experience level</label>
                        <button
                            type="button"
                            onClick={() => setOpenDropdown(openDropdown === 'experience_level' ? null : 'experience_level')}
                            className={dropdownButtonClass}
                        >
                            <span>
                                {formData.experience_level.length > 0
                                    ? `${formData.experience_level.length} selected`
                                    : 'Select levels'}
                            </span>
                            <ChevronDown size={16} />
                        </button>
                        {openDropdown === 'experience_level' && (
                            <div className={dropdownMenuClass}>
                                {['Intern', 'Entry-level', 'Intermediate', 'Senior', 'Staff', 'Principal', 'Manager', 'Director', 'Executive'].map(level => (
                                    <label key={level} className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm text-[var(--ink)] hover:bg-[var(--soft)]">
                                        <input
                                            type="checkbox"
                                            checked={formData.experience_level.includes(level)}
                                            onChange={() => handleCheckboxChange('experience_level', level)}
                                            className="h-4 w-4 rounded border-[var(--line)] accent-[var(--accent)]"
                                        />
                                        <span>{level}</span>
                                    </label>
                                ))}
                            </div>
                        )}
                    </div>

                    <div>
                        <label className={labelClass}>Location</label>
                        <input
                            type="text"
                            name="location"
                            value={formData.location}
                            onChange={handleChange}
                            className={fieldClass}
                            required
                            placeholder="Remote, NYC, San Francisco"
                        />
                        <p className={hintClass}>Separate multiple locations with commas.</p>
                    </div>

                    <div className="md:col-span-3">
                        <label className={labelClass}>Target companies</label>
                        <input
                            type="text"
                            name="target_companies"
                            value={formData.target_companies}
                            onChange={handleChange}
                            className={cn(fieldClass, 'border-[var(--accent-soft)] bg-[var(--accent-soft)]/40')}
                            placeholder="Stripe, Airbnb, Notion, Figma"
                        />
                        <p className="mt-1 text-xs text-[var(--accent)]">Direct career-page checks for companies you care about most.</p>
                    </div>
                </div>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                    <div className="relative" data-preferences-dropdown>
                        <label className={labelClass}>Job type</label>
                        <button
                            type="button"
                            onClick={() => setOpenDropdown(openDropdown === 'job_type' ? null : 'job_type')}
                            className={dropdownButtonClass}
                        >
                            <span>
                                {formData.job_type.length > 0
                                    ? `${formData.job_type.length} selected`
                                    : 'Select job types'}
                            </span>
                            <ChevronDown size={16} />
                        </button>
                        {openDropdown === 'job_type' && (
                            <div className={dropdownMenuClass}>
                                {['Full-time', 'Contract', 'Part-time'].map(type => (
                                    <label key={type} className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm text-[var(--ink)] hover:bg-[var(--soft)]">
                                        <input
                                            type="checkbox"
                                            checked={formData.job_type.includes(type)}
                                            onChange={() => handleCheckboxChange('job_type', type)}
                                            className="h-4 w-4 rounded border-[var(--line)] accent-[var(--accent)]"
                                        />
                                        <span>{type}</span>
                                    </label>
                                ))}
                            </div>
                        )}
                    </div>

                    <div>
                        <label className={labelClass}>Minimum match score</label>
                        <input
                            type="number"
                            name="min_match_score"
                            min="0"
                            max="100"
                            value={formData.min_match_score}
                            onChange={handleChange}
                            className={fieldClass}
                            required
                        />
                    </div>

                    <div>
                        <label className={labelClass}>Posted within</label>
                        <div className="relative">
                            <select
                                name="posted_within_days"
                                value={formData.posted_within_days}
                                onChange={handleChange}
                                className={cn(fieldClass, 'appearance-none pr-9')}
                            >
                                <option value={1}>24 hours</option>
                                <option value={2}>48 hours</option>
                                <option value={7}>1 week</option>
                                <option value={14}>2 weeks</option>
                                <option value={30}>1 month</option>
                                <option value={90}>3 months</option>
                                <option value={180}>6 months</option>
                                <option value={365}>1 year</option>
                            </select>
                            <ChevronDown size={16} className="pointer-events-none absolute right-3 top-3 text-[var(--muted)]" />
                        </div>
                    </div>
                </div>

                {saving && <ProgressBar value={100} className="animate-pulse" />}

                {message && (
                    <Notice tone={message.includes('Error') ? 'error' : 'success'}>
                        {message}
                    </Notice>
                )}
            </div>
        </div>
    );
});
