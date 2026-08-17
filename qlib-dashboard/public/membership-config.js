(() => {
  'use strict';

  window.HaoAccountConfig = Object.freeze({
    enabled: true,
    billingEnabled: true,
    referralEnabled: true,
    standaloneReferralTrigger: false,
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
      zh: '正式模型的历史绩效与风险证据公开展示。登录后可使用 Security Explorer；AlphaEngine Pro 解锁高级模型的当前持仓、目标调仓与实时信号。',
      en: 'Formal historical performance and risk evidence stay public. Sign in to use Security Explorer; AlphaEngine Pro unlocks current holdings, target allocations, and live signals for advanced models.',
    },
    privacyNote: {
      zh: '本地研究包、持仓文件、模型参数与实验数据不会上传。AlphaEngine 是研究工具，不构成投资建议或收益承诺。',
      en: 'Local research bundles, holdings files, model parameters, and experiment data are not uploaded. AlphaEngine is a research tool, not investment advice or a return promise.',
    },
    proUpgrade: {
      title: { zh: 'Free 与 AlphaEngine Pro', en: 'Free and AlphaEngine Pro' },
      freeTitle: { zh: '正式绩效公开', en: 'Formal performance stays public' },
      freeFeatures: [
        { zh: '查看正式模型的历史收益、风险与公开研究证据', en: 'View historical return, risk, and public research evidence for formal models' },
        { zh: '登录后使用 Security Explorer', en: 'Sign in to use Security Explorer' },
      ],
      proTitle: { zh: 'AlphaEngine Pro', en: 'AlphaEngine Pro' },
      proFeatures: [
        { zh: '查看 Pro 模型的当前持仓与目标调仓', en: 'View current holdings and target allocations for Pro models' },
        { zh: '查看当前交易信号、驱动因子与下一决策状态', en: 'View current trade signals, signal drivers, and next-decision state' },
      ],
      note: {
        zh: 'AlphaEngine 是研究工具，不构成投资建议或收益承诺。',
        en: 'AlphaEngine is a research tool, not investment advice or a return promise.',
      },
      checkoutDescription: {
        zh: 'US$1/月开通 AlphaEngine Pro，解锁高级模型的当前持仓、目标调仓与实时决策信号。',
        en: 'AlphaEngine Pro is US$1/month and unlocks current holdings, target allocations, and live decision signals for advanced models.',
      },
      ctaTitle: { zh: '开通 AlphaEngine Pro', en: 'Upgrade to AlphaEngine Pro' },
    },
    feedbackEnabled: false,
  });
})();