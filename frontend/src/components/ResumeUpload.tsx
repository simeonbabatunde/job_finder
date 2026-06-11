import { useState, forwardRef, useImperativeHandle, useEffect } from 'react';
import { CheckCircle2, FileText, Trash2, UploadCloud } from 'lucide-react';
import type { ResumeStatus } from '../api/client';
import { uploadResume } from '../api/client';
import { cn } from '../lib/cn';
import { Button, Notice, StatusChip } from './ui';

export interface ResumeUploadHandle {
  hasFile: boolean;
  setError: (msg: string | null) => void;
  handleUpload: (silent?: boolean) => Promise<boolean>;
  setExistingResume: (filename: string) => void;
  setResumeData: (data: { filename: string, skills?: string[], summary?: string }) => void;
}

export interface ResumeUploadProps {
  initialData?: ResumeStatus | null;
}

export const ResumeUpload = forwardRef<ResumeUploadHandle, ResumeUploadProps>((props, ref) => {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const [isError, setIsError] = useState(false);
  const [existingFile, setExistingFile] = useState<string | null>(props.initialData?.filename || null);
  const [skills, setSkills] = useState<string[]>(props.initialData?.skills || []);
  const [summary, setSummary] = useState<string>(props.initialData?.summary || '');

  useEffect(() => {
    if (props.initialData) {
      setExistingFile(props.initialData.filename);
      if (props.initialData.skills) setSkills(props.initialData.skills);
      if (props.initialData.summary) setSummary(props.initialData.summary);
    }
  }, [props.initialData]);

  useImperativeHandle(ref, () => ({
    hasFile: !!file || !!existingFile,
    setError: (msg: string | null) => {
      setIsError(!!msg);
      if (msg) setMessage(msg);
    },
    handleUpload: async (silent: boolean = false) => {
      if (!file) {
        if (existingFile) return true;
        return true;
      }

      setUploading(true);
      setMessage('');
      setIsError(false);
      try {
        await uploadResume(file);
        if (!silent) {
          setMessage('Resume uploaded successfully.');
        }
        setExistingFile(file.name);
        setFile(null);
        return true;
      } catch (error) {
        setMessage('Error uploading resume.');
        setIsError(true);
        console.error(error);
        return false;
      } finally {
        setUploading(false);
      }
    },
    setExistingResume: (filename: string) => {
      setExistingFile(filename);
    },
    setResumeData: (data) => {
      setExistingFile(data.filename);
      if (data.skills) setSkills(data.skills);
      if (data.summary) setSummary(data.summary);
    }
  }));

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      setFile(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
    }
  };

  const clearCurrentResume = () => {
    setExistingFile(null);
    setSkills([]);
    setSummary('');
    setMessage('');
    setIsError(false);
  };

  return (
    <div className="w-full">
      <div
        className={cn(
          'relative rounded-lg border border-dashed p-4 text-left transition-colors',
          dragActive && 'border-[var(--accent)] bg-[var(--accent-soft)]',
          !dragActive && !isError && 'border-[var(--line)] bg-[var(--page)] hover:border-[var(--accent)]',
          isError && 'border-[var(--danger)] bg-[var(--danger-soft)]',
        )}
        onDragEnter={(e) => { handleDrag(e); setIsError(false); setMessage(''); }}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={(e) => { handleDrop(e); setIsError(false); setMessage(''); }}
      >
        <input
          type="file"
          id="file-upload"
          onChange={(e) => { handleChange(e); setIsError(false); setMessage(''); }}
          className="hidden"
        />

        {file ? (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-center gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-white text-[var(--accent)]">
                <FileText size={21} />
              </span>
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-[var(--ink)]">{file.name}</p>
                <p className="text-xs text-[var(--muted)]">{(file.size / 1024).toFixed(0)} KB selected</p>
              </div>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setFile(null)}>
              <Trash2 size={15} />
              Remove
            </Button>
          </div>
        ) : existingFile ? (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-center gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-[var(--positive-soft)] text-[var(--positive)]">
                <CheckCircle2 size={21} />
              </span>
              <div className="min-w-0">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <p className="truncate text-sm font-semibold text-[var(--ink)]">{existingFile}</p>
                  <StatusChip tone="success">Ready</StatusChip>
                </div>
                <p className="text-xs text-[var(--muted)]">This resume anchors matching and generated materials.</p>
              </div>
            </div>
            <Button variant="secondary" size="sm" onClick={clearCurrentResume}>
              Upload different file
            </Button>
          </div>
        ) : (
          <label htmlFor="file-upload" className="flex cursor-pointer flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span className="flex min-w-0 items-center gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-white text-[var(--accent)]">
                <UploadCloud size={22} />
              </span>
              <span>
                <span className="block text-sm font-semibold text-[var(--ink)]">Upload the resume to match against</span>
                <span className="mt-1 block text-xs text-[var(--muted)]">PDF, DOCX, or TXT. The assistant uses it to score fit.</span>
              </span>
            </span>
            <span className="inline-flex min-h-10 items-center justify-center rounded-md bg-[var(--accent)] px-4 text-sm font-semibold text-white">
              Choose file
            </span>
          </label>
        )}
      </div>

      {skills.length > 0 && (
        <div className="mt-3">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Extracted skills</h4>
          <div className="flex flex-wrap gap-2">
            {skills.map((skill, i) => (
              <StatusChip key={`${skill}-${i}`} tone="accent">
                {skill}
              </StatusChip>
            ))}
          </div>
        </div>
      )}

      {summary && (
        <div className="mt-3 rounded-lg border border-[var(--line)] bg-[var(--page)] p-3">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Resume summary</h4>
          <p className="text-sm leading-6 text-[var(--ink)]">{summary}</p>
        </div>
      )}

      <div className="mt-3">
        {uploading && (
          <div className="h-2 overflow-hidden rounded-full bg-[var(--soft)]">
            <div className="h-full w-full animate-pulse rounded-full bg-[var(--accent)]" />
          </div>
        )}

        {message && (
          <Notice tone={isError ? 'error' : 'success'} className="mt-3">
            {message}
          </Notice>
        )}
      </div>
    </div>
  );
});
