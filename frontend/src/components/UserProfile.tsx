import { useState, useEffect, forwardRef, useImperativeHandle } from 'react';
import type { ChangeEvent } from 'react';
import { AlertCircle, CheckCircle2, LoaderCircle, Save } from 'lucide-react';
import type { ProfilePayload } from '../api/client';
import { getErrorMessage, saveProfile } from '../api/client';
import { cn } from '../lib/cn';
import { Button, ProgressBar, StatusChip } from './ui';

export interface UserProfileHandle {
    save: (silent?: boolean) => Promise<boolean>;
}

export interface UserProfileProps {
    initialData?: Partial<ProfilePayload> | null;
    userEmail?: string;
}

interface FormData {
    first_name: string;
    last_name: string;
    email: string;
    phone: string;
    location: string;
    linkedin_url: string;
    portfolio_url: string;
    github_url: string;
    years_experience: number;
    expected_salary: string;
}

const EMPTY_FORM: FormData = {
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

function buildForm(data: Partial<ProfilePayload> | null | undefined, userEmail?: string): FormData {
    if (!data) return { ...EMPTY_FORM, email: userEmail || '' };
    return {
        first_name: data.first_name || '',
        last_name: data.last_name || '',
        email: data.email || userEmail || '',
        phone: data.phone || '',
        location: data.location || '',
        linkedin_url: data.linkedin_url || '',
        portfolio_url: data.portfolio_url || '',
        github_url: data.github_url || '',
        years_experience: data.years_experience ?? 0,
        expected_salary: data.expected_salary || '',
    };
}

const fieldClass =
    'min-h-10 w-full rounded-md border border-[var(--line)] bg-white px-3 text-sm text-[var(--ink)] outline-none transition-colors placeholder:text-slate-400 focus:border-[var(--accent)]';
const labelClass = 'mb-1 block text-sm font-semibold text-[var(--ink)]';

export const UserProfile = forwardRef<UserProfileHandle, UserProfileProps>((props, ref) => {
    const [form, setForm] = useState<FormData>(buildForm(props.initialData, props.userEmail));
    const [saving, setSaving] = useState(false);
    const [status, setStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
    const [profileComplete, setProfileComplete] = useState(false);

    useEffect(() => {
        if (props.initialData || props.userEmail) {
            setForm(buildForm(props.initialData, props.userEmail));
        }
    }, [props.initialData, props.userEmail]);

    useEffect(() => {
        const required = [form.first_name, form.last_name, form.email, form.phone, form.location];
        setProfileComplete(required.every(v => v.trim() !== ''));
    }, [form]);

    const handleChange = (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
        const { name, value } = e.target;
        setForm(prev => ({
            ...prev,
            [name]: name === 'years_experience' ? parseInt(value) || 0 : value,
        }));
    };

    const doSave = async (silent = false): Promise<boolean> => {
        setSaving(true);
        setStatus(null);
        try {
            await saveProfile(form);
            if (!silent) setStatus({ type: 'success', message: 'Profile saved successfully.' });
            return true;
        } catch (err) {
            setStatus({ type: 'error', message: getErrorMessage(err, 'Failed to save profile') });
            return false;
        } finally {
            setSaving(false);
        }
    };

    useImperativeHandle(ref, () => ({ save: doSave }));

    const completionFields = [
        { key: 'first_name', label: 'First name' },
        { key: 'last_name', label: 'Last name' },
        { key: 'email', label: 'Email' },
        { key: 'phone', label: 'Phone' },
        { key: 'location', label: 'Location' },
    ] as const;

    const filledCount = completionFields.filter(f => (form[f.key] as string).trim() !== '').length;
    const pct = Math.round((filledCount / completionFields.length) * 100);

    const renderInput = (
        label: string,
        name: keyof FormData,
        placeholder: string,
        type = 'text',
        required = false,
        className?: string,
    ) => (
        <div className={className}>
            <label className={labelClass}>{label}{required ? ' *' : ''}</label>
            <input
                type={type}
                name={name}
                value={form[name]}
                onChange={handleChange}
                placeholder={placeholder}
                className={fieldClass}
            />
        </div>
    );

    return (
        <div className="w-full space-y-4">
            <div className={cn(
                'flex items-start gap-3 rounded-lg border p-3',
                profileComplete
                    ? 'border-[var(--positive-soft)] bg-[var(--positive-soft)]'
                    : 'border-[var(--warning-soft)] bg-[var(--warning-soft)]',
            )}>
                <span className={cn(
                    'flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-white',
                    profileComplete ? 'text-[var(--positive)]' : 'text-[var(--warning)]',
                )}>
                    {profileComplete ? <CheckCircle2 size={19} /> : <AlertCircle size={19} />}
                </span>
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <p className={cn('text-sm font-semibold', profileComplete ? 'text-[var(--positive)]' : 'text-[var(--warning)]')}>
                            {profileComplete ? 'Profile complete' : 'Profile incomplete'}
                        </p>
                        <StatusChip tone={profileComplete ? 'success' : 'warning'}>{pct}%</StatusChip>
                    </div>
                    <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
                        Required contact fields help the assistant write accurate materials and fill application forms.
                    </p>
                    <ProgressBar value={pct} className="mt-2 bg-white/70" />
                </div>
            </div>

            <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">
                    Required details
                </h3>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    {renderInput('First name', 'first_name', 'Simeon', 'text', true)}
                    {renderInput('Last name', 'last_name', 'Babatunde', 'text', true)}
                    {renderInput('Email', 'email', 'you@example.com', 'email', true)}
                    {renderInput('Phone', 'phone', '+1 (555) 000-0000', 'tel', true)}
                    {renderInput('Location', 'location', 'City, State / Remote', 'text', true, 'md:col-span-2')}
                </div>
            </div>

            <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">
                    Optional signals
                </h3>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    {renderInput('LinkedIn URL', 'linkedin_url', 'https://linkedin.com/in/yourname', 'url')}
                    {renderInput('Portfolio / website', 'portfolio_url', 'https://yourportfolio.com', 'url')}
                    {renderInput('GitHub URL', 'github_url', 'https://github.com/yourusername', 'url')}
                    {renderInput('Expected salary', 'expected_salary', '$120k-$150k / $85/hr')}
                    <div>
                        <label className={labelClass}>Years of experience</label>
                        <select
                            name="years_experience"
                            value={form.years_experience}
                            onChange={handleChange}
                            className={fieldClass}
                        >
                            {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 20].map(y => (
                                <option key={y} value={y}>
                                    {y === 0 ? 'Less than 1 year' : y === 20 ? '20+ years' : `${y} year${y > 1 ? 's' : ''}`}
                                </option>
                            ))}
                        </select>
                    </div>
                </div>
            </div>

            <div className="flex flex-col gap-3 border-t border-[var(--line)] pt-3 sm:flex-row sm:items-center sm:justify-between">
                {status && (
                    <p className={cn('flex items-center gap-2 text-sm font-semibold', status.type === 'success' ? 'text-[var(--positive)]' : 'text-[var(--danger)]')}>
                        {status.type === 'success' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
                        {status.message}
                    </p>
                )}
                <Button onClick={() => doSave(false)} disabled={saving} className="sm:ml-auto">
                    {saving ? <LoaderCircle className="animate-spin" size={16} /> : <Save size={16} />}
                    {saving ? 'Saving' : 'Save profile'}
                </Button>
            </div>
        </div>
    );
});
