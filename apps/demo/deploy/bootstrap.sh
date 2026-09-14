#!/usr/bin/env bash
# 서버에서 한 번 실행. Amazon Linux 2023(dnf) 과 Ubuntu 24.04(apt) 둘 다 된다. 이후 코드 갱신은 로컬에서 deploy.sh 만.
#   scp -i KEY.pem apps/demo/deploy/bootstrap.sh ec2-user@IP:~ && ssh -i KEY.pem ec2-user@IP 'bash bootstrap.sh'
set -euo pipefail
if command -v dnf >/dev/null; then
  sudo dnf install -y -q python3.11 python3.11-pip nginx
  PY=python3.11
  # AL2023 의 nginx.conf 에는 80 을 듣는 기본 server 블록이 들어 있다 — 우리 conf.d 와 겹치지 않게 지운다
  sudo sed -i '/^    server {$/,/^    }$/d' /etc/nginx/nginx.conf
else
  sudo apt-get update -q
  sudo apt-get install -y -q python3 python3-venv python3-pip nginx
  PY=python3
fi
id veilo >/dev/null 2>&1 || sudo useradd -r -m -d /srv/veilo -s /sbin/nologin veilo
sudo mkdir -p /srv/veilo/app /srv/veilo/data
sudo chown -R veilo:veilo /srv/veilo
sudo chmod 755 /srv/veilo
sudo -u veilo $PY -m venv /srv/veilo/venv
sudo systemctl enable --now nginx
echo "bootstrap: 시스템 준비 끝 ($PY). 이제 로컬에서 deploy.sh 를 돌리면 코드·의존성·서비스가 올라간다."
