#!/usr/bin/env bash
# deploy/deploy.sh — 一鍵上線腳本（對應 deploy/launch-checklist.md §0–§5）
#
#   ./deploy/deploy.sh                    # 完整上線：前置檢查 → build → 遷移 → seed → 回填 → 重訓 → 驗證
#   ./deploy/deploy.sh --dry-run          # 只印出指令（前置檢查仍實際執行，唯讀）
#   ./deploy/deploy.sh --skip-backfill    # 跳過回填（已回填過的環境重跑）
#   ./deploy/deploy.sh --from 2015        # 指定回填起始年份（預設 2010）
#
# 設計原則：逐步 fail-fast（任一步失敗即中止）；可重複執行；不碰 .env／compose／volume。
set -euo pipefail

ENV_FILE=".env"
HKJC_URL="https://info.cld.hkjc.com/graphql/base/"
DISK_MIN_KIB=$((10 * 1024 * 1024)) # 10 GiB
PG_WAIT_SECS=90
HEALTH_WAIT_SECS=60
TOTAL_STEPS=13

DRY_RUN=0
SKIP_BACKFILL=0
BACKFILL_FROM=2010
PGUSER="football"
PGDB="football"

# ---------- 輸出工具 ----------
die() { printf '\n✗ %s\n' "$*" >&2; exit 1; }
warn() { printf '⚠ %s\n' "$*" >&2; }
info() { printf '  · %s\n' "$*"; }
step() { printf '\n[%s/%s] %s\n' "$1" "$TOTAL_STEPS" "$2"; }

# 執行（--dry-run 時只印出）
run() {
  printf '  $ %s\n' "$*"
  [[ $DRY_RUN -eq 1 ]] && return 0
  "$@"
}

usage() {
  cat <<'EOF'
用法: ./deploy/deploy.sh [選項]

選項:
  -h, --help        顯示本說明並結束
      --dry-run     只印出指令，不執行任何變更（前置檢查仍實際執行）
      --skip-backfill  跳過歷史回填（已回填過的環境重跑時使用）
      --from YEAR   回填起始年份，預設 2010（例：--from 2015）

需在 repo 根目錄執行，且 .env 內需有非空的 POSTGRES_PASSWORD 與 DATABASE_URL
（DATABASE_URL 的 host 必須是 compose 服務名 postgres）。
EOF
}

