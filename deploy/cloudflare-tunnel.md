# Cloudflare Tunnel + Access（自架主機的對外門面）

目標：讓你家／機房的 Linux 主機在不開任何 firewall port、不用固定 IP 的前提下，提供一個
`https://wc.<你的網域>` 的 HTTPS 網址，並用 Zero Trust Access 加一道「只有你能進」的 email OTP 門禁。

```
訪客 ──HTTPS──▶ Cloudflare 邊緣（TLS/WAF）──▶ Access 驗證 ──▶ Tunnel ──▶ 你的主機 web:3000
                                                                          │（compose 網路，服務名互連）
                                                                          ▼
                                                                        app:8000 ──▶ Postgres
```

---

## 0. 前置：一個網域（Cloudflare 免費不提供網域本體）

- Tunnel 的公開網址必須是**你帳號中的一個 zone**。免費的 `*.pages.dev` / `*.workers.dev` 不能當 Tunnel hostname。
- 取得方式：在 Cloudflare Registrar **以成本價購買**（無加價，只付註冊局年費），或從其他註冊商**轉入**；
  接著把網域的 **Nameserver 指向 Cloudflare**（Dashboard → Add a site → 依指示到原註冊商改 NS）。
- DNS 代管、Universal SSL、Tunnel、Access 都是**免費**的。
- 若暫時不想買網域：可先跳過本文件，之後再回來；臨時測試可用文末的 Quick Tunnel。

## 1. 建 Tunnel 並拿 token

1. 登入 **Zero Trust**（`one.dash.cloudflare.com`）→ **Networks → Tunnels → Create a tunnel**。
2. Connector 選 **Cloudflared**，名稱例如 `worldcup` → Save。
3. 該頁會給安裝指令，把其中的 **token**（`--token` 後那串）複製起來。

## 2. 把 token 放進 `.env` 並啟動容器

```bash
# 在 repo 根目錄
printf 'TUNNEL_TOKEN=<paste-token-here>\nCOMPOSE_PROFILES=tunnel\n' >> .env
# 記得把 <paste-token-here> 換成 Zero Trust 給你的實際 token
docker compose up -d          # 因為 COMPOSE_PROFILES=tunnel，cloudflared 會一起起來
docker compose logs -f cloudflared   # 看到 "Registered tunnel connection" 即成功
```

（不想用 `COMPOSE_PROFILES` 的話，改用 `docker compose --profile tunnel up -d`。）

## 3. 設定公開網址（Public Hostname）

在該 Tunnel 頁面 → **Public Hostnames → Add a public hostname**：

| 欄位 | 值 |
|---|---|
| Subdomain | `wc` |
| Domain | `你的網域`（下拉選） |
| Service · Type | `HTTP` |
| Service · URL | `web:3000` |

> URL 用 `web:3000` 是因為 cloudflared 與 web 同屬 compose 網路，可用服務名互連；公開入口是
> dashboard 容器，它再從 compose 網路內部呼叫 `app:8000`。API 刻意不對外公開。
> 不需要 `http://` 前綴以外的東西，也不要在這裡填主機的對外 IP。

存檔後 Cloudflare 會自動建立一筆 DNS 記錄。等 1–2 分鐘，`https://wc.你的網域/` 應該可以連到 dashboard。

## 4. 加一道 Access 門禁（email OTP）

1. Zero Trust → **Access → Applications → Add an application → Self-hosted**。
2. Name：`WorldCup`；Session Duration 隨意（例如 24h）。
3. Public hostname：`wc` / `你的網域`（就是第 3 步那個）。
4. **Policies** → Add a policy：Action = `Allow`；Include → Selector `Emails` → 你的 email。
5. Save。（登入方式：Zero Trust → Settings → Authentication，預設可用 **One-time PIN** 寄 OTP，也可接 Google/GitHub。）

之後任何人連 `https://wc.你的網域` 都會先看到 Cloudflare 登入頁，通過才進到你的 dashboard。
**不需要自己寫任何登入程式碼。**

驗證：`curl -sI https://wc.你的網域/` 應回傳 302 導向 Cloudflare Access 登入（代表門禁生效）；
用瀏覽器登入後應看到 dashboard。

## 5. 機器對機器呼叫（非 dashboard）：Service Token

> **已作廢（dashboard 部分）**：子系統 D 現在是 compose 服務（`web`），在伺服器端呼叫 API
> （`http://app:8000`），瀏覽器從不直接打 API。因此 dashboard **不需要** Service Token，也**不需要**
> CORS；FastAPI 應用程式**永遠不會**為了 CORS 被修改。原本「部署在 Cloudflare Pages + Service Token + CORS」
> 的計畫已由 compose 服務取代。

本節僅保留給**非 dashboard** 的機器對機器呼叫者（例如 cron、外部腳本）：

1. Zero Trust → Access → **Service Auth → Create Service Token**（例如 `worldcup-cron`）→ 複製 `Client ID` / `Client Secret`（只顯示一次）。
2. 回到該 Application 的 Policy，加一條 `Include → Service Token → worldcup-cron`（或另建 policy）。
3. 呼叫端帶上 header：
   `CF-Access-Client-Id: <id>`、`CF-Access-Client-Secret: <secret>`。

## 6. 注意事項

- **API 不再對外公開**：公開入口是 dashboard（`web:3000`），API 只在 compose 網路內（`app:8000`）與主機本機（`127.0.0.1:8000`）可達。這是刻意的，順帶關掉了先前唯讀 `/ops/*` 端點的對外暴露。
- **不要對 API 開快取**：Cloudflare 預設只快取靜態資源；不要為 `wc.你的網域` 建 Cache Rules 去快取 `/predictions`、`/bets` 這類動態 JSON。
- **本機直連不受影響**：compose 把 app 綁在 `127.0.0.1:8000`，主機上仍可直接 `curl localhost:8000/health`（繞過 Access，適合自己在機器上維運）。
- **`web` 不發布任何主機埠**：dashboard 只透過 compose 網路被 cloudflared 存取，主機上沒有對外 port。
- Cloudflare 掛掉時外部連不到（內網／localhost 不受影響）。
- 換 token／改網域後：`docker compose up -d cloudflared`（重啟該容器）。

## 7. 臨時測試（沒有網域也能用）

不需要 Access、網址是隨機的 `*.trycloudflare.com`，每次重啟就換：

```bash
# 看 dashboard（公開入口）
docker compose run --rm cloudflared tunnel --no-autoupdate --url http://web:3000

# 直接看 API（除錯用；正常對外不該這樣開）
docker compose run --rm cloudflared tunnel --no-autoupdate --url http://app:8000
```

僅供「臨時從外網看一眼」，不要當成長期方案（無固定網址、無門禁）。

---

## 疑難排解

| 症狀 | 檢查 |
|---|---|
| `cloudflared` 一直重啟 | `docker compose logs cloudflared`；多半是 `TUNNEL_TOKEN` 錯／過期，或 tunnel 已被刪 |
| 網站 502 / 1033 | Public Hostname 的 Service URL 不是 `web:3000`，或 web 容器不健康（`docker compose ps`）；若 dashboard 起得來但顯示 API 錯誤，改查 app 的健康（`curl localhost:8000/health`） |
| 一直跳 Access 登入 | 正常；檢查 Policy 的 email 是否正確，或改用 Service Token |
| DNS 沒生效 | 等幾分鐘；確認網域 NS 已指向 Cloudflare |
