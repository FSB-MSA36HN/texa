#!/usr/bin/env bash
# Chạy Texa local; Ctrl-C/TERM/HUP/thoát lỗi sẽ dừng process và container đi kèm.
# ./run.sh stop dừng Texa mà không xóa container, image, volume hoặc build cache.
set -euo pipefail
cd "$(dirname "$0")"
TEXA_ROOT=$(pwd -P)
PIDFILE=.run.pid

case "${1:-start}" in
  start|stop) action=${1:-start} ;;
  -h|--help) echo "Dùng: ./run.sh [start|stop]"; exit 0 ;;
  *) echo "Dùng: ./run.sh [start|stop]" >&2; exit 2 ;;
esac
[ "$#" -le 1 ] || { echo "Chỉ nhận một lệnh start hoặc stop." >&2; exit 2; }

# Pin đúng compose file; không phụ thuộc COMPOSE_FILE hoặc thư mục gọi script.
texa_compose() {
  docker compose --project-directory "$TEXA_ROOT" -f "$TEXA_ROOT/docker-compose.yml" --profile '*' "$@"
}

stop_containers() {
  if ! docker info >/dev/null 2>&1; then
    echo "!! Không kết nối được Docker để xác nhận trạng thái; không tự mở Docker khi dừng." >&2
    return 1
  fi
  # Không liệt kê riêng postgres/airflow: bao gồm api/web và mọi profile của Texa.
  texa_compose stop --timeout 10 || return 1
  # compose ps gồm cả orphan containers của cùng project. stop giữ nguyên mọi
  # container/image/volume, kể cả writable layer của Airflow để khởi động lại nhanh.
  local ids
  ids=$(texa_compose ps --all --quiet) || return 1
  if [ -n "$ids" ]; then
    docker stop --time 10 $ids >/dev/null || return 1
  fi
}

stop_existing() {
  local old command cwd_record i
  old=$(cat "$PIDFILE" 2>/dev/null || true)
  case "$old" in ''|*[!0-9]*) return 0 ;; esac
  command=$(ps -p "$old" -o command= 2>/dev/null || true)
  case "$command" in *run.sh*) ;; *) return 0 ;; esac
  # PID có thể đã được tái sử dụng bởi run.sh của project khác.
  if command -v lsof >/dev/null 2>&1; then
    # Đọc hết output trước khi kiểm tra để tránh SIGPIPE từ grep -q + pipefail.
    cwd_record=$(lsof -a -p "$old" -d cwd -Fn 2>/dev/null || true)
    if ! grep -Fxq "n$TEXA_ROOT" <<< "$cwd_record"; then
      kill -0 "$old" 2>/dev/null || return 0  # Process có thể vừa thoát.
      echo "!! Bỏ qua PID cũ không thuộc thư mục Texa; không gửi signal cho process đó." >&2
      return 0
    fi
  fi
  echo "==> Đang dừng Texa (PID $old)..."
  kill -TERM "$old" 2>/dev/null || true
  for i in $(seq 45); do
    kill -0 "$old" 2>/dev/null || return 0
    sleep 1
  done
  echo "!! Script cũ chưa thoát; buộc dừng trước khi kiểm tra container."
  kill -KILL "$old" 2>/dev/null || true
}

if [ "$action" = stop ]; then
  stop_existing
  stop_containers
  rm -f "$PIDFILE"
  echo "==> Texa đã dừng; giữ nguyên container, image và dữ liệu."
  exit 0
fi

stop_existing
echo $$ > "$PIDFILE"
# Mỗi background job có process group riêng để npm/uv và các process con cùng dừng.
set -m
cleanup() {
  local status=$? pid groups i alive
  trap - EXIT INT TERM HUP
  set +e
  echo; echo "==> Đang tắt Texa và các container đi kèm..."
  groups=$(jobs -pr)
  for pid in $groups; do kill -TERM -- "-$pid" 2>/dev/null; done
  for i in $(seq 10); do
    alive=false
    for pid in $groups; do kill -0 -- "-$pid" 2>/dev/null && alive=true; done
    [ "$alive" = false ] && break
    sleep 1
  done
  for pid in $groups; do kill -KILL -- "-$pid" 2>/dev/null; done
  wait 2>/dev/null
  if ! stop_containers; then
    echo "!! Chưa xác nhận dừng hết container. Chạy lại: ./run.sh stop" >&2
    status=1
  fi
  [ "$(cat "$PIDFILE" 2>/dev/null)" = "$$" ] && rm -f "$PIDFILE"
  echo "==> Đã kết thúc; giữ nguyên image, container và volume."
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

# wait là builtin nên signal được xử lý ngay cả trong bước khởi động dài.
run_task() {
  local directory=$1 task_pid
  shift
  (cd "$directory" && exec "$@") &
  task_pid=$!
  wait "$task_pid"
}

[ -f .env ] || cp .env.example .env
set -a; source .env; set +a

if ! docker info >/dev/null 2>&1; then
  echo "==> Docker chưa chạy, đang mở Docker Desktop..."
  open -a Docker
  for _ in $(seq 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
  docker info >/dev/null 2>&1 || { echo "!! Docker không lên sau 2 phút."; exit 1; }
fi

echo "==> Khởi động Postgres + Airflow"
run_task . docker compose --project-directory "$TEXA_ROOT" -f "$TEXA_ROOT/docker-compose.yml" up -d --wait postgres
run_task . docker compose --project-directory "$TEXA_ROOT" -f "$TEXA_ROOT/docker-compose.yml" up -d airflow

echo "==> Backend: uv sync + publish catalog"
run_task backend uv sync -q
# ponytail: publish lỗi khi chưa nạp dữ liệu (xem README bước 1) — chỉ cảnh báo, không dừng
run_task backend uv run texa catalog publish || echo "!! Publish catalog lỗi — đã nạp dữ liệu chưa?"

# Doanh thu quy USD cần bảng tỷ giá + nạp lại cửa hàng (một lần, xem README bước 1). Chỉ nhắc, không tự chạy.
fx=$(texa_compose exec -T postgres psql -U texa -d texa -tAc \
  "SELECT (SELECT count(*) FROM analytics.fx_rates) || ' ' || count(revenue_usd) FROM analytics.event_activity" 2>/dev/null || echo "0 0")
if [ "${fx% *}" = "0" ] || [ "${fx#* }" = "0" ]; then
  echo "!! Chưa có doanh thu quy USD. Chạy một lần:"
  echo "   cd pipeline && uv run --python 3.12 --with 'psycopg[binary]' python -m texa_etl.run fx_rates"
  echo "   rồi với từng cửa hàng: python -m texa_etl.run <olist_marketplace|cosmetics_shop> load_mart refresh_metadata"
fi

[ -d web/node_modules ] || run_task web npm install

echo "==> Chạy API :18000 và Web :15173"
(cd backend && exec uv run uvicorn texa.main:app --port 18000) &
(cd web && exec npm run dev) &

cat <<EOF

  Web:     http://localhost:15173
  API:     http://localhost:18000
  Airflow: http://localhost:18080  (mật khẩu: docker compose logs airflow | grep password)

  Nhấn Ctrl-C để tắt Texa và toàn bộ container của nó.
  Hoặc từ terminal khác: ./run.sh stop
EOF

# bash 3.2 (macOS) không có `wait -n`: một tiến trình chết → thoát và dọn dẹp
while [ "$(jobs -rp | wc -l)" -eq 2 ]; do sleep 2; done
echo "!! API hoặc Web đã dừng."
exit 1
