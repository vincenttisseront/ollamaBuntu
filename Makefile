.PHONY: lint i18n i18n-check test test-ui bundle

lint:
	# SC2319 exclu : les tests écrivent « [ condition ]; ok $$? » à dessein (le code de retour de la condition)
	shellcheck -S warning -e SC2034,SC2154,SC2319 build.sh lib/*.sh src/installer/*.sh src/rootfs/usr/local/sbin/ollamabuntu-update src/rootfs/usr/local/lib/ollamabuntu/rollback.sh tests/unit/*.sh

I18N = python3 tools/i18n/build_catalog.py

i18n:
	$(I18N)

i18n-check:
	$(I18N) --check

test:
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/router_balance_test.py
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/gpu_auto_test.py
	bash tests/unit/crypt_engine_test.sh
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/online_update_test.py
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/hf_test.py
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/limits_test.py
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/monitor_test.py
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/admin_features_test.py
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/backup_test.py
	bash tests/unit/rollback_test.sh
	bash tests/unit/host_docker_test.sh
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/router_limits_test.py
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/router_expiry_test.py
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/batch2_test.py
	bash tests/unit/gpu_ready_test.sh
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/gpu_guard_test.py
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/perf_test.py
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/router_batch3_test.py
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/ops3_test.py
	PYTHONDONTWRITEBYTECODE=1 python3 tests/unit/catalog_sources_test.py

# Console web (jsdom requis : npm install --no-save jsdom@24)
test-ui:
	node tests/unit/online_update_ui_test.js
	node tests/unit/ops_ui_test.js
	node tests/unit/batch2_ui_test.js
	node tests/unit/batch3_ui_test.js

# Archive de mise à jour en ligne (OB_VERSION=AAAA.MM.JJ-HHMM, OB_SIGNING_KEY=clé privée pour signer)
bundle:
	./build.sh --bundle
