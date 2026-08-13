import { describe, expect, it, vi } from 'vitest';
import { shareUrl } from './ProductShareButton';

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
