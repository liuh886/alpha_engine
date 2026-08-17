import { useEffect, useState } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { Check, Link2, Share2, UserPlus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAlphaMembership } from '@/hooks/useAlphaMembership';
import { cn } from '@/lib/utils';

type ShareState = 'idle' | 'copied' | 'failed';

interface HaoReferralApi {
  open?: () => void;
}

declare global {
  interface Window {
    HaoReferral?: HaoReferralApi;
  }
}

export async function shareUrl({ title, text, url }: { title: string; text: string; url: string }): Promise<'shared' | 'copied' | 'cancelled' | 'failed'> {
  if (typeof navigator.share === 'function') {
    try {
      await navigator.share({ title, text, url });
      return 'shared';
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return 'cancelled';
    }
  }
  try {
    await navigator.clipboard.writeText(url);
    return 'copied';
  } catch {
    return 'failed';
  }
}

export function openReferralInvite(): 'referral' | 'account' | 'unavailable' {
  if (window.HaoReferral?.open) {
    window.HaoReferral.open();
    return 'referral';
  }
  if (window.HaoAccount?.open) {
    window.HaoAccount.open();
    return 'account';
  }
  return 'unavailable';
}

export function ProductShareButton({ landing = false, className }: { landing?: boolean; className?: string }) {
  const [state, setState] = useState<ShareState>('idle');
  const [open, setOpen] = useState(false);
  const [fallbackUrl, setFallbackUrl] = useState('');
  const membership = useAlphaMembership();

  useEffect(() => {
    if (state !== 'copied') return undefined;
    const timer = window.setTimeout(() => setState('idle'), 1800);
    return () => window.clearTimeout(timer);
  }, [state]);

  const handleShare = async () => {
    const url = window.location.href;
    const result = await shareUrl({
      title: 'Alpha Engine — Systematic Strategy Console',
      text: 'Inspect systematic strategies, current decisions, formal performance, risk and evidence in Alpha Engine.',
      url,
    });
    if (result === 'failed') {
      setFallbackUrl(url);
      setState('failed');
      return;
    }
    if (result === 'copied') setState('copied');
    if (result !== 'cancelled') setOpen(false);
  };

  const handleInvite = () => {
    setOpen(false);
    openReferralInvite();
  };

  const inviteDescription = membership.signedIn
    ? membership.isPro
      ? 'Give eligible new users the current complimentary Alpha Engine Pro trial.'
      : 'Share your permanent personal Alpha Engine invite link.'
    : 'Sign in to create and share your personal invite link.';

  const trigger = landing ? (
    <button
      type="button"
      className={cn('landing-icon-button', className)}
      aria-label="Share Alpha Engine"
      title="Share"
    >
      {state === 'copied' ? <Check className="h-4 w-4" /> : <Share2 className="h-4 w-4" />}
    </button>
  ) : (
    <Button
      variant="ghost"
      size="sm"
      className={cn('h-8 gap-1.5 px-2.5 text-xs font-medium', className)}
      aria-label="Share Alpha Engine"
      title="Share"
    >
      {state === 'copied' ? <Check className="h-4 w-4" /> : <Share2 className="h-4 w-4" />}
      <span className="hidden sm:inline">{state === 'copied' ? 'Copied' : 'Share'}</span>
    </Button>
  );

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>{trigger}</Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          collisionPadding={12}
          className="z-50 w-[min(19rem,calc(100vw-24px))] rounded-xl border border-border/80 bg-popover p-1.5 text-popover-foreground shadow-xl outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95"
        >
          <button
            type="button"
            className="flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => void handleShare()}
          >
            <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border/70 bg-background">
              {state === 'copied' ? <Check className="h-4 w-4" /> : <Link2 className="h-4 w-4" />}
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-medium">{state === 'copied' ? 'Link copied' : 'Share this page'}</span>
              <span className="mt-0.5 block text-xs leading-4 text-muted-foreground">Use your device share sheet, or copy the current view link.</span>
            </span>
          </button>

          {state === 'failed' && (
            <div role="status" className="mx-1 mb-1 rounded-lg border border-destructive/30 bg-destructive/5 p-2.5">
              <p className="text-xs font-medium text-destructive">Automatic copy failed. Select the link below and copy it manually.</p>
              <input
                aria-label="Share link for manual copy"
                readOnly
                value={fallbackUrl}
                onFocus={(event) => event.currentTarget.select()}
                className="mt-2 h-8 w-full rounded-md border bg-background px-2 font-mono text-[10px] text-foreground"
              />
            </div>
          )}

          <div className="my-1 h-px bg-border/70" />

          <button
            type="button"
            className="flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={handleInvite}
          >
            <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border/70 bg-background">
              <UserPlus className="h-4 w-4" />
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-medium">Invite a friend</span>
              <span className="mt-0.5 block text-xs leading-4 text-muted-foreground">{inviteDescription}</span>
            </span>
          </button>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
