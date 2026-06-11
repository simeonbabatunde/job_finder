import type {
    ButtonHTMLAttributes,
    HTMLAttributes,
    InputHTMLAttributes,
    LabelHTMLAttributes,
    ReactNode,
} from 'react';
import { AlertCircle, CheckCircle2, Info, LoaderCircle, TriangleAlert } from 'lucide-react';
import { cn } from '../lib/cn';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    variant?: ButtonVariant;
    size?: ButtonSize;
}

const buttonVariants: Record<ButtonVariant, string> = {
    primary: 'bg-[var(--accent)] text-white border-transparent hover:bg-[var(--accent-hover)]',
    secondary: 'bg-white text-[var(--ink)] border-[var(--line)] hover:border-[var(--accent)] hover:text-[var(--accent)]',
    ghost: 'bg-transparent text-[var(--muted)] border-transparent hover:bg-[var(--soft)] hover:text-[var(--ink)]',
    danger: 'bg-[var(--danger-soft)] text-[var(--danger)] border-transparent hover:bg-red-100',
};

const buttonSizes: Record<ButtonSize, string> = {
    sm: 'min-h-9 px-3 text-xs',
    md: 'min-h-10 px-4 text-sm',
    lg: 'min-h-12 px-5 text-sm',
};

export function Button({
    className,
    variant = 'primary',
    size = 'md',
    type = 'button',
    ...props
}: ButtonProps) {
    return (
        <button
            type={type}
            className={cn(
                'inline-flex items-center justify-center gap-2 rounded-md border font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60',
                buttonVariants[variant],
                buttonSizes[size],
                className,
            )}
            {...props}
        />
    );
}

type NoticeTone = 'success' | 'error' | 'warning' | 'info';

interface NoticeProps extends HTMLAttributes<HTMLDivElement> {
    tone?: NoticeTone;
    title?: string;
    children: ReactNode;
}

const noticeStyles: Record<NoticeTone, string> = {
    success: 'border-[var(--positive-soft)] bg-[var(--positive-soft)] text-[var(--positive)]',
    error: 'border-[var(--danger-soft)] bg-[var(--danger-soft)] text-[var(--danger)]',
    warning: 'border-[var(--warning-soft)] bg-[var(--warning-soft)] text-[var(--warning)]',
    info: 'border-[var(--accent-soft)] bg-[var(--accent-soft)] text-[var(--accent)]',
};

const noticeIcons = {
    success: CheckCircle2,
    error: AlertCircle,
    warning: TriangleAlert,
    info: Info,
};

export function Notice({ tone = 'info', title, children, className, ...props }: NoticeProps) {
    const Icon = noticeIcons[tone];
    return (
        <div
            role={tone === 'error' || tone === 'warning' ? 'alert' : 'status'}
            aria-live={tone === 'error' || tone === 'warning' ? 'assertive' : 'polite'}
            className={cn(
                'flex items-start gap-2 rounded-md border px-3 py-2 text-sm',
                noticeStyles[tone],
                className,
            )}
            {...props}
        >
            <Icon className="mt-0.5 shrink-0" size={16} />
            <div className="min-w-0">
                {title && <p className="font-semibold">{title}</p>}
                <div className={cn('leading-5', title ? 'mt-0.5 text-xs' : 'font-semibold')}>
                    {children}
                </div>
            </div>
        </div>
    );
}

interface ConfirmDialogProps {
    open: boolean;
    title: string;
    description?: ReactNode;
    confirmLabel: string;
    cancelLabel?: string;
    confirmVariant?: ButtonVariant;
    iconTone?: NoticeTone;
    loading?: boolean;
    loadingLabel?: string;
    onConfirm: () => void;
    onCancel: () => void;
}

export function ConfirmDialog({
    open,
    title,
    description,
    confirmLabel,
    cancelLabel = 'Cancel',
    confirmVariant = 'danger',
    iconTone = 'warning',
    loading = false,
    loadingLabel = 'Working',
    onConfirm,
    onCancel,
}: ConfirmDialogProps) {
    if (!open) return null;
    const Icon = noticeIcons[iconTone];

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4">
            <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="confirm-dialog-title"
                className="w-full max-w-md rounded-lg border border-[var(--line)] bg-white shadow-xl"
            >
                <div className="flex items-start gap-3 border-b border-[var(--line)] p-5">
                    <span className={cn(
                        'mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-white',
                        iconTone === 'success' && 'bg-[var(--positive-soft)] text-[var(--positive)]',
                        iconTone === 'error' && 'bg-[var(--danger-soft)] text-[var(--danger)]',
                        iconTone === 'warning' && 'bg-[var(--warning-soft)] text-[var(--warning)]',
                        iconTone === 'info' && 'bg-[var(--accent-soft)] text-[var(--accent)]',
                    )}>
                        <Icon size={18} />
                    </span>
                    <div>
                        <h3 id="confirm-dialog-title" className="text-base font-semibold text-[var(--ink)]">
                            {title}
                        </h3>
                        {description && (
                            <div className="mt-1 text-sm leading-6 text-[var(--muted)]">
                                {description}
                            </div>
                        )}
                    </div>
                </div>
                <div className="flex flex-col gap-2 p-5 sm:flex-row sm:justify-end">
                    <Button variant="secondary" onClick={onCancel} disabled={loading}>
                        {cancelLabel}
                    </Button>
                    <Button variant={confirmVariant} onClick={onConfirm} disabled={loading}>
                        {loading ? <LoaderCircle className="animate-spin" size={16} /> : null}
                        {loading ? loadingLabel : confirmLabel}
                    </Button>
                </div>
            </div>
        </div>
    );
}

