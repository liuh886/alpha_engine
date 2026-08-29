from pathlib import Path

path = Path('.github/workflows/formal-backtest-refresh.yml')
text = path.read_text(encoding='utf-8')
start = text.index('      - name: Resolve manifest-bound provider cache identity\n')
end = text.index('      - name: Transfer verified provider\n', start)
replacement = '''      - name: Resolve requested provider cache identity
        id: requested_contract
        env:
          MARKET: ${{ matrix.market }}
          REQUESTED_CUTOFF: ${{ matrix.market == 'us' && needs.prepare.outputs.us_cutoff || needs.prepare.outputs.cn_cutoff }}
        run: |
          python -m scripts.govern_formal_provider_cache contract \\
            --root . --market "$MARKET" --start 2021-01-01 \\
            --cutoff "$REQUESTED_CUTOFF" \\
            --output "artifacts/formal-refresh/provider-${MARKET}-contract.json" \\
            --github-output "$GITHUB_OUTPUT"
      - name: Restore requested governed provider cache
        id: provider_cache
        uses: actions/cache/restore@v4
        with:
          path: artifacts/formal-refresh/provider-${{ matrix.market }}
          key: ${{ steps.requested_contract.outputs.cache_key }}-governed
      - name: Install locked provider environment
        if: steps.provider_cache.outputs.cache-hit != 'true'
        run: |
          curl -LsSf https://astral.sh/uv/install.sh | sh
          echo "$HOME/.local/bin" >> "$GITHUB_PATH"
          uv sync --frozen
      - name: Resolve latest complete provider cutoff
        id: readiness
        if: steps.provider_cache.outputs.cache-hit != 'true'
        env:
          MARKET: ${{ matrix.market }}
          REQUESTED_CUTOFF: ${{ matrix.market == 'us' && needs.prepare.outputs.us_cutoff || needs.prepare.outputs.cn_cutoff }}
          SEED_CUTOFF: ${{ matrix.market == 'us' && needs.prepare.outputs.us_seed_cutoff || needs.prepare.outputs.cn_seed_cutoff }}
        run: |
          readiness="artifacts/formal-refresh/provider-${MARKET}-readiness.json"
          if [ "$MARKET" = "us" ]; then
            uv run python scripts/data/resolve_formal_provider_cutoff.py \\
              --market "$MARKET" \\
              --requested-cutoff "$REQUESTED_CUTOFF" \\
              --seed-cutoff "$SEED_CUTOFF" \\
              --output "$readiness" \\
              --github-output "$GITHUB_OUTPUT"
          else
            python - <<'PY2' >> "$GITHUB_OUTPUT"
          import json
          import os
          from pathlib import Path

          requested = os.environ["REQUESTED_CUTOFF"]
          seed = os.environ["SEED_CUTOFF"]
          payload = {
              "schema_version": "1.0",
              "evidence_type": "formal_provider_readiness_v1",
              "market": os.environ["MARKET"],
              "status": "current",
              "requested_cutoff": requested,
              "effective_cutoff": requested,
              "effective_seed_cutoff": seed,
              "research_only": True,
              "trade_ready": False,
          }
          path = Path(f"artifacts/formal-refresh/provider-{os.environ['MARKET']}-readiness.json")
          path.parent.mkdir(parents=True, exist_ok=True)
          path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
          print("provider_status=current")
          print(f"effective_cutoff={requested}")
          print(f"effective_seed_cutoff={seed}")
          PY2
          fi
      - name: Resolve effective provider cache identity
        id: contract
        if: steps.provider_cache.outputs.cache-hit != 'true'
        env:
          MARKET: ${{ matrix.market }}
          EFFECTIVE_CUTOFF: ${{ steps.readiness.outputs.effective_cutoff }}
        run: |
          python -m scripts.govern_formal_provider_cache contract \\
            --root . --market "$MARKET" --start 2021-01-01 \\
            --cutoff "$EFFECTIVE_CUTOFF" \\
            --output "artifacts/formal-refresh/provider-${MARKET}-contract.json" \\
            --github-output "$GITHUB_OUTPUT"
      - name: Restore exact effective governed provider cache
        id: effective_cache
        if: steps.provider_cache.outputs.cache-hit != 'true'
        uses: actions/cache/restore@v4
        with:
          path: artifacts/formal-refresh/provider-${{ matrix.market }}
          key: ${{ steps.contract.outputs.cache_key }}-governed
      - name: Restore previous governed provider seed
        if: steps.provider_cache.outputs.cache-hit != 'true' && steps.effective_cache.outputs.cache-hit != 'true'
        uses: actions/cache/restore@v4
        with:
          path: artifacts/formal-refresh/provider-${{ matrix.market }}
          key: formal-provider-seed-${{ matrix.market }}-${{ github.run_id }}
          restore-keys: |
            formal-provider-1.1.0-${{ matrix.market }}-${{ steps.readiness.outputs.effective_seed_cutoff }}-
            formal-provider-1.0.0-${{ matrix.market }}-${{ steps.readiness.outputs.effective_seed_cutoff }}-
      - name: Prepare governed provider seed
        id: provider_seed
        if: steps.provider_cache.outputs.cache-hit != 'true' && steps.effective_cache.outputs.cache-hit != 'true'
        env:
          MARKET: ${{ matrix.market }}
        run: |
          restored="artifacts/formal-refresh/provider-${MARKET}"
          seed="artifacts/formal-refresh/provider-${MARKET}-seed"
          if [ -d "$restored/data/csv_source" ]; then
            python - <<'PY2'
          import json
          import os
          from pathlib import Path

          market = os.environ["MARKET"]
          root = Path(f"artifacts/formal-refresh/provider-{market}")
          manifest = json.loads(
              (root / "artifacts/selected_pool_price_refresh_manifest.json").read_text(
                  encoding="utf-8"
              )
          )
          receipt = json.loads(
              (root / "artifacts/formal-provider-cache-receipt.json").read_text(
                  encoding="utf-8"
              )
          )
          if manifest.get("status") != "selected_pool_price_refresh_ready":
              raise SystemExit("previous provider seed is not refresh ready")
          if manifest.get("promotion_eligible") is not True:
              raise SystemExit("previous provider seed is not promotion eligible")
          if receipt.get("evidence_type") != "formal_provider_cache_receipt":
              raise SystemExit("previous provider seed is not governed cache evidence")
          PY2
            rm -rf "$seed"
            mv "$restored" "$seed"
            echo "source_csv_dir=$seed/data/csv_source" >> "$GITHUB_OUTPUT"
            echo "seed_source=governed_cache" >> "$GITHUB_OUTPUT"
          else
            echo "source_csv_dir=data/csv_clean" >> "$GITHUB_OUTPUT"
            echo "seed_source=repository_bootstrap" >> "$GITHUB_OUTPUT"
          fi
      - name: Incrementally extend isolated selected-pool provider
        if: steps.provider_cache.outputs.cache-hit != 'true' && steps.effective_cache.outputs.cache-hit != 'true'
        env:
          MARKET: ${{ matrix.market }}
          EFFECTIVE_CUTOFF: ${{ steps.readiness.outputs.effective_cutoff }}
          SOURCE_CSV_DIR: ${{ steps.provider_seed.outputs.source_csv_dir }}
        run: |
          rm -rf "artifacts/formal-refresh/provider-${MARKET}"
          args=(
            --root .
            --market "$MARKET"
            --source-csv-dir "$SOURCE_CSV_DIR"
            --output-root "artifacts/formal-refresh/provider-${MARKET}"
            --start 2021-01-01
            --cutoff "$EFFECTIVE_CUTOFF"
            --max-rounds 3
          )
          while IFS= read -r symbol; do
            args+=(--auxiliary-symbol "$symbol")
          done < <(python - <<'PY2'
          import json
          import os
          from pathlib import Path

          market = os.environ["MARKET"]
          contract = json.loads(
              Path(f"artifacts/formal-refresh/provider-{market}-contract.json").read_text(
                  encoding="utf-8"
              )
          )
          for symbol in contract["auxiliary_symbols"]:
              print(symbol)
          PY2
          )
          timeout --signal=TERM --kill-after=30s 30m \\
            uv run python scripts/data/refresh_selected_pool_prices_v2.py "${args[@]}"
      - name: Seal fresh provider cache
        if: steps.provider_cache.outputs.cache-hit != 'true' && steps.effective_cache.outputs.cache-hit != 'true'
        env:
          MARKET: ${{ matrix.market }}
        run: |
          python -m scripts.govern_formal_provider_cache seal \\
            --provider-root "artifacts/formal-refresh/provider-${MARKET}" \\
            --contract "artifacts/formal-refresh/provider-${MARKET}-contract.json" \\
            --receipt "artifacts/formal-refresh/provider-${MARKET}/artifacts/formal-provider-cache-receipt.json"
      - name: Verify restored provider cache
        if: steps.provider_cache.outputs.cache-hit == 'true' || steps.effective_cache.outputs.cache-hit == 'true'
        env:
          MARKET: ${{ matrix.market }}
        run: |
          python -m scripts.govern_formal_provider_cache verify \\
            --provider-root "artifacts/formal-refresh/provider-${MARKET}" \\
            --contract "artifacts/formal-refresh/provider-${MARKET}-contract.json" \\
            --receipt "artifacts/formal-refresh/provider-${MARKET}/artifacts/formal-provider-cache-receipt.json"
      - name: Save exact governed provider cache
        if: steps.provider_cache.outputs.cache-hit != 'true' && steps.effective_cache.outputs.cache-hit != 'true'
        uses: actions/cache/save@v4
        with:
          path: artifacts/formal-refresh/provider-${{ matrix.market }}
          key: ${{ steps.contract.outputs.cache_key }}-governed
'''
text = text[:start] + replacement + text[end:]

