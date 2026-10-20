#!/usr/bin/env bash
# Chạy Texa trên local: Postgres + Airflow (Docker), API (uvicorn), Web (Vite).
# Ctrl-C (hoặc đóng script) sẽ tắt toàn bộ dịch vụ.
set -euo pipefail
cd "$(dirname "$0")"

PIDFILE=.run.pid

# Chỉ cho 1 bản chạy: nếu bản cũ còn sống thì tắt nó (để nó tự dọn dẹp) rồi mới chạy bản mới.
# ponytail: không khoá chống 2 bản khởi động cùng một giây; thêm flock/mkdir-lock nếu cần.
old=$(cat "$PIDFILE" 2>/dev/null || true)
if [ -n "$old" ] && ps -p "$old" -o command= 2>/dev/null | grep -q run.sh; then
  echo "==> Đang tắt bản run.sh cũ (PID $old)..."
  kill "$old"
  for _ in $(seq 60); do kill -0 "$old" 2>/dev/null || break; sleep 1; done
  kill -0 "$old" 2>/dev/null && { echo "!! Bản cũ không tắt sau 60s, buộc dừng."; kill -9 "$old"; }
fi
echo $$ > "$PIDFILE"

[ -f .env ] || cp .env.example .env
set -a; source .env; set +a

cleanup() {
  trap - EXIT INT TERM
  echo; echo "==> Đang tắt dịch vụ..."
  kill $(jobs -p) 2>/dev/null || true
  wait 2>/dev/null || true
  docker info >/dev/null 2>&1 && docker compose stop postgres airflow
  [ "$(cat "$PIDFILE" 2>/dev/null)" = "$$" ] && rm -f "$PIDFILE"
  echo "==> Đã tắt."
}
trap cleanup EXIT INT TERM

if ! docker info >/dev/null 2>&1; then
  echo "==> Docker chưa chạy, đang mở Docker Desktop..."
  open -a Docker
  for _ in $(seq 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
  docker info >/dev/null 2>&1 || { echo "!! Docker không lên sau 2 phút."; exit 1; }
fi

echo "==> Khởi động Postgres + Airflow"
docker compose up -d --wait postgres
docker compose up -d airflow

echo "==> Backend: uv sync + publish catalog"
(cd backend && uv sync -q)
# ponytail: publish lỗi khi chưa nạp dữ liệu (xem README bước 1) — chỉ cảnh báo, không dừng
(cd backend && uv run texa catalog publish) || echo "!! Publish catalog lỗi — đã nạp dữ liệu chưa?"

# Doanh thu quy USD cần bảng tỷ giá + nạp lại cửa hàng (một lần, xem README bước 1). Chỉ nhắc, không tự chạy.
fx=$(docker compose exec -T postgres psql -U texa -d texa -tAc \
  "SELECT (SELECT count(*) FROM analytics.fx_rates) || ' ' || count(revenue_usd) FROM analytics.event_activity" 2>/dev/null || echo "0 0")
if [ "${fx% *}" = "0" ] || [ "${fx#* }" = "0" ]; then
  echo "!! Chưa có doanh thu quy USD. Chạy một lần:"
  echo "   cd pipeline && uv run --python 3.12 --with 'psycopg[binary]' python -m texa_etl.run fx_rates"
  echo "   rồi với từng cửa hàng: python -m texa_etl.run <olist_marketplace|cosmetics_shop> load_mart refresh_metadata"
fi

[ -d web/node_modules ] || (cd web && npm install)

echo "==> Chạy API :18000 và Web :15173"
(cd backend && exec uv run uvicorn texa.main:app --port 18000) &
(cd web && exec npm run dev) &

cat <<EOF

  Web:     http://localhost:15173
  API:     http://localhost:18000
  Airflow: http://localhost:18080  (mật khẩu: docker compose logs airflow | grep password)

  Nhấn Ctrl-C để tắt tất cả.
EOF

# bash 3.2 (macOS) không có `wait -n`: một tiến trình chết → thoát và dọn dẹp
while [ "$(jobs -rp | wc -l)" -eq 2 ]; do sleep 2; done
echo "!! API hoặc Web đã dừng."
