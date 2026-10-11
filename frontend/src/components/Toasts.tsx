import React from 'react';
import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react';
import { useGameStore } from '../store/gameStore';

const STYLE = {
  info: ['border-cyan/40 bg-cyan/10 text-cyan', Info],
  success: ['border-emerald-400/40 bg-emerald-500/10 text-emerald-200', CheckCircle2],
  warning: ['border-amber/50 bg-amber/10 text-amber', AlertTriangle],
  error: ['border-rose-400/50 bg-rose-500/15 text-rose-200', XCircle],
} as const;

export const Toasts: React.FC = () => {
  const toasts = useGameStore((s) => s.toasts);
  const dismiss = useGameStore((s) => s.dismissToast);
  return (
    <div className="fixed right-4 top-20 z-[60] flex w-[360px] flex-col gap-2">
      {toasts.map((t) => {
        const [cls, Icon] = STYLE[t.kind];
        return (
          <button key={t.id} onClick={() => dismiss(t.id)} className={`flex animate-fade-up items-start gap-2 rounded-xl border px-4 py-3 text-left text-sm font-medium backdrop-blur ${cls}`}>
            <Icon className="mt-0.5 h-4 w-4 shrink-0" /> <span>{t.text}</span>
          </button>
        );
      })}
    </div>
  );
};
