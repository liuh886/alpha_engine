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
      zh: 'AlphaEngine 按未登录、登录、Pro 与 Owner 四级管理访问。Owner 决定哪些模型和模块需要登录或 Pro 权限，模型名称本身不绑定账户级别。',
      en: 'AlphaEngine uses Guest, Member, Pro, and Owner access levels. Owner decides which models and modules require Member or Pro access; model identity does not determine account tier.',
    },
    privacyNote: {
      zh: '本地研究包、持仓文件、模型参数与实验数据不会上传到共享账户。AlphaEngine 是研究工具，不构成投资建议或收益承诺。',
      en: 'Local research bundles, holdings files, model parameters, and experiment data are not uploaded to the shared account. AlphaEngine is a research tool, not investment advice or a return promise.',
    },
    features: [
      { zh: 'Guest：浏览公开模型与公开模块', en: 'Guest: browse public models and modules' },
      { zh: 'Member：登录后浏览登录级产品', en: 'Member: unlock signed-in products' },
      { zh: 'Pro：浏览 Owner 指定的高级模型和模块', en: 'Pro: browse advanced models and modules selected by Owner' },
      { zh: 'Owner：配置每个模型与模块的开放级别', en: 'Owner: configure access for every model and module' },
      { zh: '与其他 Hao Apps 共用同一登录身份', en: 'Use the same identity across Hao Apps' },
    ],
    proUpgrade: {
      title: { zh: 'AlphaEngine 访问级别', en: 'AlphaEngine access levels' },
      freeTitle: { zh: '公开与登录产品', en: 'Public and Member products' },
      freeFeatures: [
        { zh: '浏览公开产品；登录后可使用 Owner 指定为登录级的模型和模块', en: 'Browse public products and sign in for models and modules designated as Member access by Owner' },
      ],
      proTitle: { zh: 'Owner 指定的 Pro 产品', en: 'Owner-designated Pro products' },
      proFeatures: [
        { zh: '使用 Owner 指定的高级模型、正式回测、归因与研究证据', en: 'Use advanced models, formal backtests, attribution, and research evidence designated by Owner' },
        { zh: '模型名称不决定权限；Owner 可随时调整每个产品的开放级别', en: 'Model names do not determine access; Owner can change each product level at any time' },
      ],
      note: {
        zh: 'AlphaEngine 是研究工具，不构成投资建议或收益承诺。',
        en: 'AlphaEngine is a research tool, not investment advice or a return promise.',
      },
      checkoutDescription: {
        zh: 'US$1/月开通 AlphaEngine Pro，访问由 Owner 指定的 Pro 模型与模块。',
        en: 'AlphaEngine Pro is US$1/month and unlocks models and modules designated as Pro by Owner.',
      },
      ctaTitle: { zh: '开通 AlphaEngine Pro', en: 'Upgrade to AlphaEngine Pro' },
    },
    feedbackEnabled: false,
  });
})();
