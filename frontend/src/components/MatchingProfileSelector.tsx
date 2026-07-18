import { useEffect, useMemo, useState } from 'react';
import { Archive, Copy, Plus, Save } from 'lucide-react';
import type { MatchingProfile } from '../api/client';
import { Button, Notice, StatusChip } from './ui';

interface MatchingProfileSelectorProps {
  profiles: MatchingProfile[];
  selectedProfileId: number | null;
  saving?: boolean;
  error?: string | null;
  onSelect: (profileId: number) => void;
  onCreate: () => Promise<void> | void;
  onDuplicate: () => Promise<void> | void;
  onArchive: () => Promise<void> | void;
  onRename: (name: string) => Promise<void> | void;
}

const summarizeList = (items?: string[], fallback = 'Not set') => {
  const cleanItems = (items || []).map(item => item.trim()).filter(Boolean);
  if (!cleanItems.length) return fallback;
  if (cleanItems.length === 1) return cleanItems[0];
  return `${cleanItems[0]} +${cleanItems.length - 1}`;
};

export function MatchingProfileSelector({
  profiles,
  selectedProfileId,
  saving = false,
  error,
  onSelect,
  onCreate,
  onDuplicate,
  onArchive,
  onRename,
}: MatchingProfileSelectorProps) {
  const selectedProfile = useMemo(
    () => profiles.find(profile => profile.id === selectedProfileId) || profiles[0] || null,
    [profiles, selectedProfileId],
  );
  const [nameDraft, setNameDraft] = useState(selectedProfile?.name || '');

  useEffect(() => {
    setNameDraft(selectedProfile?.name || '');
  }, [selectedProfile?.id, selectedProfile?.name]);

  const trimmedName = nameDraft.trim();
  const hasNameChange = Boolean(selectedProfile && trimmedName && trimmedName !== selectedProfile.name);
  const resumeLabel = selectedProfile?.resume?.filename || 'No resume attached';
  const roleLabel = summarizeList(selectedProfile?.role, 'No role targets yet');
  const locationLabel = summarizeList(selectedProfile?.location, 'No markets yet');

  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--page)] p-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-[var(--ink)]">Matching profile</p>
            {selectedProfile?.is_default && <StatusChip tone="accent">Default</StatusChip>}
            {profiles.length > 0 && <StatusChip tone="neutral">{profiles.length} saved</StatusChip>}
          </div>
          <p className="max-w-2xl text-sm leading-6 text-[var(--muted)]">
            Save a resume with its own roles, markets, companies, and match threshold so each search area stays clean.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => void onCreate()} disabled={saving}>
            <Plus size={15} />
            New
          </Button>
          <Button variant="secondary" size="sm" onClick={() => void onDuplicate()} disabled={saving || !selectedProfile}>
            <Copy size={15} />
            Duplicate
          </Button>
          <Button variant="ghost" size="sm" onClick={() => void onArchive()} disabled={saving || !selectedProfile || profiles.length <= 1}>
            <Archive size={15} />
            Archive
          </Button>
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(220px,0.8fr)_minmax(220px,1fr)_auto] lg:items-end">
        <div>
          <label className="mb-1 block text-sm font-semibold text-[var(--ink)]">Saved profiles</label>
          <select
            value={selectedProfile?.id || ''}
            onChange={(event) => onSelect(Number(event.target.value))}
            className="min-h-10 w-full rounded-md border border-[var(--line)] bg-white px-3 text-sm text-[var(--ink)] outline-none transition-colors focus:border-[var(--accent)]"
            disabled={!profiles.length || saving}
          >
            {profiles.map(profile => (
              <option key={profile.id} value={profile.id}>{profile.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-sm font-semibold text-[var(--ink)]">Profile name</label>
          <input
            value={nameDraft}
            onChange={(event) => setNameDraft(event.target.value)}
            className="min-h-10 w-full rounded-md border border-[var(--line)] bg-white px-3 text-sm text-[var(--ink)] outline-none transition-colors placeholder:text-slate-400 focus:border-[var(--accent)]"
            placeholder="Embedded systems search"
            disabled={!selectedProfile || saving}
          />
        </div>
        <Button
          variant="secondary"
          size="md"
          onClick={() => void onRename(trimmedName)}
          disabled={!hasNameChange || saving}
          className="lg:mb-0"
        >
          <Save size={15} />
          Save name
        </Button>
      </div>

      <div className="mt-3 grid gap-2 text-xs text-[var(--muted)] sm:grid-cols-3">
        <div className="rounded-md border border-[var(--line)] bg-white p-2">
          <p className="font-semibold text-[var(--ink)]">Resume</p>
          <p className="mt-1 truncate">{resumeLabel}</p>
        </div>
        <div className="rounded-md border border-[var(--line)] bg-white p-2">
          <p className="font-semibold text-[var(--ink)]">Roles</p>
          <p className="mt-1 truncate">{roleLabel}</p>
        </div>
        <div className="rounded-md border border-[var(--line)] bg-white p-2">
          <p className="font-semibold text-[var(--ink)]">Markets</p>
          <p className="mt-1 truncate">{locationLabel}</p>
        </div>
      </div>

      {error && (
        <Notice tone="error" className="mt-3">
          {error}
        </Notice>
      )}
    </div>
  );
}
