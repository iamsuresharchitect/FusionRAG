# Hybrid RAG with Claude — deploy to Hostinger VPS

Upload PDFs/DOCX/TXT/MD/CSV, ask questions, get answers from **Claude (Anthropic API)** with numbered citations.

**Why "hybrid"?** Every question runs two searches and merges them:

| Retriever | Good at | Implementation |
|---|---|---|
| Vector (semantic) | Meaning, paraphrases ("backup failed" ≈ "job did not complete") | `fastembed` + `BAAI/bge-small-en-v1.5`, runs on CPU, no extra API key |
| BM25 (keyword) | Exact terms: error codes, hostnames, KB numbers (`19:1131`, `AHV`) | Built-in Okapi BM25 |
| Fusion | Best of both | Reciprocal Rank Fusion (RRF, k=60) |

The top passages go to Claude, which answers only from them. The UI lets you switch **Hybrid / Vector / Keyword** to compare, and shows each source's vector rank, BM25 rank and RRF score.

```
Browser ─► Nginx :443 ─┬─ /      ─► frontend container (React, nginx)  :3000
                       └─ /api/* ─► backend container  (FastAPI)       :8000 ─► Claude API
                                          │
                                          └─ Docker volume rag-data (index persists)
```

## Project layout (matches the guide, Step 1)

```
hybrid-rag/
├── backend/
│   ├── app/            config.py · ingest.py (parse+chunk) · store.py (hybrid index) · llm.py (Claude)
│   ├── main.py         FastAPI routes: /health /config /documents /search /chat (SSE streaming)
│   ├── requirements.txt
│   ├── Dockerfile      Step 2 (also bakes the embedding model into the image)
│   ├── .dockerignore   Step 4
│   └── .env.example    copy to .env  ← secrets, never pushed
├── frontend/
│   ├── src/            React (Vite) chat UI
│   ├── nginx.conf      Step 3 (+ /api proxy so localhost:3000 works end to end)
│   ├── Dockerfile      Step 3 multi-stage build
│   └── .dockerignore   Step 4
├── deploy/
│   ├── nginx-site.conf Step 16 host Nginx config (with upload size + streaming fixes)
│   ├── setup-vps.sh    Steps 8–9 + Nginx/Certbot/ufw/swap in one script
│   └── redeploy.sh     Part 3 redeploy loop
├── docker-compose.yml  Step 5
└── .gitignore          Step 7
```

## Part 1 — on your laptop

```bash
cd hybrid-rag
cp backend/.env.example backend/.env       # then edit: ANTHROPIC_API_KEY, ADMIN_TOKEN
cd frontend && npm install && cd ..        # creates package-lock.json (commit it)
docker compose up --build                  # Step 6
```
- http://localhost:3000 → the app (upload a file, ask a question)
- http://localhost:8000/docs → FastAPI docs

Push to GitHub (Step 7): `git init && git add . && git status` — **`backend/.env` must NOT appear** — then commit and push.

## Part 2 — on the Hostinger VPS

Hostinger: choose **KVM 1 or higher** with the **Ubuntu 24.04** template. hPanel shows the IP and root password.

```bash
ssh root@YOUR_VPS_IP                                   # Step 8
git clone https://github.com/USERNAME/hybrid-rag.git   # Step 11 (use your PAT as password if private)
cd hybrid-rag
sudo bash deploy/setup-vps.sh                          # Step 9 + Nginx, Certbot, ufw, swap
exit                                                   # log out/in for the docker group
ssh root@YOUR_VPS_IP && cd hybrid-rag

nano backend/.env                                      # recreate secrets (copy from .env.example)
docker compose up --build -d                           # Step 12 (first build ~5–8 min)
docker ps                                              # Step 13: both "Up"
```
Test http://YOUR_VPS_IP:3000 before DNS. If it doesn't load, check **hPanel → VPS → Firewall**.

**DNS (Steps 14–15)** — hPanel → Domains → DNS / Nameservers → DNS records: delete the default parking A records, add `A @ → VPS_IP` and `A www → VPS_IP`. Check on dnschecker.org.

**Nginx (Steps 16–17)**
```bash
sudo cp deploy/nginx-site.conf /etc/nginx/sites-available/yourdomain.com
sudo sed -i 's/yourdomain.com/YOUR-REAL-DOMAIN/g' /etc/nginx/sites-available/yourdomain.com
sudo ln -s /etc/nginx/sites-available/yourdomain.com /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

**SSL (Step 18)**
```bash
sudo certbot --nginx -d YOUR-REAL-DOMAIN -d www.YOUR-REAL-DOMAIN    # choose Redirect
sudo certbot renew --dry-run
```

**Lock the ports (recommended once HTTPS works).** Docker-published ports bypass `ufw`, so close 3000/8000 to the internet:
```bash
echo "BIND_IP=127.0.0.1" > .env        # root .env, read by docker compose
docker compose up -d                   # now only Nginx can reach the containers
```

## Redeploy after changes
Laptop: `git add . && git commit -m "..." && git push` → VPS: `bash deploy/redeploy.sh`.
Your indexed documents live in the `rag-data` volume and survive redeploys (`docker compose down -v` deletes them).

## Configuration (`backend/.env`)

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required. console.anthropic.com → API Keys |
| `CLAUDE_MODEL` | `claude-sonnet-5-5` | `claude-haiku-5-5` cheaper/faster, `claude-opus-5-5` strongest |
| `ADMIN_TOKEN` | empty | When set, upload/delete need it (UI asks once). Chat stays open |
| `TOP_K` | 6 | Passages sent to Claude (adjustable in the UI) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 1000 / 150 | Characters |
| `MAX_UPLOAD_MB` | 25 | Keep in sync with `client_max_body_size` in both Nginx files |

## API
| Method | Path (via Nginx add `/api`) | Purpose |
|---|---|---|
| GET | `/health` | Status, doc/chunk counts |
| GET | `/documents` | List indexed docs |
| POST | `/documents` | Upload (multipart `files`, header `X-Admin-Token`) |
| DELETE | `/documents/{id}` | Remove a doc |
| POST | `/search` | Retrieval only `{query, mode, top_k}` |
| POST | `/chat` | `{question, history, mode, top_k}` → SSE: `sources`, `token`, `error`, `done` |

## Troubleshooting (in addition to the guide's table)
| Symptom | Fix |
|---|---|
| `413 Request Entity Too Large` on upload | `client_max_body_size 25m;` missing in host Nginx config → use `deploy/nginx-site.conf` |
| Answer appears all at once, not streaming | `proxy_buffering off;` in the `/api/` block |
| "ANTHROPIC_API_KEY is missing" banner | Fill `backend/.env`, then `docker compose up -d` |
| `401 Admin token required` | Paste `ADMIN_TOKEN` into the sidebar field |
| "No readable text found" | Scanned PDF — OCR it first (e.g. `ocrmypdf in.pdf out.pdf`) |
| Backend build `Killed` | Swap missing — `setup-vps.sh` adds 2 GB |
