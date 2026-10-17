#!/usr/bin/env python3
"""Render network/nftables/fw.nft from ansible/group_vars/all.yml without running Ansible.

Ansible uses the same template (roles/bess_stack/templates/fw.nft.j2), so the committed
file and an Ansible deployment can never drift apart.
    python tools/render_configs.py          # write
    python tools/render_configs.py --check  # exit 1 if the committed file is out of date (CI)
"""
import sys
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parent.parent
VARS = yaml.safe_load((ROOT / "ansible/group_vars/all.yml").read_text())
TEMPLATES = {
    ROOT / "ansible/roles/bess_stack/templates/fw.nft.j2": ROOT / "network/nftables/fw.nft",
}

env = jinja2.Environment(undefined=jinja2.StrictUndefined, trim_blocks=True, lstrip_blocks=False,
                         keep_trailing_newline=True)
stale = False
for src, dst in TEMPLATES.items():
    text = env.from_string(src.read_text()).render(**VARS)
    if "--check" in sys.argv:
        if not dst.exists() or dst.read_text() != text:
            print(f"OUT OF DATE: {dst.relative_to(ROOT)}")
            stale = True
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text)
        print(f"rendered {dst.relative_to(ROOT)}")
sys.exit(1 if stale else 0)
