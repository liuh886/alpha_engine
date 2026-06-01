# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

## [Unreleased]
### Added
- Strategy plugin architecture with auto-discovery (src/strategies/registry.py, plugins/)
- Plugin API endpoints: GET /strategy/plugins, GET /strategy/plugins/{name}/schema, POST /strategy/plugins/{name}/validate
- Version bump script (scripts/bump_version.py)
- Strategy registry test suite (tests/test_strategy_registry.py)

## [2.5.0] - 2026-05-28
### Added
- Structured logging with structlog across 50+ modules (e8fcc33, e9308bd)
- BaseIndex mixin for 8 SQLite index classes (dfe2e95)
- Pre-commit configuration updates (05d41ff)
- Logging for silent exception swallows (e8fcc33)

### Changed
- Consolidated duplicate load_watchlist into shared utility (127f4f2)
- Consolidated configuration for version, CORS, static site dir (aa7e2a5)
- Import ordering fixed via ruff auto-fix (35a59eb)

### Removed
- Dead PCA code from training pipeline (0cce845)
- Legacy V1 directories and run.py (5002f98)
- 5 dead modules with zero imports (708564b)
- Dead config.py with hardcoded password (502a09e)

### Fixed
- PM2 crash loop caused by missing PROJECT_ROOT export (451bbcd)

## [2.0.0] - 2026-04-30
### Changed
- Complete V2 architectural refactoring (68cc541, 4d886ab)
- Security hardening and mock removal checks (2f635ac)
- CI setup and artifact cleanup (3fea54c)

## [1.0.0] - 2026-03-05
### Added
- Initial release: base AlphaEngine codebase (fe351e5)
- V1 state snapshot before V2 refactoring (90f26ce)
