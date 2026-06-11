import { BriefcaseBusiness, LogIn, LogOut, Settings, UserRound } from 'lucide-react';
import { cn } from '../lib/cn';
import { Button, StatusChip } from './ui';

interface AppUser {
    email: string;
    subscription_tier: string;
    role: string;
}

interface AppHeaderProps {
    user: AppUser | null;
    currentPath: string;
    onLogin: () => void;
    onLogout: () => void | Promise<void>;
}

const navItems = [
    { href: '/', label: 'Dashboard' },
    { href: '/applications', label: 'Applications' },
];

export function AppHeader({ user, currentPath, onLogin, onLogout }: AppHeaderProps) {
    const isActive = (href: string) => (href === '/' ? currentPath === '/' : currentPath.startsWith(href));

    return (
        <header className="border-b border-[var(--line)] bg-white">
            <div className="mx-auto flex max-w-7xl flex-col gap-4 px-5 py-4 md:flex-row md:items-center md:justify-between">
                <a href="/" className="flex w-fit items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--accent-soft)] text-[var(--accent)]">
                        <BriefcaseBusiness size={21} strokeWidth={2.2} />
                    </span>
                    <span>
                        <span className="block text-xs font-semibold uppercase tracking-[0.14em] text-[var(--accent)]">
                            job matching assistant
                        </span>
                        <span className="mt-0.5 block text-xl font-semibold text-[var(--ink)]">
                            JobMatchHero
                        </span>
                    </span>
                </a>

                <nav className="flex flex-wrap items-center gap-2 text-sm font-medium text-[var(--muted)]">
                    {navItems.map((item) => (
                        <a
                            key={item.href}
                            href={item.href}
                            className={cn(
                                'rounded-md px-3 py-2 transition-colors hover:bg-[var(--soft)] hover:text-[var(--ink)]',
                                isActive(item.href) && 'bg-[var(--soft)] text-[var(--ink)]',
                            )}
                        >
                            {item.label}
                        </a>
                    ))}
                    {user && (
                        <a
                            href="/settings"
                            className={cn(
                                'inline-flex items-center gap-1.5 rounded-md px-3 py-2 transition-colors hover:bg-[var(--soft)] hover:text-[var(--ink)]',
                                isActive('/settings') && 'bg-[var(--soft)] text-[var(--ink)]',
                            )}
                        >
                            <UserRound size={15} />
                            Account
                        </a>
                    )}
                    {user?.role === 'admin' && (
                        <a
                            href="/admin"
                            className={cn(
                                'inline-flex items-center gap-1.5 rounded-md px-3 py-2 transition-colors hover:bg-[var(--soft)] hover:text-[var(--ink)]',
                                isActive('/admin') && 'bg-[var(--soft)] text-[var(--ink)]',
                            )}
                        >
                            <Settings size={15} />
                            Admin
                        </a>
                    )}

                    <span className="hidden h-6 w-px bg-[var(--line)] md:block" />

                    {user ? (
                        <>
                            <StatusChip tone={user.subscription_tier === 'pro' ? 'accent' : 'neutral'}>
                                {user.subscription_tier} plan
                            </StatusChip>
                            <span className="max-w-[220px] truncate text-sm text-[var(--muted)]">
                                {user.email}
                            </span>
                            <Button variant="ghost" size="sm" onClick={onLogout}>
                                <LogOut size={15} />
                                Sign out
                            </Button>
                        </>
                    ) : (
                        <Button variant="primary" size="sm" onClick={onLogin}>
                            <LogIn size={15} />
                            Sign in
                        </Button>
                    )}
                </nav>
            </div>
        </header>
    );
}
