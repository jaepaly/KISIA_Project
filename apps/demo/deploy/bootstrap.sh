#!/usr/bin/env bash
# 서버에서 한 번 실행 (Ubuntu 24.04, sudo 가능한 계정). 이후 코드 갱신은 로컬에서 deploy.sh 만.
#   scp -i KEY.pem apps/demo/deploy/bootstrap.sh ubuntu@IP:~ && ssh -i KEY.pem ubuntu@IP 'bash bootstrap.sh'
set -euo pipefail
sudo apt-get update -q
sudo apt-get install -y -q python3 python3-venv python3-pip nginx
id veilo >/dev/null 2>&1 || sudo useradd -r -m -d /srv/veilo -s /usr/sbin/nologin veilo
sudo mkdir -p /srv/veilo/app /srv/veilo/data
sudo chown -R veilo:veilo /srv/veilo
sudo chmod 755 /srv/veilo
[ -f /srv/veilo/.env ] || { sudo cp /srv/veilo/app/apps/demo/deploy/env.example /srv/veilo/.env 2>/dev/null || true; }
sudo -u veilo python3 -m venv /srv/veilo/venv
echo "bootstrap: 시스템 준비 끝. 이제 로컬에서 deploy.sh 를 돌리면 코드·의존성·서비스가 올라간다."
