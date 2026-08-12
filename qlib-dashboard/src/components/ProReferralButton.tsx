import { useEffect, useState } from 'react';
import { Check, Copy, Gift, Loader2, Share2 } from 'lucide-react';
import { shareUrl } from '@/components/ProductShareButton';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { useAccessControl } from '@/hooks/useAccessControl';

type ReferralProduct = {
  product_code: string;
  name: string;
  app_url: string;
};

type ReferralCreateResult = {
  ok: true;
  invite_id: string;
  invite_url: string;
  duration_days: number;
  products: ReferralProduct[];
};

function referralResult(value: unknown): ReferralCreateResult {
  if (!value || typeof value !== 'object') throw new Error('Referral response is invalid.');
  const row = value as Record<string, unknown>;
  const products = Array.isArray(row.products) ? row.products.flatMap((product) => {
    if (!product || typeof product !== 'object') return [];
    const item = product as Record<string, unknown>;
    const parsed = {
      product_code: String(item.product_code ?? ''),
      name: String(item.name ?? ''),
      app_url: String(item.app_url ?? ''),
    };
    return parsed.product_code && parsed.name && /^https:\/\//.test(parsed.app_url) ? [parsed] : [];
  }) : [];
  const durationDays = Number(row.duration_days);
  if (row.ok !== true || !row.invite_id || !row.invite_url || durationDays !== 30 || products.length !== 1 || products[0].product_code !== 'alpha_engine') {
    throw new Error('Referral response does not match the Alpha Engine 30-day offer.');
  }
  return {
    ok: true,
    invite_id: String(row.invite_id),
    invite_url: String(row.invite_url),
    duration_days: durationDays,
    products,
  };
}

function shareableInviteUrl(result: ReferralCreateResult): string {
  const url = new URL(result.invite_url);
  const params = new URLSearchParams(url.hash.slice(1));
  params.set('offer', JSON.stringify({
    duration_days: result.duration_days,
    products: result.products,
  }));
  url.hash = params.toString();
  return url.toString();
}

export function ProReferralButton() {
  const access = useAccessControl();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [inviteUrl, setInviteUrl] = useState('');
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return undefined;
    const timer = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timer);
  }, [copied]);

  if (!access.isPro || !access.signedIn) return null;

  const createInvite = async () => {
    setCreating(true);
    setError('');
    try {
      const client = await access.getClient();
      if (!client) throw new Error('Shared account client is unavailable.');
      const { data, error: functionError } = await client.functions.invoke<unknown>('membership-invite', {
        body: { action: 'create_referral' },
      });
      if (functionError) throw new Error(functionError.message || 'Could not create referral.');
      const result = referralResult(data);
      setInviteUrl(shareableInviteUrl(result));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setCreating(false);
    }
  };

  const copyInvite = async () => {
    if (!inviteUrl) return;
    await navigator.clipboard.writeText(inviteUrl);
    setCopied(true);
  };

  const shareInvite = async () => {
    if (!inviteUrl) return;
    const result = await shareUrl({
      title: 'Try Alpha Engine Pro free for 30 days',
      text: 'I use Alpha Engine Pro. This single-use invitation gives you 30 days of Alpha Engine Pro free.',
      url: inviteUrl,
    });
    if (result === 'copied') setCopied(true);
  };

  return (
    <Dialog open={open} onOpenChange={(next) => {
      setOpen(next);
      if (!next) {
        setInviteUrl('');
        setError('');
        setCopied(false);
      }
    }}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className="hidden h-8 gap-1.5 px-2.5 text-xs sm:inline-flex">
          <Gift className="h-3.5 w-3.5" /> Invite
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Give a friend 30 days of Pro</DialogTitle>
          <DialogDescription>
            As an Alpha Engine Pro member, you can create a single-use invitation. The recipient gets one free 30-day Alpha Engine Pro trial.
          </DialogDescription>
        </DialogHeader>

        <div className="rounded-lg border bg-muted/35 p-4">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Gift className="h-4 w-4" /></div>
            <div>
              <p className="text-sm font-semibold">Alpha Engine Pro · 30 days</p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">One recipient, one redemption. Existing or previous Alpha Engine Pro members cannot stack another free month.</p>
            </div>
          </div>
        </div>

        {!inviteUrl ? (
          <Button onClick={() => void createInvite()} disabled={creating} className="w-full">
            {creating ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Creating invitation</> : <><Gift className="mr-2 h-4 w-4" /> Create invitation</>}
          </Button>
        ) : (
          <div className="space-y-3">
            <div className="rounded-lg border bg-background p-3">
              <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">Single-use invitation</p>
              <p className="mt-2 break-all font-mono text-[10px] leading-relaxed text-muted-foreground">{inviteUrl}</p>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Button variant="outline" onClick={() => void copyInvite()}>
                {copied ? <Check className="mr-2 h-4 w-4" /> : <Copy className="mr-2 h-4 w-4" />}{copied ? 'Copied' : 'Copy link'}
              </Button>
              <Button onClick={() => void shareInvite()}><Share2 className="mr-2 h-4 w-4" /> Share invite</Button>
            </div>
          </div>
        )}

        {error && <p className="rounded-md border border-destructive/25 bg-destructive/5 p-3 text-xs leading-relaxed text-destructive">{error}</p>}
        <p className="text-[10px] leading-relaxed text-muted-foreground">The invitation activates through the existing Hao Apps account and Stripe trial system. It does not expose portfolio or account data to the recipient.</p>
      </DialogContent>
    </Dialog>
  );
}
