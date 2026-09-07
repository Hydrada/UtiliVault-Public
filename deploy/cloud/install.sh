#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo deploy/cloud/install.sh"
  exit 1
fi

install -d -m 0755 /opt/utilivault /var/lib/utilivault
install -d -m 0700 /etc/utilivault /etc/utilivault/secrets
chown -R 10001:10001 /var/lib/utilivault /etc/utilivault/secrets

install -m 0644 deploy/cloud/utilivault-watcher.service /etc/systemd/system/
install -m 0644 deploy/cloud/utilivault-watcher.timer /etc/systemd/system/
install -m 0644 deploy/cloud/utilivault-monitor.service /etc/systemd/system/
install -m 0644 deploy/cloud/utilivault-monitor.timer /etc/systemd/system/

if [ ! -f /etc/utilivault/runtime.env ]; then
  install -m 0600 deploy/cloud/runtime.env.example /etc/utilivault/runtime.env
fi

systemctl daemon-reload
echo "Installed but not enabled. Complete deploy/cloud/RUNBOOK.md before starting a timer."