interface IconButtonProps extends ButtonProps {
    label: string;
}

export function IconButton({ label, className, children, ...props }: IconButtonProps) {
    return (
        <Button
            aria-label={label}
            title={label}
            className={cn('aspect-square px-0', className)}
            {...props}
        >
            {children}
        </Button>
    );
}

export function PageShell({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
    return (
        <main
            className={cn('mx-auto w-full max-w-7xl px-5 py-6 md:py-8', className)}
            {...props}
        />
    );
}

export function Panel({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
    return (
        <section
            className={cn('rounded-lg border border-[var(--line)] bg-white shadow-sm', className)}
            {...props}
        />
    );
}

interface SectionHeaderProps extends HTMLAttributes<HTMLDivElement> {
    eyebrow?: string;
    title: string;
    description?: string;
    action?: ReactNode;
}

export function SectionHeader({
    eyebrow,
    title,
    description,
    action,
    className,
    ...props
}: SectionHeaderProps) {
    return (
        <div className={cn('flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between', className)} {...props}>
            <div className="min-w-0">
                {eyebrow && (
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--accent)]">
                        {eyebrow}
                    </p>
                )}
                <h2 className="text-xl font-semibold text-[var(--ink)]">{title}</h2>
                {description && (
                    <p className="mt-1 max-w-2xl text-sm leading-6 text-[var(--muted)]">
                        {description}
                    </p>
                )}
            </div>
            {action && <div className="shrink-0">{action}</div>}
        </div>
    );
}

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
    label: string;
    hint?: string;
    error?: string;
    containerClassName?: string;
    labelProps?: LabelHTMLAttributes<HTMLLabelElement>;
}

export function TextField({
    label,
    hint,
    error,
    id,
    className,
    containerClassName,
    labelProps,
    ...props
}: TextFieldProps) {
    const fieldId = id ?? props.name;
    return (
        <div className={containerClassName}>
            <label
                htmlFor={fieldId}
                className="mb-1 block text-sm font-semibold text-[var(--ink)]"
                {...labelProps}
            >
                {label}
            </label>
            <input
                id={fieldId}
                className={cn(
                    'min-h-10 w-full rounded-md border border-[var(--line)] bg-white px-3 text-sm text-[var(--ink)] outline-none transition-colors placeholder:text-slate-400 focus:border-[var(--accent)]',
                    error && 'border-[var(--danger)]',
                    className,
                )}
                {...props}
            />
            {hint && !error && <p className="mt-1 text-xs text-[var(--muted)]">{hint}</p>}
            {error && <p className="mt-1 text-xs font-semibold text-[var(--danger)]">{error}</p>}
        </div>
    );
}

interface StatusChipProps extends HTMLAttributes<HTMLSpanElement> {
    tone?: 'neutral' | 'accent' | 'success' | 'warning' | 'danger';
}

const statusTones: Record<NonNullable<StatusChipProps['tone']>, string> = {
    neutral: 'bg-[var(--soft)] text-[var(--muted)]',
    accent: 'bg-[var(--accent-soft)] text-[var(--accent)]',
    success: 'bg-[var(--positive-soft)] text-[var(--positive)]',
    warning: 'bg-[var(--warning-soft)] text-[var(--warning)]',
    danger: 'bg-[var(--danger-soft)] text-[var(--danger)]',
};

export function StatusChip({ className, tone = 'neutral', ...props }: StatusChipProps) {
    return (
        <span
            className={cn(
                'inline-flex min-h-7 items-center rounded-md px-2.5 text-xs font-semibold',
                statusTones[tone],
                className,
            )}
            {...props}
        />
    );
}

interface MetricTileProps {
    label: string;
    value: ReactNode;
    detail?: ReactNode;
    className?: string;
}

export function MetricTile({ label, value, detail, className }: MetricTileProps) {
    return (
        <div className={cn('rounded-lg border border-[var(--line)] bg-[var(--page)] p-4', className)}>
            <p className="text-sm text-[var(--muted)]">{label}</p>
            <div className="mt-2 text-2xl font-semibold text-[var(--ink)]">{value}</div>
            {detail && <p className="mt-1 text-xs text-[var(--muted)]">{detail}</p>}
        </div>
    );
}

export function EmptyState({ title, detail }: { title: string; detail?: string }) {
    return (
        <div className="rounded-lg border border-dashed border-[var(--line)] bg-white p-8 text-left">
            <h3 className="text-lg font-semibold text-[var(--ink)]">{title}</h3>
            {detail && <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--muted)]">{detail}</p>}
        </div>
    );
}

export function ProgressBar({ value, className }: { value: number; className?: string }) {
    const safeValue = Math.max(0, Math.min(100, value));
    return (
        <div className={cn('h-2 overflow-hidden rounded-full bg-[var(--soft)]', className)}>
            <div
                className="h-full rounded-full bg-[var(--accent)] transition-all"
                style={{ width: `${safeValue}%` }}
            />
        </div>
    );
}