# 讀取 .env 的值（僅用於「驗證」，不輸出、不傳給 compose——compose 自己會讀 .env）
env_value() {
  local key="$1" line val
  [[ -f $ENV_FILE ]] || return 0
  line=$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$ENV_FILE" | tail -n1 || true)
  [[ -n $line ]] || return 0
  val="${line#*=}"
  val="${val%%#*}"                     # 去行尾註解
  val="${val%\"}"; val="${val#\"}"     # 去雙引號
  val="${val%\'}"; val="${val#\'}"     # 去單引號
  val="${val#"${val%%[![:space:]]*}"}" # trim 前導空白
  val="${val%"${val##*[![:space:]]}"}" # trim 尾隨空白
  printf '%s' "$val"
}

# ---------- 前置檢查 ----------
preflight() {
  # a) 必須在 repo 根目錄
  [[ -f docker-compose.yml && -f deploy/env.example ]] \
    || die "請在 repo 根目錄執行本腳本（找不到 docker-compose.yml / deploy/env.example）"

  # b) 必要指令
  for cmd in docker curl; do
    command -v "$cmd" >/dev/null || die "找不到指令 ${cmd}，請先安裝"
  done
  docker --version >/dev/null 2>&1 || die "docker 無法執行"
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 不可用（需 docker compose，非 docker-compose）"

  # c/d) .env 必需變數（一次列出所有問題）
  [[ -f $ENV_FILE ]] || die ".env 不存在：請執行 cp deploy/env.example .env 後填入 POSTGRES_PASSWORD 與 DATABASE_URL
    DATABASE_URL 的 host 必須是 compose 服務名 postgres（例如 postgresql+asyncpg://football:<密碼>@postgres:5432/football）"

  local problems=() dsn
  [[ -n $(env_value POSTGRES_PASSWORD) ]] || problems+=("缺少非空的 POSTGRES_PASSWORD")
  dsn=$(env_value DATABASE_URL)
  [[ -n $dsn ]] || problems+=("缺少非空的 DATABASE_URL")
  if [[ $dsn == *"@localhost"* || $dsn == *"@127.0.0.1"* ]]; then
    problems+=("DATABASE_URL 指向 localhost；在 compose 內 app 容器需用服務名 postgres 連線")
  fi
  if ((${#problems[@]} > 0)); then
    printf '\n✗ .env 設定不完整（%s）：\n' "$ENV_FILE" >&2
    printf '    - %s\n' "${problems[@]}" >&2
    die "請參考 deploy/env.example 修正 .env 後重跑（此檔不會被本腳本修改）"
  fi
  PGUSER="$(env_value POSTGRES_USER)"; PGUSER="${PGUSER:-football}"
  PGDB="$(env_value POSTGRES_DB)"; PGDB="${PGDB:-football}"

  # e) 資源
  local free_kib
  free_kib=$(df -Pk . | awk 'NR==2 {print $4}')
  (( free_kib >= DISK_MIN_KIB )) || die "磁碟可用空間不足 10 GiB（目前 $((free_kib / 1024 / 1024)) GiB）"
  local mem_bytes=0
  if [[ -r /proc/meminfo ]]; then
    mem_bytes=$(( $(awk '/^MemTotal:/ {print $2}' /proc/meminfo) * 1024 ))
  elif command -v sysctl >/dev/null; then
    mem_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
  fi
  (( mem_bytes == 0 || mem_bytes >= 2 * 1024 * 1024 * 1024 )) \
    || warn "記憶體 < 2 GiB（$((mem_bytes / 1024 / 1024)) MiB）：LightGBM 訓練可能吃緊"

  # f) HKJC 可達性（4xx 正常，timeout 才是問題）
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$HKJC_URL") \
    || die "HKJC 不可達（疑似 timeout／被擋）：請換出口 IP 或區域後重試（勿調小 HKJC_THROTTLE_SECONDS）"
  info "HKJC 可達（HTTP ${code}）"

  # g) .env 權限
  local mode
  mode=$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE" 2>/dev/null || echo "")
  if [[ -n $mode && $mode != "600" ]]; then
    if [[ $DRY_RUN -eq 1 ]]; then
      warn "$ENV_FILE 權限為 ${mode}（建議 600）：chmod 600 $ENV_FILE"
    else
      info "修正 $ENV_FILE 權限 ${mode} → 600"
      chmod 600 "$ENV_FILE"
    fi
  fi

  info "前置檢查通過（disk $((free_kib / 1024 / 1024)) GiB free, PG=$PGUSER/${PGDB}）"
}

# ---------- 等待 postgres 就緒 ----------
wait_for_postgres() {
  local cid status deadline=$((SECONDS + PG_WAIT_SECS))
  cid=$(docker compose ps -q postgres)
  [[ -n $cid ]] || die "找不到 postgres 容器（docker compose up -d postgres 是否成功？）"
  while (( SECONDS < deadline )); do
    status=$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || true)
    if [[ $status == "healthy" ]]; then
      info "postgres 就緒（healthcheck=healthy）"
      return 0
    fi
    if [[ -z $status ]] && docker compose exec -T postgres pg_isready -U "$PGUSER" -d "$PGDB" >/dev/null 2>&1; then
      info "postgres 就緒（pg_isready）"
      return 0
    fi
    sleep 3
  done
  die "postgres 在 ${PG_WAIT_SECS}s 內未就緒 → docker compose logs postgres | tail -30"
}

# ---------- 等待 app 健康 ----------
wait_for_health() {
  local body deadline=$((SECONDS + HEALTH_WAIT_SECS))
  while (( SECONDS < deadline )); do
    body=$(curl -s --max-time 5 localhost:8000/health 2>/dev/null || true)
    if [[ $body == *'"status":"ok"'* ]]; then
      info "app 健康檢查通過：${body}"
      return 0
    fi
    sleep 3
  done
  die "app 在 ${HEALTH_WAIT_SECS}s 內未通過健康檢查 → docker compose logs app | tail -30"
}

# ---------- 參數 ----------
while (( $# )); do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --skip-backfill) SKIP_BACKFILL=1; shift ;;
    --from)
      [[ -n ${2:-} && ${2:-} =~ ^[0-9]{4}$ ]] || die "--from 需要 4 位年份，例如 --from 2010"
      BACKFILL_FROM="$2"
      shift 2
      ;;
    --from=*)
      BACKFILL_FROM="${1#*=}"
      [[ $BACKFILL_FROM =~ ^[0-9]{4}$ ]] || die "--from 需要 4 位年份，例如 --from 2010"
      shift
      ;;
    *) usage >&2; die "未知參數：$1" ;;
  esac
done

# ---------- 主流程 ----------
if [[ $DRY_RUN -eq 1 ]]; then
  printf '世界盃分析 Agent — 上線腳本（dry-run：只印不執行）\n'
else
  printf '世界盃分析 Agent — 上線腳本\n'
fi

step 1 "前置檢查"
preflight

step 2 "建置映像（務必在目標主機上執行）"
run docker compose build

step 3 "啟動資料庫"
run docker compose up -d postgres

step 4 "等待 Postgres 就緒"
if [[ $DRY_RUN -eq 1 ]]; then
  printf '  $ （輪詢 postgres 就緒，最多 %ss）\n' "$PG_WAIT_SECS"
else
  wait_for_postgres
fi

step 5 "套用資料庫遷移（0001 → 0002_ml_tables → 0003_ledger_bets）"
run docker compose run --rm app alembic upgrade head

step 6 "種入白名單聯賽"
run docker compose run --rm app python -m app.cli seed-leagues

step 7 "啟動應用程式"
run docker compose up -d

step 8 "健康檢查"
if [[ $DRY_RUN -eq 1 ]]; then
  printf '  $ curl -s localhost:8000/health   # 輪詢至 {"status":"ok"}，最多 %ss\n' "$HEALTH_WAIT_SECS"
else
  wait_for_health
fi

if [[ $SKIP_BACKFILL -eq 1 ]]; then
  step "9" "歷史回填（--skip-backfill 已跳過）"
else
  step 9 "歷史回填（一次性，數分鐘）"
  run docker compose run --rm app python -m app.cli backfill --from "$BACKFILL_FROM"
fi

step 10 "訓練出第一個 champion（不必等排程的 7 天）"
run docker compose run --rm app python -m app.cli retrain

step 11 "驗證 champion 已就位"
if [[ $DRY_RUN -eq 1 ]]; then
  printf '  $ curl -s localhost:8000/models   # 需含 "champion"\n'
else
  models=$(curl -s --max-time 10 localhost:8000/models || true)
  [[ $models == *'"champion"'* ]] \
    || die "找不到 champion：ML_MIN_TRAIN_ROWS 可能過大、或回填筆數不足 → docker compose logs app | tail -30"
  info "champion 已就位"
fi

step 12 "首次預測"
run docker compose run --rm app python -m app.cli predict

step 13 "首次帳本（結算＋下注）"
run docker compose run --rm app python -m app.cli ledger

# ---------- 總結 ----------
printf '\n=== 完成 ===\n'
if [[ $DRY_RUN -eq 1 ]]; then
  printf '（dry-run 結束，未執行任何變更）\n'
  exit 0
fi
printf '帳本摘要：\n'
curl -s localhost:8000/bets/summary || true
printf '\n\n接下來會自動發生：\n'
printf '  +10 分鐘  首次賠率同步\n  +15 分鐘  首次賽果結算\n  +1 小時   首次預測與帳本更新\n  +7 天     首次自動重訓\n'
printf '\n維運提醒：\n'
printf '  · app 只可有一個 instance（docker compose ps）——APScheduler 在 process 內，多開會重複輪詢與重複入帳\n'
printf '  · 每日備份：docker compose exec postgres pg_dump -U %s %s > backup-$(date +%%F).sql\n' "$PGUSER" "$PGDB"
printf '  · 對外門面（Cloudflare Tunnel + Access）：見 deploy/cloudflare-tunnel.md\n'