old_env = '''          US_CUTOFF: ${{ needs.plan.outputs.us_cutoff }}
          CN_CUTOFF: ${{ needs.plan.outputs.cn_cutoff }}
'''
new_env = '''          US_CUTOFF: ${{ needs.plan.outputs.us_cutoff }}
          CN_CUTOFF: ${{ needs.plan.outputs.cn_cutoff }}
          EXPECTED_US_CUTOFF: ${{ needs.prepare.outputs.us_cutoff }}
          EXPECTED_CN_CUTOFF: ${{ needs.prepare.outputs.cn_cutoff }}
'''
if old_env not in text:
    raise SystemExit('publish status env marker not found')
text = text.replace(old_env, new_env, 1)

old_status = '''            const semanticNoChange = !failed && !publicationRequired;
            const status = failed ? 'blocked' : 'current';
'''
new_status = '''            const semanticNoChange = !failed && !publicationRequired;
            const providerDelayed = !failed && (
              (process.env.EXPECTED_US_CUTOFF && process.env.US_CUTOFF
                && process.env.US_CUTOFF < process.env.EXPECTED_US_CUTOFF)
              || (process.env.EXPECTED_CN_CUTOFF && process.env.CN_CUTOFF
                && process.env.CN_CUTOFF < process.env.EXPECTED_CN_CUTOFF)
            );
            const status = failed ? 'blocked' : providerDelayed ? 'delayed' : 'current';
'''
if old_status not in text:
    raise SystemExit('publish status marker not found')
