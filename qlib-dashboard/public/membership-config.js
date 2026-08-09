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
      zh: '登录用于保存轻量研究偏好、统一权益，并为未来高级研究模型、完整归因与可复现研究包建立访问基础。',
      en: 'Sign in to keep lightweight research preferences, unify access, and prepare for future advanced research models, full attribution, and reproducible research packages.',
    },
    privacyNote: {
      zh: '本地研究包、持仓文件、模型参数与实验数据不会上传到共享账户。AlphaEngine 是研究工具，不构成投资建议或收益承诺。',
      en: 'Local research bundles, holdings files, model parameters, and experiment data are not uploaded to the shared account. AlphaEngine is a research tool, not investment advice or a return promise.',
    },
    features: [
      { zh: '未来解锁高级研究模型与完整归因视图', en: 'Prepare for advanced research models and full attribution views' },
      { zh: '未来保存模型、市场与视图偏好', en: 'Prepare to save model, market, and view preferences' },
      { zh: '与其他 Hao Apps 共用同一登录身份', en: 'Use the same identity across Hao Apps' },
    ],
    feedbackEnabled: false,
  });
})();
