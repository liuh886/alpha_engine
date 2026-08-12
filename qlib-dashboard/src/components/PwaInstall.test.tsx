import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PwaInstallProvider } from './PwaInstall';

describe('PwaInstallProvider', () => {
  beforeEach(() => {
    sessionStorage.clear();
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockImplementation(() => ({
        matches: false,
        media: '',
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  it('surfaces and invokes the captured browser install prompt', async () => {
    render(<PwaInstallProvider><div>Product</div></PwaInstallProvider>);
    const prompt = vi.fn().mockResolvedValue(undefined);
    const event = new Event('beforeinstallprompt') as Event & {
      prompt: () => Promise<void>;
      userChoice: Promise<{ outcome: 'accepted'; platform: string }>;
    };
    event.prompt = prompt;
    event.userChoice = Promise.resolve({ outcome: 'accepted', platform: 'web' });

    act(() => { window.dispatchEvent(event); });
    const install = await screen.findByRole('button', { name: 'Install' });
    fireEvent.click(install);

    await waitFor(() => expect(prompt).toHaveBeenCalledOnce());
  });
});
