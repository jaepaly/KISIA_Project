#!/usr/bin/env bash
# 서버에서 한 번 실행. Amazon Linux 2023(dnf) 과 Ubuntu 24.04(apt) 둘 다 된다. 이후 코드 갱신은 로컬에서 deploy.sh 만.
#   scp -i KEY.pem apps/demo/deploy/bootstrap.sh ec2-user@IP:~ && ssh -i KEY.pem ec2-user@IP 'bash bootstrap.sh'
set -euo pipefail
if command -v dnf >/dev/null; then
  sudo dnf install -y -q python3.11 python3.11-pip nginx certbot python3-certbot-nginx
  PY=python3.11
  # AL2023 의 nginx.conf 에는 80 을 듣는 기본 server 블록이 들어 있다 — 우리 conf.d 와 겹치지 않게 지운다
  sudo sed -i '/^    server {$/,/^    }$/d' /etc/nginx/nginx.conf
else
  sudo apt-get update -q
  sudo apt-get install -y -q python3 python3-venv python3-pip nginx certbot python3-certbot-nginx
  PY=python3
fi
id veilo >/dev/null 2>&1 || sudo useradd -r -m -d /srv/veilo -s /sbin/nologin veilo
sudo mkdir -p /srv/veilo/app /srv/veilo/data
sudo chown -R veilo:veilo /srv/veilo
sudo chmod 755 /srv/veilo
sudo -u veilo $PY -m venv /srv/veilo/venv
sudo timedatectl set-timezone Asia/Seoul || true
# 스왑 2G — 1GB VPS 에서 두 프로세스 + 인구표가 동시에 커질 때 OOM 으로 죽지 않게
if [ ! -f /swapfile ]; then
  sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
  sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi
sudo systemctl enable --now nginx
echo "bootstrap: 인증서는 DNS(veilo.site A 레코드)가 이 서버를 가리킨 뒤에:"
echo "  sudo certbot --nginx -d veilo.site -d www.veilo.site --redirect --agree-tos -m <메일> --non-interactive"
echo "bootstrap: 시스템 준비 끝 ($PY). 이제 로컬에서 deploy.sh 를 돌리면 코드·의존성·서비스가 올라간다."
