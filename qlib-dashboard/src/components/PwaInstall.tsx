import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Download, Share } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

type InstallOutcome = 'accepted' | 'dismissed' | 'manual' | 'unavailable';

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
};

type NavigatorWithStandalone = Navigator & { standalone?: boolean };

interface PwaInstallValue {
  installed: boolean;
  installable: boolean;
  iosManualInstall: boolean;
  install: () => Promise<InstallOutcome>;
}

const PwaInstallContext = createContext<PwaInstallValue | null>(null);
const SESSION_DISMISS_KEY = 'alpha-engine-pwa-install-dismissed';

function isInstalledDisplayMode(): boolean {
  return window.matchMedia('(display-mode: standalone)').matches
    || window.matchMedia('(display-mode: fullscreen)').matches
    || (navigator as NavigatorWithStandalone).standalone === true;
}

function isIosDevice(): boolean {
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

export function PwaInstallProvider({ children }: { children: ReactNode }) {
  const [promptEvent, setPromptEvent] = useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(() => isInstalledDisplayMode());
  const [dismissed, setDismissed] = useState(() => sessionStorage.getItem(SESSION_DISMISS_KEY) === '1');
  const iosManualInstall = !installed && isIosDevice();

  useEffect(() => {
    const displayMode = window.matchMedia('(display-mode: standalone)');
    const handleDisplayMode = () => setInstalled(isInstalledDisplayMode());
    const handlePrompt = (event: Event) => {
      event.preventDefault();
      setPromptEvent(event as BeforeInstallPromptEvent);
    };
    const handleInstalled = () => {
      setInstalled(true);
      setPromptEvent(null);
      sessionStorage.removeItem(SESSION_DISMISS_KEY);
    };

    displayMode.addEventListener('change', handleDisplayMode);
    window.addEventListener('beforeinstallprompt', handlePrompt);
    window.addEventListener('appinstalled', handleInstalled);
    return () => {
      displayMode.removeEventListener('change', handleDisplayMode);
      window.removeEventListener('beforeinstallprompt', handlePrompt);
      window.removeEventListener('appinstalled', handleInstalled);
    };
  }, []);

  const install = useCallback(async (): Promise<InstallOutcome> => {
    if (installed) return 'unavailable';
    if (!promptEvent) return iosManualInstall ? 'manual' : 'unavailable';
    await promptEvent.prompt();
    const choice = await promptEvent.userChoice;
    if (choice.outcome === 'accepted') {
      setPromptEvent(null);
      return 'accepted';
    }
    return 'dismissed';
  }, [installed, iosManualInstall, promptEvent]);

  const dismissBanner = useCallback(() => {
    sessionStorage.setItem(SESSION_DISMISS_KEY, '1');
    setDismissed(true);
  }, []);

  const value = useMemo<PwaInstallValue>(() => ({
    installed,
    installable: Boolean(promptEvent),
    iosManualInstall,
    install,
  }), [installed, install, iosManualInstall, promptEvent]);

  const showBanner = !installed && !dismissed && (Boolean(promptEvent) || iosManualInstall);

  return (
    <PwaInstallContext.Provider value={value}>
      {children}
      {showBanner && (
        <aside className="fixed bottom-3 left-3 right-3 z-[90] mx-auto flex max-w-xl items-center gap-3 rounded-xl border bg-card/95 p-3 shadow-2xl backdrop-blur sm:bottom-5 sm:left-auto sm:right-5 sm:w-[420px]" aria-label="Install Alpha Engine">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-primary/25 bg-primary/10 text-primary">
            <Download className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">Install Alpha Engine</p>
            <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
              {iosManualInstall ? 'Use Share → Add to Home Screen for the full-screen app experience.' : 'Keep the strategy console one tap away and open it as a full-screen app.'}
            </p>
          </div>
          {!iosManualInstall && (
            <Button size="sm" className="h-8 shrink-0" onClick={() => void install()}>Install</Button>
          )}
          {iosManualInstall && <Share className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />}
          <button type="button" className="shrink-0 px-1 text-xs font-medium text-muted-foreground hover:text-foreground" onClick={dismissBanner} aria-label="Dismiss install prompt">Later</button>
        </aside>
      )}
    </PwaInstallContext.Provider>
  );
}

export function usePwaInstall(): PwaInstallValue {
  const value = useContext(PwaInstallContext);
  if (!value) throw new Error('usePwaInstall must be used within PwaInstallProvider.');
  return value;
}

export function PwaOpenButton({ className }: { className?: string }) {
  const { installed, installable, iosManualInstall, install } = usePwaInstall();
  const shouldInstall = !installed && (installable || iosManualInstall);

  if (!shouldInstall) {
    return <a className={className} href="#/app">Open app</a>;
  }

  return (
    <button type="button" className={cn(className)} onClick={() => void install()}>
      <Download className="h-4 w-4" /> Install app
    </button>
  );
}
