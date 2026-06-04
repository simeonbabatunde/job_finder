import { useEffect, useMemo, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import { AlertCircle, CheckCircle2, LoaderCircle, RotateCcw, Save, ShieldAlert } from 'lucide-react';
import type { ApplicationSubmitSettingsPayload } from '../api/client';
import {
    getErrorMessage,
    getSubmissionSettings,
    hasAuthSession,
    resetSubmissionSettings,
    saveSubmissionSettings,
} from '../api/client';
import { cn } from '../lib/cn';
import { Button, StatusChip, TextField } from './ui';

const EMPTY_SETTINGS: ApplicationSubmitSettingsPayload = {
    true_submit_enabled: false,
    true_submit_pilot_enabled: false,
    true_submit_pilot_approved: false,
    true_submit_pilot_blockers: [],
    require_human_confirmation: true,
    min_fit_score: 80,
    max_submits_per_day: 5,
    allowed_companies: [],
    denied_companies: [],
    allowed_domains: [],
    denied_domains: [],
    allowed_job_title_keywords: [],
    consent_to_submit: false,
};

function joinList(values?: string[]) {
    return (values || []).join(', ');
}

function splitList(value: string) {
    return value
        .split(',')
        .map(item => item.trim())
        .filter(Boolean);
}

function buildSettings(data?: Partial<ApplicationSubmitSettingsPayload> | null): ApplicationSubmitSettingsPayload {
    const next = { ...EMPTY_SETTINGS, ...(data || {}) };
    next.consent_to_submit = Boolean(next.true_submit_enabled || next.consented_at);
    return next;
}

export function SubmissionSettings() {
    const [settings, setSettings] = useState<ApplicationSubmitSettingsPayload>(EMPTY_SETTINGS);
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [status, setStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

    useEffect(() => {
        let active = true;
        const loadSettings = async () => {
            if (!hasAuthSession()) return;
            setLoading(true);
            try {
                const data = await getSubmissionSettings();
                if (active) setSettings(buildSettings(data));
            } catch (error) {
                if (active) setStatus({ type: 'error', message: getErrorMessage(error, 'Failed to load submission settings') });
            } finally {
                if (active) setLoading(false);
            }
        };
        void loadSettings();
        return () => {
            active = false;
        };
    }, []);

    const readiness = useMemo(() => {
        let score = 0;
        if (settings.require_human_confirmation) score += 25;
        if (settings.min_fit_score >= 70) score += 25;
        if (settings.max_submits_per_day > 0) score += 25;
        if (settings.allowed_companies.length || settings.allowed_domains.length || settings.denied_companies.length || settings.denied_domains.length) score += 25;
        return score;
    }, [settings]);
    const pilotApproved = Boolean(settings.true_submit_pilot_approved);
    const pilotBlocker = settings.true_submit_pilot_blockers?.[0] || 'True-submit readiness requires an approved pilot.';

    const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
        const { name, value, type, checked } = event.target;
        setSettings(prev => {
            const next = { ...prev };
            if (type === 'checkbox') {
                if (name === 'true_submit_enabled') {
                    next.true_submit_enabled = pilotApproved && checked;
                    next.consent_to_submit = pilotApproved && checked ? next.consent_to_submit : false;
                } else {
                    (next as Record<string, unknown>)[name] = checked;
                }
                return next;
            }
            if (name === 'min_fit_score' || name === 'max_submits_per_day') {
                (next as Record<string, unknown>)[name] = Number(value);
                return next;
            }
            (next as Record<string, unknown>)[name] = splitList(value);
            return next;
        });
    };

    const handleSubmit = async (event: FormEvent) => {
        event.preventDefault();
        if (!hasAuthSession()) {
            setStatus({ type: 'error', message: 'Sign in to save submission guardrails.' });
            return;
        }

        setSaving(true);
        setStatus(null);
        try {
            const saved = await saveSubmissionSettings(settings);
            setSettings(buildSettings(saved));
            setStatus({ type: 'success', message: 'Submission guardrails saved.' });
        } catch (error) {
            setStatus({ type: 'error', message: getErrorMessage(error, 'Failed to save submission guardrails') });
        } finally {
            setSaving(false);
        }
    };

    const handleReset = async () => {
        if (!hasAuthSession()) {
            setStatus({ type: 'error', message: 'Sign in to reset submission guardrails.' });
            return;
        }
        if (!confirm('Reset submission guardrails to defaults?')) return;

        setSaving(true);
        setStatus(null);
        try {
            const reset = await resetSubmissionSettings();
            setSettings(buildSettings(reset));
            setStatus({ type: 'success', message: 'Submission guardrails reset.' });
        } catch (error) {
            setStatus({ type: 'error', message: getErrorMessage(error, 'Failed to reset submission guardrails') });
        } finally {
            setSaving(false);
        }
    };

    return (
        <form onSubmit={handleSubmit} className="space-y-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                    <h3 className="text-base font-semibold text-[var(--ink)]">Submission guardrails</h3>
                    <p className="mt-1 text-sm leading-6 text-[var(--muted)]">
                        Final-submit rules for future human-confirmed submissions.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <StatusChip tone={settings.true_submit_enabled ? 'warning' : pilotApproved ? 'neutral' : 'danger'}>
                        {settings.true_submit_enabled ? 'Submit mode armed' : pilotApproved ? 'Submit mode off' : 'Pilot locked'}
                    </StatusChip>
                    <StatusChip tone={readiness >= 75 ? 'success' : 'warning'}>{readiness}% guarded</StatusChip>
                </div>
            </div>

            {loading ? (
                <div className="flex items-center gap-2 rounded-md border border-[var(--line)] bg-white px-3 py-2 text-sm font-semibold text-[var(--muted)]">
                    <LoaderCircle className="animate-spin" size={16} />
                    Loading guardrails
                </div>
            ) : null}

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <TextField
                    label="Minimum fit score"
                    name="min_fit_score"
                    type="number"
                    min={0}
                    max={100}
                    value={settings.min_fit_score}
                    onChange={handleInputChange}
                    hint="Future final-submit checks block applications below this score."
                />
                <TextField
                    label="Daily final-submit limit"
                    name="max_submits_per_day"
                    type="number"
                    min={0}
                    max={50}
                    value={settings.max_submits_per_day}
                    onChange={handleInputChange}
                    hint="This is a guardrail only; true submit still requires confirmation."
                />
                <TextField
                    label="Allowed companies"
                    name="allowed_companies"
                    value={joinList(settings.allowed_companies)}
                    onChange={handleInputChange}
                    placeholder="Acme, Globex"
                />
                <TextField
                    label="Denied companies"
                    name="denied_companies"
                    value={joinList(settings.denied_companies)}
                    onChange={handleInputChange}
                    placeholder="Company to avoid"
                />
                <TextField
                    label="Allowed domains"
                    name="allowed_domains"
                    value={joinList(settings.allowed_domains)}
                    onChange={handleInputChange}
                    placeholder="greenhouse.io, lever.co"
                />
                <TextField
                    label="Denied domains"
                    name="denied_domains"
                    value={joinList(settings.denied_domains)}
                    onChange={handleInputChange}
                    placeholder="example.com"
                />
                <TextField
                    label="Allowed title keywords"
                    name="allowed_job_title_keywords"
                    value={joinList(settings.allowed_job_title_keywords)}
                    onChange={handleInputChange}
                    placeholder="Backend, Platform, AI"
                    containerClassName="md:col-span-2"
                />
            </div>

            <label className="flex items-start gap-3 rounded-md border border-[var(--line)] bg-white p-3">
                <input
                    type="checkbox"
                    name="require_human_confirmation"
                    checked={settings.require_human_confirmation}
                    onChange={handleInputChange}
                    className="mt-1 h-4 w-4 rounded border-[var(--line)] text-[var(--accent)]"
                />
                <span>
                    <span className="block text-sm font-semibold text-[var(--ink)]">Require a final human confirmation per application</span>
                    <span className="mt-1 block text-xs leading-5 text-[var(--muted)]">
                        Keep this on so future submit flows stop for review before any final click.
                    </span>
                </span>
            </label>

            <div className="rounded-md border border-[var(--warning-soft)] bg-[var(--warning-soft)] p-3">
                <label className="flex items-start gap-3">
                    <input
                        type="checkbox"
                        name="true_submit_enabled"
                        checked={settings.true_submit_enabled}
                        disabled={!pilotApproved}
                        onChange={handleInputChange}
                        className="mt-1 h-4 w-4 rounded border-[var(--line)] text-[var(--warning)] disabled:cursor-not-allowed disabled:opacity-60"
                    />
                    <span>
                        <span className="flex items-center gap-2 text-sm font-semibold text-[var(--warning)]">
                            <ShieldAlert size={16} />
                            Allow future true-submit readiness
                        </span>
                        <span className="mt-1 block text-xs leading-5 text-[var(--warning)]">
                            {pilotApproved
                                ? 'This does not submit applications. It only lets readiness checks confirm whether a job could reach a future final-confirm step.'
                                : pilotBlocker}
                        </span>
                    </span>
                </label>
                {settings.true_submit_enabled && (
                    <label className="mt-3 flex items-start gap-3 rounded-md bg-white/70 p-3">
                        <input
                            type="checkbox"
                            name="consent_to_submit"
                            checked={Boolean(settings.consent_to_submit)}
                            onChange={handleInputChange}
                            className="mt-1 h-4 w-4 rounded border-[var(--line)] text-[var(--warning)]"
                        />
                        <span className="text-xs font-semibold leading-5 text-[var(--warning)]">
                            I understand future final-submit workflows must still show a per-job confirmation before any application is submitted.
                        </span>
                    </label>
                )}
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
                    <Button type="button" variant="secondary" onClick={handleReset} disabled={saving}>
                        <RotateCcw size={16} />
                        Reset
                    </Button>
                    <Button type="submit" disabled={saving || (settings.true_submit_enabled && !settings.consent_to_submit)}>
                        {saving ? <LoaderCircle className="animate-spin" size={16} /> : <Save size={16} />}
                        {saving ? 'Saving' : 'Save guardrails'}
                    </Button>
                </div>
            </div>
        </form>
    );
}
