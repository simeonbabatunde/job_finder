import { useEffect, useMemo, useState } from 'react';
import { CreditCard, LoaderCircle, Settings, Sparkles } from 'lucide-react';
import {
    createBillingCheckoutSession,
    createBillingPortalSession,
    getBillingStatus,
    getErrorMessage,
} from '../api/client';
import type { BillingStatus } from '../api/client';
import { Button, Notice, StatusChip } from './ui';

const freeFeatures = ['3 matching runs per day', 'Generated packages', 'Pipeline tracking'];
const proFeatures = ['50 matching runs per day', 'Fill-for-review', 'Higher search volume'];

function formatBillingDate(value?: string | null) {
    if (!value) return null;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

export function BillingSettings() {
    const [billing, setBilling] = useState<BillingStatus | null>(null);
    const [loading, setLoading] = useState(true);
    const [actionLoading, setActionLoading] = useState<'checkout' | 'portal' | null>(null);
    const [notice, setNotice] = useState<{ tone: 'success' | 'error' | 'info'; message: string } | null>(null);

    const returnNotice = useMemo(() => {
        const billingResult = new URLSearchParams(window.location.search).get('billing');
        if (billingResult === 'success') return 'Stripe is confirming your Pro subscription. Your plan updates automatically after the webhook lands.';
        if (billingResult === 'cancelled') return 'Checkout was cancelled. You can upgrade whenever you are ready.';
        if (billingResult === 'portal_return') return 'Billing changes sync from Stripe automatically.';
        return '';
    }, []);

    useEffect(() => {
        let active = true;
        const loadBilling = async () => {
            setLoading(true);
            try {
                const data = await getBillingStatus();
                if (active) {
                    setBilling(data);
                    setNotice(returnNotice ? { tone: 'info', message: returnNotice } : null);
                }
            } catch (error) {
                if (active) setNotice({ tone: 'error', message: getErrorMessage(error, 'Failed to load billing status') });
            } finally {
                if (active) setLoading(false);
            }
        };
        void loadBilling();
        return () => {
            active = false;
        };
    }, [returnNotice]);

    const handleCheckout = async () => {
        setActionLoading('checkout');
        setNotice(null);
        try {
            const session = await createBillingCheckoutSession();
            window.location.href = session.url;
        } catch (error) {
            setNotice({ tone: 'error', message: getErrorMessage(error, 'Failed to start Pro checkout') });
        } finally {
            setActionLoading(null);
        }
    };

    const handlePortal = async () => {
        setActionLoading('portal');
        setNotice(null);
        try {
            const session = await createBillingPortalSession();
            window.location.href = session.url;
        } catch (error) {
            setNotice({ tone: 'error', message: getErrorMessage(error, 'Failed to open billing management') });
        } finally {
            setActionLoading(null);
        }
    };

    const periodEnd = formatBillingDate(billing?.subscription_current_period_end);
    const isPro = billing?.plan === 'pro';

    return (
        <section className="space-y-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--accent)]">Billing</p>
                    <h3 className="mt-1 text-xl font-semibold text-[var(--ink)]">Plan and subscription</h3>
                    <p className="mt-1 text-sm leading-6 text-[var(--muted)]">
                        Upgrade to Pro for higher matching volume and supported application form prep.
                    </p>
                </div>
                {billing && (
                    <StatusChip tone={isPro ? 'accent' : 'neutral'}>
                        {billing.plan} plan
                    </StatusChip>
                )}
            </div>

            {notice && <Notice tone={notice.tone}>{notice.message}</Notice>}

            {loading ? (
                <div className="flex items-center gap-2 rounded-md border border-[var(--line)] bg-white px-3 py-2 text-sm font-semibold text-[var(--muted)]">
                    <LoaderCircle className="animate-spin" size={16} />
                    Loading billing
                </div>
            ) : billing ? (
                <>
                    <div className="grid gap-px overflow-hidden rounded-md bg-[var(--line)] text-sm sm:grid-cols-2">
                        <div className="bg-[var(--page)] p-3">
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <p className="font-semibold text-[var(--ink)]">Free</p>
                                    <p className="mt-0.5 text-xs font-semibold text-[var(--muted)]">$0/month</p>
                                </div>
                                {!isPro && <StatusChip tone="success">Current</StatusChip>}
                            </div>
                            <ul className="mt-3 space-y-1.5 text-xs leading-5 text-[var(--muted)]">
                                {freeFeatures.map(feature => <li key={feature}>{feature}</li>)}
                            </ul>
                        </div>
                        <div className="bg-[var(--accent-soft)] p-3">
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <p className="font-semibold text-[var(--ink)]">Pro</p>
                                    <p className="mt-0.5 text-xs font-semibold text-[var(--accent)]">{billing.pro_price_label}</p>
                                </div>
                                {isPro ? <StatusChip tone="accent">Current</StatusChip> : <Sparkles size={18} className="text-[var(--accent)]" />}
                            </div>
                            <ul className="mt-3 space-y-1.5 text-xs leading-5 text-[var(--ink)]">
                                {proFeatures.map(feature => <li key={feature}>{feature}</li>)}
                            </ul>
                        </div>
                    </div>

                    {isPro && (billing.subscription_status || periodEnd) && (
                        <p className="text-xs leading-5 text-[var(--muted)]">
                            Status: {billing.subscription_status || 'active'}{periodEnd ? ` through ${periodEnd}` : ''}
                            {billing.subscription_cancel_at_period_end ? '. Cancels at period end.' : ''}
                        </p>
                    )}

                    {!billing.billing_enabled && (
                        <Notice tone="info">
                            Billing is not configured in this environment. Add Stripe keys before enabling paid upgrades.
                        </Notice>
                    )}

                    <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
                        {isPro ? (
                            <Button
                                type="button"
                                variant="secondary"
                                onClick={handlePortal}
                                disabled={!billing.can_manage_billing || actionLoading !== null}
                            >
                                {actionLoading === 'portal' ? <LoaderCircle className="animate-spin" size={16} /> : <Settings size={16} />}
                                Manage billing
                            </Button>
                        ) : (
                            <Button
                                type="button"
                                onClick={handleCheckout}
                                disabled={!billing.can_upgrade || actionLoading !== null}
                            >
                                {actionLoading === 'checkout' ? <LoaderCircle className="animate-spin" size={16} /> : <CreditCard size={16} />}
                                Upgrade to Pro
                            </Button>
                        )}
                    </div>
                </>
            ) : null}
        </section>
    );
}
