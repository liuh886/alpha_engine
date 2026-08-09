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
      zh: 'Free 用户可浏览标准正式模型；AlphaEngine Pro 可浏览 Pro 级别模型。目前 QQQ 系列为 Pro 模型，包含当前配置、正式回测、归因与研究证据。',
      en: 'Free users can browse standard formal models. AlphaEngine Pro unlocks Pro-tier models; the QQQ family is currently Pro and includes current allocation, formal backtests, attribution, and research evidence.',
    },
    privacyNote: {
      zh: '本地研究包、持仓文件、模型参数与实验数据不会上传到共享账户。AlphaEngine 是研究工具，不构成投资建议或收益承诺。',
      en: 'Local research bundles, holdings files, model parameters, and experiment data are not uploaded to the shared account. AlphaEngine is a research tool, not investment advice or a return promise.',
    },
    features: [
      { zh: 'Free：浏览标准正式模型', en: 'Free: browse standard formal models' },
      { zh: 'Pro：浏览 QQQ 系列 Pro 模型与完整研究视图', en: 'Pro: browse QQQ Pro models and their full research views' },
      { zh: '与其他 Hao Apps 共用同一登录身份', en: 'Use the same identity across Hao Apps' },
    ],
    feedbackEnabled: false,
  });
})();
