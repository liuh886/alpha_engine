# CN Selected Pool — Second-Round Deletion Candidates

Date: 2026-08-01
Current pool: `cn_selected_equities_v2` (163 candidates)

This document is a decision aid only. It does not modify membership or delete data.
The user intends to select at least 30 of the 40 candidates below for removal.

## Selection principles

- Remove duplicated economic exposures when a more liquid or more representative leader remains.
- Prefer clean sector representatives over conglomerates, narrow event-driven names, and property-linked laggards.
- Avoid retaining several companies driven by the same macro factor.
- Preserve the user's explicitly important symbols and the strongest representatives needed for cross-sectional rotation.
- Freeze the resulting v3 membership before inspecting performance.

## Tier A — recommended first 30 removals

1. `000157` 中联重科 — construction-machinery overlap; retain 三一重工 / 徐工机械.
2. `000338` 潍柴动力 — legacy engine and heavy-vehicle exposure; automotive representation is already broad.
3. `000617` 中油资本 — financial holding-company exposure is less clean than direct bank, broker, or insurer representatives.
4. `000703` 恒逸石化 — petrochemical overlap; retain 万华化学、华鲁恒升、卫星化学.
5. `000708` 中信特钢 — steel overlap; retain 宝钢股份 as the cleaner large-cap steel proxy.
6. `000723` 美锦能源 — coke, coal and hydrogen narrative is highly idiosyncratic; retain 中国神华 for coal exposure.
7. `000786` 北新建材 — property-chain exposure with limited incremental information after the first-round property cleanup.
8. `000876` 新希望 — agriculture overlap; retain 牧原股份 and 海大集团.
9. `000895` 双汇发展 — low-elasticity defensive consumption; food exposure remains well represented.
10. `002032` 苏泊尔 — home-appliance overlap; retain 美的、格力、海尔.
11. `002064` 华峰化学 — chemical-material overlap; stronger chemical leaders remain.
12. `002153` 石基信息 — narrow hospitality software exposure and weaker sector representativeness.
13. `002180` 纳思达 — printer and chip conglomerate exposure is comparatively idiosyncratic.
14. `002202` 金风科技 — wind-equipment overlap; retain 国电南瑞、明阳电气、金盘科技 and other power-equipment leaders.
15. `002236` 大华股份 — surveillance overlap; retain 海康威视.
16. `002252` 上海莱士 — plasma-product concentration and company-specific event risk.
17. `002304` 洋河股份 — liquor basket remains crowded; retain 贵州茅台、五粮液、山西汾酒.
18. `002508` 老板电器 — mature property-linked appliance exposure.
19. `002555` 三七互娱 — gaming overlap; retain 世纪华通 as the primary listed game representative.
20. `002558` 巨人网络 — gaming overlap; retain 世纪华通.
21. `002624` 完美世界 — gaming overlap and high product-cycle idiosyncrasy.
22. `002739` 万达电影 — cinema-chain exposure is narrow and event driven.
23. `300017` 网宿科技 — mature CDN exposure; cloud and digital-infrastructure exposure remains available elsewhere.
24. `300133` 华策影视 — content-production exposure is narrow and project driven.
25. `600050` 中国联通 — telecom-operator overlap; retain 中国电信, while 中兴通讯 represents equipment.
26. `600184` 光电股份 — narrow defence-electronics exposure; defence basket already has broader leaders.
27. `600428` 中远海特 — shipping overlap; retain 中远海能、中远海控、招商轮船.
28. `600585` 海螺水泥 — low-elasticity property and infrastructure-cycle exposure.
29. `601006` 大秦铁路 — mature single-corridor railway exposure with limited alpha elasticity.
30. `601898` 中煤能源 — coal overlap; retain 中国神华 and optionally 陕西煤业.

## Tier B — additional 10 candidates

31. `600028` 中国石化 — integrated-oil overlap; retain 中国海油 and 中国石油 if two energy majors are desired.
32. `600196` 复星医药 — diversified healthcare exposure overlaps with cleaner pharmaceutical and medical-service leaders.
33. `600600` 青岛啤酒 — mature consumer exposure with limited incremental information.
34. `600875` 东方电气 — power-equipment overlap; retain 国电南瑞 and more focused growth representatives.
35. `601111` 中国国航 — airline economics are highly cyclical and company-specific.
36. `601166` 兴业银行 — bank basket remains redundant; retain 招商银行、宁波银行 and 成都银行 / 平安银行 as needed.
37. `601225` 陕西煤业 — coal overlap; retain 中国神华 if one high-quality coal proxy is sufficient.
38. `601360` 三六零 — weak and mixed internet/cybersecurity exposure versus cleaner technology representatives.
39. `601727` 上海电气 — diversified equipment exposure overlaps with more focused power and industrial leaders.
40. `601816` 京沪高铁 — low-elasticity infrastructure asset with limited suitability for excess-return discovery.

## Protected or preferred representatives

Do not remove in this round without a separate decision:

- User-priority names: `600426`, `600522`, `601899`, `688676`, `002709`, `600026`, `002837`.
- Financial representatives: `600036`, `002142`, `600030`, `300059`, `601318`.
- Technology and advanced manufacturing leaders: `002371`, `002463`, `002475`, `300750`, `600406`, `601138`, `603501`, `603986`, `688008`.
- Consumer leaders: `000333`, `600519`, `000858`.
- Resources and energy leaders: `600938`, `601088`, `603993`.

## Execution after approval

1. Create immutable `cn_selected_equities_v3` before any performance inspection.
2. Record every approved removal and the retained sector representative.
3. Remove approved symbols from current CSV data and active provider/watchlist manifests.
4. Run pool identity, file-presence, benchmark separation and coverage tests.
5. Merge the pool-reduction PR.
6. Only then begin the separate destructive Git-history cleanup project.
