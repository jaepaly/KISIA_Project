#!/usr/bin/env bash
# 로컬(git-bash)에서: 현재 HEAD 를 tar 로 묶어 서버에 올리고, 의존성·시딩·서비스·nginx 를 갱신한다.
#   apps/demo/deploy/deploy.sh ubuntu@IP ~/.ssh/veilo.pem [--reset]
# --reset : 글 데이터(sns.db)를 시딩 상태로 되돌린다 (첫 배포·리허설 전). 9/20 이후엔 코드 배포 자체를 하지 않는다.
set -euo pipefail
HOST="${1:?ubuntu@IP}"; KEY="${2:?pem path}"; RESET="${3:-}"
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
TGZ="$(mktemp -t veilo-XXXX).tgz"
cd "$ROOT"
git archive --format=tar.gz -o "$TGZ" HEAD apps/demo apps/sns src/kopl data/dict/admin data/corpus/v0
echo "archive: $(du -h "$TGZ" | cut -f1)"
S="ssh -i $KEY -o StrictHostKeyChecking=accept-new $HOST"
scp -i "$KEY" -o StrictHostKeyChecking=accept-new "$TGZ" "$HOST:/tmp/veilo.tgz"
$S "set -e
sudo rm -rf /srv/veilo/app.new && sudo mkdir -p /srv/veilo/app.new
sudo tar -xzf /tmp/veilo.tgz -C /srv/veilo/app.new
sudo rm -rf /srv/veilo/app.old; [ -d /srv/veilo/app ] && sudo mv /srv/veilo/app /srv/veilo/app.old
sudo mv /srv/veilo/app.new /srv/veilo/app
sudo chown -R veilo:veilo /srv/veilo/app
[ -f /srv/veilo/.env ] || sudo cp /srv/veilo/app/apps/demo/deploy/env.example /srv/veilo/.env
sudo chown veilo:veilo /srv/veilo/.env && sudo chmod 600 /srv/veilo/.env
sudo -u veilo /srv/veilo/venv/bin/pip install -q -r /srv/veilo/app/apps/sns/requirements.txt -r /srv/veilo/app/apps/demo/requirements.txt waitress
sudo cp /srv/veilo/app/apps/demo/deploy/veilo.service /srv/veilo/app/apps/demo/deploy/padopool.service /etc/systemd/system/
sudo cp /srv/veilo/app/apps/demo/deploy/nginx.conf /etc/nginx/sites-available/veilo
sudo ln -sf /etc/nginx/sites-available/veilo /etc/nginx/sites-enabled/veilo
sudo rm -f /etc/nginx/sites-enabled/default
sudo systemctl daemon-reload
if [ '$RESET' = '--reset' ] || [ ! -f /srv/veilo/data/sns.db ]; then
  sudo systemctl stop veilo padopool 2>/dev/null || true
  sudo -u veilo env \$(grep -v '^#' /srv/veilo/.env | xargs) PYTHONPATH=/srv/veilo/app/src /srv/veilo/venv/bin/python /srv/veilo/app/apps/demo/seed.py --reset
fi
sudo systemctl enable --now padopool veilo
sudo systemctl restart padopool veilo
sudo nginx -t && sudo systemctl reload nginx
sleep 2; curl -s -o /dev/null -w 'veilo http %{http_code}\n' http://127.0.0.1/ ; curl -s -o /dev/null -w 'padopool http %{http_code}\n' http://127.0.0.1:8000/
"
rm -f "$TGZ"
echo "deploy: 끝. 브라우저에서 http://<IP>/ (도메인 붙이면 certbot --nginx)"
