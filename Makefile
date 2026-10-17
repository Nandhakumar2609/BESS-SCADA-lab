# BESS SCADA lab - common tasks.  `make help` lists everything.
SHELL := /bin/bash
MODE ?= segmented
COMPOSE_FILE := $(if $(filter simple,$(MODE)),docker-compose.simple.yml,docker-compose.yml)
DC := docker compose -f $(COMPOSE_FILE)
PY ?= python3
export BESS_COMPOSE := $(COMPOSE_FILE)

.PHONY: help init demo up down logs ps fat test netlab local cli check dashboards render \
        backup restore baseline drift vpn deploy clean

help:  ## show this help
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-11s\033[0m %s\n", $$1, $$2}'
	@echo "  MODE=simple|segmented (default segmented) selects the compose file"

.env:
	@$(PY) -c "import secrets;t=lambda n:secrets.token_urlsafe(n);open('.env','w').write(\
	'SIM_SPEED=20\nINFLUX_ADMIN_PASSWORD=%s\nINFLUX_ADMIN_TOKEN=%s\nGRAFANA_ADMIN_PASSWORD=%s\nGRAFANA_ANONYMOUS_VIEWER=false\n'%(t(18),t(36),t(15)))"
	@chmod 600 .env && echo "created .env with random secrets (Grafana admin password inside)"

init: .env  ## create .env with random passwords/tokens
	@mkdir -p reports backups

demo: init  ## quick flat demo on any Docker host -> http://localhost:3000
	GRAFANA_ANONYMOUS_VIEWER=true docker compose -f docker-compose.simple.yml up -d --build
	@echo; echo "HMI: http://localhost:3000  (anonymous viewer on; admin password in .env)"

up: init  ## full segmented OT network with firewall + VPN (Linux, Docker Engine 28+)
	$(DC) up -d --build
	@echo; echo "HMI: http://localhost:3000 (via firewall DNAT). Admin password: see .env"

down:  ## stop the stack (keeps data volumes)
	$(DC) down

ps:  ## container status
	$(DC) ps

logs:  ## follow gateway + firewall logs
	$(DC) logs -f --tail=50 gateway $(if $(filter simple,$(MODE)),,fw)

fat:  ## run the automated FAT inside the control zone -> reports/
	$(DC) exec gateway python -m bess_lab.fat --out /app/reports

cli:  ## commissioning CLI, e.g. make cli ARGS="dump pcs01"
	$(DC) exec gateway python -m bess_lab.cli $(ARGS)

test:  ## unit + integration tests (no Docker needed)
	$(PY) -m pytest -q

netlab:  ## namespace network lab: zones, firewall, NAT, spoofing tests (needs root)
	sudo PYTHON=$(PY) lab/netns-lab.sh all

local:  ## run simulator + gateway on this machine, printing line protocol
	@trap 'kill 0' EXIT; $(PY) -m bess_lab.sim.server --local --speed 20 & sleep 2; \
	  $(PY) -m bess_lab.gateway.main --local --sink stdout

check:  ## static checks: rendered configs up to date, nft syntax, ansible syntax, tests
	$(PY) tools/render_configs.py --check
	@if command -v nft >/dev/null && [ $$(id -u) -eq 0 ]; then ip netns add bess-chk && ip netns exec bess-chk nft -c -f network/nftables/fw.nft && ip netns del bess-chk && echo "nft syntax OK"; fi
	cd ansible && ansible-playbook site.yml --syntax-check
	$(PY) -m pytest -q

dashboards:  ## regenerate Grafana dashboards from tools/build_dashboards.py
	$(PY) tools/build_dashboards.py

render:  ## regenerate network/nftables/fw.nft from ansible/group_vars/all.yml
	$(PY) tools/render_configs.py

backup:  ## historian + HMI + config backup -> backups/
	scripts/backup.sh

restore:  ## make restore FILE=backups/bess-backup_xxx.tar.gz
	scripts/restore.sh $(FILE)

baseline:  ## capture configuration baseline
	scripts/baseline.sh capture

drift:  ## compare running configuration with the baseline
	scripts/baseline.sh check

vpn:  ## generate WireGuard configs: make vpn ENDPOINT=<public ip>
	scripts/wg-genkeys.sh $(ENDPOINT)
	-$(DC) restart fw

deploy:  ## full deployment with Ansible onto the inventory host
	cd ansible && ansible-galaxy collection install -r requirements.yml && ansible-playbook site.yml

clean:  ## stop and DELETE all data volumes
	$(DC) down -v
