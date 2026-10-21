(() => {
  'use strict';

  window.HaoAccountConfig = Object.freeze({
    enabled: true,
    billingEnabled: false,
    referralEnabled: false,
    standaloneReferralTrigger: false,
    appName: 'AlphaEngine',
    productCode: 'alpha_engine',
    entitlementCode: 'alpha_engine.pro',
    supabaseUrl: 'https://blgwlycfcwvsupmqyqwn.supabase.co',
    supabasePublishableKey: 'sb_publishable_n1Va-c_alpkQ0zNuJYUaxA_J0u68RVW',
    redirectUrl: 'https://liuh886.github.io/alpha_engine/',
    mountSelectors: ['[data-account-slot]'],
    compactTrigger: true,
    title: {
      zh: 'AlphaEngine 研究账户',
      en: 'AlphaEngine research account',
    },
    description: {
      zh: '查看正式策略的历史证据；当前研究观察按已有账户权限读取。',
      en: 'View formal strategy evidence. Current research observations follow the existing account access policy.',
    },
    privacyNote: {
      zh: '页面只读取已发布的研究证据。AlphaEngine 是研究工具，不构成投资建议或收益承诺。',
      en: 'This page reads published research evidence. AlphaEngine is a research tool, not investment advice or a return promise.',
    },
    feedbackEnabled: false,
  });
})();
