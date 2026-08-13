import { useEffect, useState } from 'react';
import { Check, Share2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

type ShareState = 'idle' | 'copied';

export async function shareUrl({ title, text, url }: { title: string; text: string; url: string }): Promise<'shared' | 'copied' | 'cancelled'> {
  if (typeof navigator.share === 'function') {
    try {
      await navigator.share({ title, text, url });
      return 'shared';
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return 'cancelled';
    }
  }
  await navigator.clipboard.writeText(url);
  return 'copied';
}

export function ProductShareButton({ landing = false, className }: { landing?: boolean; className?: string }) {
  const [state, setState] = useState<ShareState>('idle');

  useEffect(() => {
    if (state !== 'copied') return undefined;
    const timer = window.setTimeout(() => setState('idle'), 1800);
    return () => window.clearTimeout(timer);
  }, [state]);

  const handleShare = async () => {
    const result = await shareUrl({
      title: 'Alpha Engine — Systematic Strategy Console',
      text: 'Inspect systematic strategies, current decisions, formal performance, risk and evidence in Alpha Engine.',
      url: window.location.href,
    });
    if (result === 'copied') setState('copied');
  };

  if (landing) {
    return (
      <button type="button" className={cn('landing-icon-button', className)} onClick={() => void handleShare()} aria-label={state === 'copied' ? 'Link copied' : 'Share Alpha Engine'}>
        {state === 'copied' ? <Check className="h-4 w-4" /> : <Share2 className="h-4 w-4" />}
      </button>
    );
  }

  return (
    <Button variant="ghost" size="icon" className={cn('h-8 w-8', className)} onClick={() => void handleShare()} aria-label={state === 'copied' ? 'Link copied' : 'Share Alpha Engine'} title={state === 'copied' ? 'Link copied' : 'Share'}>
      {state === 'copied' ? <Check className="h-4 w-4" /> : <Share2 className="h-4 w-4" />}
    </Button>
  );
}
