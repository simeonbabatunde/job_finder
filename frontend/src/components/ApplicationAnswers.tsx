import { useEffect, useMemo, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import { AlertCircle, CheckCircle2, LoaderCircle, Save, ShieldCheck, Trash2 } from 'lucide-react';
import type { ApplicationAnswerProfilePayload } from '../api/client';
import {
    deleteApplicationProfile,
    getApplicationProfile,
    getErrorMessage,
    hasAuthSession,
    saveApplicationProfile,
} from '../api/client';
import { cn } from '../lib/cn';
import { Button, StatusChip, TextField } from './ui';

const EMPTY_ANSWERS: ApplicationAnswerProfilePayload = {
    work_authorized_us: 'unspecified',
    requires_sponsorship_now: 'unspecified',
    requires_sponsorship_future: 'unspecified',
    willing_to_relocate: 'unspecified',
    remote_preference: 'unspecified',
    earliest_start_date: '',
    notice_period: '',
    desired_salary: '',
    work_authorization_notes: '',
    consent_to_use_answers: false,
    gender: 'prefer_not_to_answer',
    race_ethnicity: 'prefer_not_to_answer',
    veteran_status: 'prefer_not_to_answer',
    disability_status: 'prefer_not_to_answer',
    consent_to_use_demographics: false,
};

const yesNoOptions = [
    { value: 'unspecified', label: 'Not specified' },
    { value: 'yes', label: 'Yes' },
    { value: 'no', label: 'No' },
    { value: 'prefer_not_to_answer', label: 'Prefer not to answer' },
];

const remoteOptions = [
    { value: 'unspecified', label: 'Not specified' },
    { value: 'remote', label: 'Remote' },
    { value: 'hybrid', label: 'Hybrid' },
    { value: 'onsite', label: 'On-site' },
    { value: 'flexible', label: 'Flexible' },
    { value: 'prefer_not_to_answer', label: 'Prefer not to answer' },
];

const genderOptions = [
    { value: 'prefer_not_to_answer', label: 'Prefer not to answer' },
    { value: 'woman', label: 'Woman' },
    { value: 'man', label: 'Man' },
    { value: 'non_binary', label: 'Non-binary' },
    { value: 'self_describe', label: 'Self-describe' },
];

const raceOptions = [
    { value: 'prefer_not_to_answer', label: 'Prefer not to answer' },
    { value: 'american_indian_or_alaska_native', label: 'American Indian or Alaska Native' },
    { value: 'asian', label: 'Asian' },
    { value: 'black_or_african_american', label: 'Black or African American' },
    { value: 'hispanic_or_latino', label: 'Hispanic or Latino' },
    { value: 'native_hawaiian_or_pacific_islander', label: 'Native Hawaiian or Pacific Islander' },
    { value: 'white', label: 'White' },
    { value: 'two_or_more', label: 'Two or more races' },
    { value: 'self_describe', label: 'Self-describe' },
];

const veteranOptions = [
    { value: 'prefer_not_to_answer', label: 'Prefer not to answer' },
    { value: 'not_a_veteran', label: 'Not a veteran' },
    { value: 'veteran', label: 'Veteran' },
    { value: 'protected_veteran', label: 'Protected veteran' },
];

const disabilityOptions = [
    { value: 'prefer_not_to_answer', label: 'Prefer not to answer' },
    { value: 'no', label: 'No' },
    { value: 'yes', label: 'Yes' },
];

const fieldClass =
    'min-h-10 w-full rounded-md border border-[var(--line)] bg-white px-3 text-sm text-[var(--ink)] outline-none transition-colors focus:border-[var(--accent)]';
const labelClass = 'mb-1 block text-sm font-semibold text-[var(--ink)]';

interface ApplicationAnswersProps {
    initialData?: Partial<ApplicationAnswerProfilePayload> | null;
    onSaved?: (data: ApplicationAnswerProfilePayload) => void;
}

function buildAnswers(data?: Partial<ApplicationAnswerProfilePayload> | null): ApplicationAnswerProfilePayload {
    return { ...EMPTY_ANSWERS, ...(data || {}) };
}

export function ApplicationAnswers({ initialData, onSaved }: ApplicationAnswersProps) {
    const [answers, setAnswers] = useState<ApplicationAnswerProfilePayload>(buildAnswers(initialData));
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [status, setStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

    useEffect(() => {
        if (initialData) {
            setAnswers(buildAnswers(initialData));
        }
    }, [initialData]);

    useEffect(() => {
        let active = true;
        const loadAnswers = async () => {
            if (!hasAuthSession()) return;
            setLoading(true);
            try {
                const data = await getApplicationProfile();
                if (active && data) {
                    setAnswers(buildAnswers(data));
                }
            } catch (error) {
                if (active) {
                    setStatus({ type: 'error', message: getErrorMessage(error, 'Failed to load application answers') });
                }
            } finally {
                if (active) setLoading(false);
            }
        };
        void loadAnswers();
        return () => {
            active = false;
        };
    }, []);

    const readiness = useMemo(() => {
        const answered = [
            answers.work_authorized_us,
            answers.requires_sponsorship_now,
            answers.requires_sponsorship_future,
        ].filter(value => value && value !== 'unspecified').length;
        return Math.round((answered / 3) * 100);
    }, [answers.requires_sponsorship_future, answers.requires_sponsorship_now, answers.work_authorized_us]);

    const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
        const { name, value, type, checked } = event.target;
        setAnswers(prev => {
            const next = {
                ...prev,
                [name]: type === 'checkbox' ? checked : value,
            };
            if (name === 'consent_to_use_demographics' && !checked) {
                next.gender = 'prefer_not_to_answer';
                next.race_ethnicity = 'prefer_not_to_answer';
                next.veteran_status = 'prefer_not_to_answer';
                next.disability_status = 'prefer_not_to_answer';
            }
            return next;
        });
    };

    const handleSelectChange = (event: ChangeEvent<HTMLSelectElement>) => {
        const { name, value } = event.target;
        setAnswers(prev => ({ ...prev, [name]: value }));
    };

    const handleSubmit = async (event: FormEvent) => {
        event.preventDefault();
        if (!hasAuthSession()) {
            setStatus({ type: 'error', message: 'Sign in to save application answers.' });
            return;
        }

        setSaving(true);
        setStatus(null);
        try {
            const saved = await saveApplicationProfile(answers) as ApplicationAnswerProfilePayload;
            setAnswers(buildAnswers(saved));
            setStatus({ type: 'success', message: 'Application answers saved.' });
            onSaved?.(saved);
        } catch (error) {
            setStatus({ type: 'error', message: getErrorMessage(error, 'Failed to save application answers') });
        } finally {
            setSaving(false);
        }
    };

    const handleReset = async () => {
        if (!hasAuthSession()) {
            setStatus({ type: 'error', message: 'Sign in to reset application answers.' });
            return;
        }
        if (!confirm('Reset all saved application answers? This clears optional self-identification answers too.')) return;

        setSaving(true);
        setStatus(null);
        try {
            await deleteApplicationProfile();
            const emptyAnswers = buildAnswers(null);
            setAnswers(emptyAnswers);
            setStatus({ type: 'success', message: 'Application answers reset.' });
            onSaved?.(emptyAnswers);
        } catch (error) {
            setStatus({ type: 'error', message: getErrorMessage(error, 'Failed to reset application answers') });
        } finally {
            setSaving(false);
        }
    };

    const renderSelect = (
        label: string,
        name: keyof ApplicationAnswerProfilePayload,
        options: Array<{ value: string; label: string }>,
        disabled = false,
    ) => (
        <div>
            <label className={labelClass}>{label}</label>
            <select
                name={name}
                value={String(answers[name] || '')}
                onChange={handleSelectChange}
                disabled={disabled}
                className={cn(fieldClass, disabled && 'cursor-not-allowed bg-[var(--soft)] text-[var(--muted)]')}
            >
                {options.map(option => (
                    <option key={option.value} value={option.value}>
                        {option.label}
                    </option>
                ))}
            </select>
        </div>
    );

    return (
        <form onSubmit={handleSubmit} className="space-y-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                    <h3 className="text-base font-semibold text-[var(--ink)]">Application answers</h3>
                    <p className="mt-1 text-sm leading-6 text-[var(--muted)]">
                        Common application questions, kept separate from matching.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <StatusChip tone={readiness >= 100 ? 'success' : 'warning'}>{readiness}% ready</StatusChip>
                    {answers.consent_to_use_answers ? (
                        <StatusChip tone="success">Fill consent on</StatusChip>
                    ) : (
                        <StatusChip tone="neutral">Draft only</StatusChip>
                    )}
                </div>
            </div>

            {loading ? (
                <div className="flex items-center gap-2 rounded-md border border-[var(--line)] bg-white px-3 py-2 text-sm font-semibold text-[var(--muted)]">
                    <LoaderCircle className="animate-spin" size={16} />
                    Loading answers
                </div>
            ) : null}

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {renderSelect('Authorized to work in the U.S.', 'work_authorized_us', yesNoOptions)}
                {renderSelect('Need sponsorship now', 'requires_sponsorship_now', yesNoOptions)}
                {renderSelect('Need sponsorship in the future', 'requires_sponsorship_future', yesNoOptions)}
                {renderSelect('Open to relocation', 'willing_to_relocate', yesNoOptions)}
                {renderSelect('Preferred work setting', 'remote_preference', remoteOptions)}
                <TextField
                    label="Earliest start date"
                    name="earliest_start_date"
                    value={answers.earliest_start_date || ''}
                    onChange={handleInputChange}
                    placeholder="Immediately / July 2026"
                />
                <TextField
                    label="Notice period"
                    name="notice_period"
                    value={answers.notice_period || ''}
                    onChange={handleInputChange}
                    placeholder="2 weeks"
                />
                <TextField
                    label="Desired compensation"
                    name="desired_salary"
                    value={answers.desired_salary || ''}
                    onChange={handleInputChange}
                    placeholder="$120k-$150k / $85/hr"
                />
                <TextField
                    label="Work authorization notes"
                    name="work_authorization_notes"
                    value={answers.work_authorization_notes || ''}
                    onChange={handleInputChange}
                    placeholder="Optional note"
                    containerClassName="md:col-span-2"
                />
            </div>

            <label className="flex items-start gap-3 rounded-md border border-[var(--line)] bg-white p-3">
                <input
                    type="checkbox"
                    name="consent_to_use_answers"
                    checked={answers.consent_to_use_answers}
                    onChange={handleInputChange}
                    className="mt-1 h-4 w-4 rounded border-[var(--line)] text-[var(--accent)]"
                />
                <span>
                    <span className="block text-sm font-semibold text-[var(--ink)]">Use these answers for fill-for-review</span>
                    <span className="mt-1 block text-xs leading-5 text-[var(--muted)]">
                        Future form filling can use these answers only when this is enabled.
                    </span>
                </span>
            </label>

            <div className="rounded-md border border-[var(--line)] bg-[var(--page)] p-3">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-center gap-2">
                        <ShieldCheck size={17} className="text-[var(--accent)]" />
                        <h4 className="text-sm font-semibold text-[var(--ink)]">Optional self-identification</h4>
                    </div>
                    <label className="inline-flex items-center gap-2 text-xs font-semibold text-[var(--muted)]">
                        <input
                            type="checkbox"
                            name="consent_to_use_demographics"
                            checked={answers.consent_to_use_demographics}
                            onChange={handleInputChange}
                            className="h-4 w-4 rounded border-[var(--line)] text-[var(--accent)]"
                        />
                        Store selected answers
                    </label>
                </div>
                <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                    {renderSelect('Gender', 'gender', genderOptions, !answers.consent_to_use_demographics)}
                    {renderSelect('Race / ethnicity', 'race_ethnicity', raceOptions, !answers.consent_to_use_demographics)}
                    {renderSelect('Veteran status', 'veteran_status', veteranOptions, !answers.consent_to_use_demographics)}
                    {renderSelect('Disability status', 'disability_status', disabilityOptions, !answers.consent_to_use_demographics)}
                </div>
            </div>

            <div className="flex flex-col gap-3 border-t border-[var(--line)] pt-3 sm:flex-row sm:items-center sm:justify-between">
                {status && (
                    <p className={cn(
                        'flex items-center gap-2 text-sm font-semibold',
                        status.type === 'success' ? 'text-[var(--positive)]' : 'text-[var(--danger)]',
                    )}>
                        {status.type === 'success' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
                        {status.message}
                    </p>
                )}
                <div className="flex flex-col gap-2 sm:ml-auto sm:flex-row">
                    <Button type="button" variant="danger" onClick={handleReset} disabled={saving}>
                        <Trash2 size={16} />
                        Reset answers
                    </Button>
                    <Button type="submit" disabled={saving}>
                        {saving ? <LoaderCircle className="animate-spin" size={16} /> : <Save size={16} />}
                        {saving ? 'Saving' : 'Save application answers'}
                    </Button>
                </div>
            </div>
        </form>
    );
}
