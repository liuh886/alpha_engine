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
      zh: 'Free 用户可浏览标准正式模型；QQQ 系列为 Pro 模型。登录用于管理模型访问权限与 AlphaEngine Pro。',
      en: 'Free users can browse standard formal models; the QQQ family is Pro. Sign in to manage model access and AlphaEngine Pro.',
    },
    privacyNote: {
      zh: '本地研究包、持仓文件、模型参数与实验数据不会上传到共享账户。AlphaEngine 是研究工具，不构成投资建议或收益承诺。',
      en: 'Local research bundles, holdings files, model parameters, and experiment data are not uploaded to the shared account. AlphaEngine is a research tool, not investment advice or a return promise.',
    },
    proUpgrade: {
      title: { zh: 'Free 与 AlphaEngine Pro', en: 'Free and AlphaEngine Pro' },
      freeTitle: { zh: '标准正式模型', en: 'Standard formal models' },
      freeFeatures: [
        { zh: '浏览非 Pro 的正式模型、当前信号与基础表现信息', en: 'Browse non-Pro formal models, current signals, and baseline performance information' },
      ],
      proTitle: { zh: '完整 QQQ 研究视图', en: 'Full QQQ research views' },
      proFeatures: [
        { zh: '查看 QQQ 系列 Pro 模型的当前配置与正式回测', en: 'View current allocations and formal backtests for QQQ Pro models' },
        { zh: '查看归因、风险与研究证据，并进入 Pro 模型详情', en: 'Inspect attribution, risk, research evidence, and Pro model details' },
      ],
      note: {
        zh: 'AlphaEngine 是研究工具，不构成投资建议或收益承诺。',
        en: 'AlphaEngine is a research tool, not investment advice or a return promise.',
      },
      checkoutDescription: {
        zh: 'US$1/月开通 AlphaEngine Pro，解锁 QQQ 系列模型的当前配置、正式回测、归因与研究证据。',
        en: 'AlphaEngine Pro is US$1/month and unlocks current QQQ allocations, formal backtests, attribution, and research evidence.',
      },
      ctaTitle: { zh: '开通 AlphaEngine Pro', en: 'Upgrade to AlphaEngine Pro' },
    },
    feedbackEnabled: false,
  });
})();
