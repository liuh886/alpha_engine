(() => {
  'use strict';

  window.HaoAccountConfig = Object.freeze({
    enabled: true,
    billingEnabled: true,
    appName: 'AlphaEngine',
    productCode: 'alpha_engine',
    entitlementCode: 'alpha_engine.pro',
    supabaseUrl: 'https://blgwlycfcwvsupmqyqwn.supabase.co',
    supabasePublishableKey: 'sb_publishable_n1Va-c_alpkQ0zNuJYUaxA_J0u68RVW',
    checkoutFunctionUrl: 'https://blgwlycfcwvsupmqyqwn.supabase.co/functions/v1/create-checkout-session',
    portalFunctionUrl: 'https://blgwlycfcwvsupmqyqwn.supabase.co/functions/v1/create-portal-session',
    redirectUrl: 'https://liuh886.github.io/alpha_engine/',
    mountSelectors: ['[data-account-slot]'],
    compactTrigger: true,
    title: {
      zh: 'AlphaEngine 研究账户',
      en: 'AlphaEngine research account',
    },
    description: {
      zh: '登录用于统一账户身份。AlphaEngine Pro 解锁高级模型、完整回测、归因与研究证据。',
      en: 'Sign in to keep one account identity. AlphaEngine Pro unlocks advanced models, full backtests, attribution, and research evidence.',
    },
    privacyNote: {
      zh: '本地研究包、持仓文件、模型参数与实验数据不会上传到共享账户。AlphaEngine 是研究工具，不构成投资建议或收益承诺。',
      en: 'Local research bundles, holdings files, model parameters, and experiment data are not uploaded to the shared account. AlphaEngine is a research tool, not investment advice or a return promise.',
    },
    proUpgrade: {
      title: { zh: 'Free 与 AlphaEngine Pro', en: 'Free and AlphaEngine Pro' },
      freeTitle: { zh: '公开研究保持开放', en: 'Public research stays open' },
      freeFeatures: [
        { zh: '浏览公开模型与公开模块；登录后使用同一 Hao Apps 身份', en: 'Browse public models and modules, and use the same Hao Apps identity after sign-in' },
      ],
      proTitle: { zh: 'AlphaEngine Pro', en: 'AlphaEngine Pro' },
      proFeatures: [
        { zh: '访问 Pro 高级模型与模块', en: 'Access Pro advanced models and modules' },
        { zh: '查看完整回测、归因与研究证据', en: 'View full backtests, attribution, and research evidence' },
      ],
      note: {
        zh: 'AlphaEngine 是研究工具，不构成投资建议或收益承诺。',
        en: 'AlphaEngine is a research tool, not investment advice or a return promise.',
      },
      checkoutDescription: {
        zh: 'US$1/月开通 AlphaEngine Pro，解锁高级模型、模块、完整回测与研究证据。',
        en: 'AlphaEngine Pro is US$1/month and unlocks advanced models, modules, full backtests, and research evidence.',
      },
      ctaTitle: { zh: '开通 AlphaEngine Pro', en: 'Upgrade to AlphaEngine Pro' },
    },
    feedbackEnabled: false,
  });
})();