text = text.replace(old_status, new_status, 1)

old_body = '''              `- **US common cutoff**: \\`${process.env.US_CUTOFF || 'unresolved'}\\``,
              `- **CN common cutoff**: \\`${process.env.CN_CUTOFF || 'unresolved'}\\``,
'''
new_body = '''              `- **US expected / provider cutoff**: \\`${process.env.EXPECTED_US_CUTOFF || 'unresolved'} / ${process.env.US_CUTOFF || 'unresolved'}\\``,
              `- **CN expected / provider cutoff**: \\`${process.env.EXPECTED_CN_CUTOFF || 'unresolved'} / ${process.env.CN_CUTOFF || 'unresolved'}\\``,
'''
if old_body not in text:
    raise SystemExit('status body cutoff marker not found')
text = text.replace(old_body, new_body, 1)

old_message = '''              failed
                ? 'The refresh failed closed before the governed publication transaction finished.'
                : semanticNoChange
                  ? 'The candidate publication was semantically identical to current evidence; review PR, candidate CI and Pages were intentionally skipped.'
                  : 'All active strategy receipts passed the Bundle v2 fan-in and the reviewed evidence transaction reached live Pages acceptance.',
'''
new_message = '''              failed
                ? 'The refresh failed closed before the governed publication transaction finished.'
                : providerDelayed
                  ? 'Governed provider evidence remains valid but trails the latest completed market session; publication did not move any strategy backwards.'
                  : semanticNoChange
                    ? 'The candidate publication was semantically identical to current evidence; review PR, candidate CI and Pages were intentionally skipped.'
                    : 'All active strategy receipts passed the Bundle v2 fan-in and the reviewed evidence transaction reached live Pages acceptance.',
'''
if old_message not in text:
    raise SystemExit('status message marker not found')
text = text.replace(old_message, new_message, 1)

diagnostics = '''      - name: Upload provider readiness evidence
        if: steps.provider_cache.outputs.cache-hit != 'true' && !cancelled()
        uses: actions/upload-artifact@v6
        with:
          name: formal-provider-readiness-${{ matrix.market }}-${{ github.run_id }}
          path: artifacts/formal-refresh/provider-${{ matrix.market }}-readiness.json
          overwrite: true
          if-no-files-found: warn
          retention-days: 7
          compression-level: 1
'''
marker = '      - name: Upload failed provider diagnostics\n'
idx = text.index(marker, text.index('  providers:\n'))
text = text[:idx] + diagnostics + text[idx:]

path.write_text(text, encoding='utf-8')
