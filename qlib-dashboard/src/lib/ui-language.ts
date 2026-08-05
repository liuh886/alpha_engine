export const ALPHA_ENGINE_UI_LANGUAGE = 'en' as const;

const PAGE_TITLE = 'Alpha Engine Research Studio';
const PAGE_DESCRIPTION = 'A local-first research artifact studio for inspecting governed data, models, experiments and backtests.';

/**
 * Alpha Engine currently ships one application-shell locale: English.
 * Research artifacts may retain their source language and must not be
 * treated as interface copy or translated implicitly.
 */
export function initializeUiLanguage(): void {
  if (typeof document === 'undefined') return;

  document.documentElement.lang = ALPHA_ENGINE_UI_LANGUAGE;
  document.documentElement.dataset.alphaEngineUiLanguage = ALPHA_ENGINE_UI_LANGUAGE;
  document.title = PAGE_TITLE;

  const description = document.querySelector<HTMLMetaElement>('meta[name="description"]');
  if (description) description.content = PAGE_DESCRIPTION;
}
