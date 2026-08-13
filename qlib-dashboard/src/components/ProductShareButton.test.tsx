import { describe, expect, it, vi } from 'vitest';
import { openReferralInvite, shareUrl } from './ProductShareButton';

describe('shareUrl', () => {
  it('uses the native share sheet when available', async () => {
    const share = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'share', { configurable: true, value: share });

    await expect(shareUrl({ title: 'Alpha', text: 'Evidence', url: 'https://example.com' })).resolves.toBe('shared');
    expect(share).toHaveBeenCalledWith({ title: 'Alpha', text: 'Evidence', url: 'https://example.com' });
  });

  it('copies the URL when native sharing is unavailable', async () => {
    Object.defineProperty(navigator, 'share', { configurable: true, value: undefined });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });

    await expect(shareUrl({ title: 'Alpha', text: 'Evidence', url: 'https://example.com' })).resolves.toBe('copied');
    expect(writeText).toHaveBeenCalledWith('https://example.com');
  });
});

describe('openReferralInvite', () => {
  it('opens the shared referral surface when it is ready', () => {
    const open = vi.fn();
    window.HaoReferral = { open };

    expect(openReferralInvite()).toBe('referral');
    expect(open).toHaveBeenCalledOnce();
  });

  it('falls back to account sign-in when the referral surface is not ready', () => {
    window.HaoReferral = undefined;
    const open = vi.fn();
    window.HaoAccount = { open };

    expect(openReferralInvite()).toBe('account');
    expect(open).toHaveBeenCalledOnce();
  });
});
