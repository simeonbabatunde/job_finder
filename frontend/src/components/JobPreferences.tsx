import { useState, forwardRef, useImperativeHandle, useEffect } from 'react';
import type { ChangeEvent, ClipboardEvent, KeyboardEvent } from 'react';
import { ChevronDown, Plus, X } from 'lucide-react';
import type { JobPreferencesPayload } from '../api/client';
import { savePreferences } from '../api/client';
import { cn } from '../lib/cn';
import { Notice, ProgressBar } from './ui';

export interface JobPreferencesHandle {
    submitPrefs: (silent?: boolean) => Promise<boolean>;
}

export interface JobPreferencesProps {
    initialData?: Partial<JobPreferencesPayload> | null;
    matchingProfileId?: number | null;
}

const fieldClass = 'min-h-10 w-full rounded-md border border-[var(--line)] bg-white px-3 text-sm text-[var(--ink)] outline-none transition-colors placeholder:text-slate-400 focus:border-[var(--accent)]';
const labelClass = 'mb-1 block text-sm font-semibold text-[var(--ink)]';
const hintClass = 'mt-1 text-xs text-[var(--muted)]';

const parseListInput = (value: string): string[] => {
    return value
        .split(/[,;\n]+/)
        .map(item => item.replace(/\s+/g, ' ').trim())
        .filter(Boolean);
};

const mergeUniqueList = (...lists: Array<string[] | undefined>): string[] => {
    const seen = new Set<string>();
    const merged: string[] = [];

    lists.flatMap(list => list || []).forEach(item => {
        const clean = item.replace(/\s+/g, ' ').trim();
        const key = clean.toLowerCase();
        if (!clean || seen.has(key)) return;
        seen.add(key);
        merged.push(clean);
    });

    return merged;
};

const listFromInitialData = (items?: string[]) => mergeUniqueList(items);

const formStateFromInitialData = (initialData?: Partial<JobPreferencesPayload> | null) => ({
    role: listFromInitialData(initialData?.role),
    experience_level: initialData?.experience_level?.length ? initialData.experience_level : ['Intermediate'],
    location: initialData?.location?.join(', ') || '',
    job_type: initialData?.job_type?.length ? initialData.job_type : ['Full-time'],
    target_companies: initialData?.target_companies?.join(', ') || '',
    min_match_score: initialData?.min_match_score ?? 70,
    posted_within_days: initialData?.posted_within_days ?? 7,
});

export const JobPreferences = forwardRef<JobPreferencesHandle, JobPreferencesProps>((props, ref) => {
    const [formData, setFormData] = useState(() => formStateFromInitialData(props.initialData));
    const [roleDraft, setRoleDraft] = useState('');
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState('');
    const [openDropdown, setOpenDropdown] = useState<'experience_level' | 'job_type' | null>(null);

    useEffect(() => {
        setFormData(formStateFromInitialData(props.initialData));
        setRoleDraft('');
        setMessage('');
    }, [props.initialData]);

    const commitRoleDraft = (rawValue = roleDraft) => {
        const roles = parseListInput(rawValue);
        if (!roles.length) return;
        setFormData(prev => ({ ...prev, role: mergeUniqueList(prev.role, roles) }));
        setRoleDraft('');
    };

    const removeRole = (role: string) => {
        setFormData(prev => ({
            ...prev,
            role: prev.role.filter(item => item.toLowerCase() !== role.toLowerCase()),
        }));
    };

    useImperativeHandle(ref, () => ({
        submitPrefs: async (silent: boolean = false) => {
            setSaving(true);
            setMessage('');
            try {
                const submittedRoles = mergeUniqueList(formData.role, parseListInput(roleDraft));
                const payload = {
                    ...formData,
                    role: submittedRoles,
                    location: formData.location.split(',').map((s: string) => s.trim()).filter((s: string) => s !== ''),
                    target_companies: formData.target_companies.split(',').map((s: string) => s.trim()).filter((s: string) => s !== ''),
                };
                await savePreferences(payload, props.matchingProfileId);
                setFormData(prev => ({ ...prev, role: submittedRoles }));
                setRoleDraft('');
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

    const handleRoleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
        if (event.key === 'Enter' || event.key === ',' || event.key === ';') {
            event.preventDefault();
            commitRoleDraft();
            return;
        }

        if (event.key === 'Backspace' && !roleDraft && formData.role.length > 0) {
            removeRole(formData.role[formData.role.length - 1]);
        }
    };

    const handleRolePaste = (event: ClipboardEvent<HTMLInputElement>) => {
        const pasted = event.clipboardData.getData('text');
        if (!/[,;\n]/.test(pasted)) return;
        event.preventDefault();
        commitRoleDraft(`${roleDraft}${roleDraft ? ', ' : ''}${pasted}`);
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
                        <label className={labelClass}>Target roles</label>
                        <div className="flex min-h-10 w-full flex-wrap items-center gap-1.5 rounded-md border border-[var(--line)] bg-white px-2 py-1.5 text-sm text-[var(--ink)] transition-colors focus-within:border-[var(--accent)]">
                            {formData.role.map(role => (
                                <span key={role} className="inline-flex h-7 max-w-full items-center gap-1 rounded-md border border-[var(--line)] bg-[var(--soft)] px-2 text-xs font-medium text-[var(--ink)]">
                                    <span className="truncate">{role}</span>
                                    <button
                                        type="button"
                                        onClick={() => removeRole(role)}
                                        className="grid h-4 w-4 shrink-0 place-items-center rounded text-[var(--muted)] transition-colors hover:bg-white hover:text-[var(--ink)]"
                                        aria-label={`Remove ${role}`}
                                    >
                                        <X size={12} />
                                    </button>
                                </span>
                            ))}
                            <input
                                type="text"
                                value={roleDraft}
                                onChange={(event) => setRoleDraft(event.target.value)}
                                onKeyDown={handleRoleKeyDown}
                                onPaste={handleRolePaste}
                                onBlur={() => commitRoleDraft()}
                                className="min-h-7 min-w-[12rem] flex-1 bg-transparent px-1 text-sm text-[var(--ink)] outline-none placeholder:text-slate-400"
                                placeholder={formData.role.length ? 'Add another role' : 'Software Engineer'}
                            />
                            <button
                                type="button"
                                onMouseDown={(event) => event.preventDefault()}
                                onClick={() => commitRoleDraft()}
                                disabled={!roleDraft.trim()}
                                className="grid h-7 w-7 shrink-0 place-items-center rounded-md border border-[var(--line)] text-[var(--muted)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-40"
                                aria-label="Add target role"
                            >
                                <Plus size={15} />
                            </button>
                        </div>
                        <p className={hintClass}>Press Enter or comma after each role.</p>
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
