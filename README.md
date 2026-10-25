# FusionRAG: hybrid RAG with Claude

Upload PDFs/DOCX/TXT/MD/CSV, ask questions, get answers from **Claude (Anthropic API)** with numbered citations.
Live at **https://app.srmai.tech** (Hostinger VPS, behind Traefik).

**Why "fusion"?** Every question runs two searches and fuses the results:

| Retriever | Good at | Implementation |
|---|---|---|
| Vector (semantic) | Meaning, paraphrases ("backup failed" ≈ "job did not complete") | `fastembed` + `BAAI/bge-small-en-v1.5`, CPU, no extra API key |
| BM25 (keyword) | Exact terms: error codes, hostnames, KB numbers (`19:1131`, `AHV`) | Built-in Okapi BM25 |
| Fusion | Best of both | Reciprocal Rank Fusion (RRF, k=60) |

The top passages go to Claude, which answers only from them. The UI can switch **Hybrid / Vector / Keyword** and shows each source's vector rank, BM25 rank and RRF score.

## Architecture (production)

```
Browser ──HTTPS──► Traefik :443 (shared with n8n, auto Let's Encrypt)
                      │  Host(`app.srmai.tech`)
                      ▼
               rag-frontend (React build + Nginx :80)
                      │  /api/*  (prefix stripped)
                      ▼
               rag-backend (FastAPI :8000) ──► Claude API
                      │
                      └─ Docker volume fusionrag_rag-data (index persists)

Host ports 3000/8000 are bound to 127.0.0.1 only; the public way in is HTTPS via Traefik.
```

## Project layout

```
FusionRAG/
├── backend/
│   ├── app/            config.py · ingest.py (parse+chunk) · store.py (hybrid index) · llm.py (Claude)
│   ├── main.py         FastAPI: /health /config /documents /search /chat (SSE streaming)
│   ├── requirements.txt
│   ├── Dockerfile      bakes the embedding model into the image
│   └── .env.example    → copy to backend/.env (API key, admin token). Never committed.
├── frontend/
│   ├── src/            React (Vite) chat UI
│   ├── nginx.conf      serves the SPA + proxies /api to the backend container
│   └── Dockerfile      multi-stage build
├── deploy/
│   ├── docker-compose.traefik.yml   Traefik labels (production add-on)
│   ├── setup-vps.sh                 one-time server prep (detects Traefik)
│   ├── redeploy.sh                  git pull + rebuild + health check
│   └── nginx-site.conf              only for Option B (server without Traefik)
├── docker-compose.yml  base stack (laptop + VPS)
├── .env.example        → copy to .env on the VPS (domain, Traefik add-on, private ports)
└── .gitignore
```

Two different `.env` files:

| File | Read by | Contains | Where |
|---|---|---|---|
| `backend/.env` | the FastAPI app | `ANTHROPIC_API_KEY`, `ADMIN_TOKEN`, model | laptop + VPS |
| `.env` (root) | `docker compose` | `COMPOSE_FILE`, `APP_DOMAIN`, `BIND_IP` | VPS only |

## Part 1: run on your laptop

```powershell
cd FusionRAG
copy backend\.env.example backend\.env      # edit: ANTHROPIC_API_KEY (ADMIN_TOKEN optional locally)
docker compose up --build
```
- http://localhost:3000 → the app
- http://localhost:8000/docs → FastAPI test page
- Logs: `docker compose logs -f backend`

No root `.env` is needed on the laptop. Push changes with GitHub Desktop (Commit to main → Push origin).

## Part 2: deploy on the Hostinger VPS (Traefik)

Hostinger's Docker template (e.g. the n8n one) already runs **Traefik** on ports 80/443.
FusionRAG plugs into it with labels; no Nginx or Certbot on the host.

1. **DNS** (hPanel → Domains → DNS records): `A  app  → VPS_IP`. Check: `curl -4 ifconfig.me` on the VPS matches.
2. **Clone** (private repo → use a GitHub Personal Access Token as the password):
   ```bash
   git clone https://github.com/iamsuresharchitect/FusionRAG.git
   cd FusionRAG
   ```
3. **Prepare the server** (updates, Docker, swap, ufw; restarts Traefik after a Docker upgrade):
   ```bash
   sudo bash deploy/setup-vps.sh
   ```
4. **Secrets**:
   ```bash
   cp backend/.env.example backend/.env && nano backend/.env    # API key + admin token
   cp .env.example .env && nano .env                            # APP_DOMAIN=app.srmai.tech
   ```
5. **Start**:
   ```bash
   docker compose up --build -d
   docker compose ps                                  # ports show 127.0.0.1:...
   curl http://127.0.0.1:3000/api/health              # {"status":"ok",...}
   ```
6. Open **https://APP_DOMAIN**. The first visit takes ~30 s while Traefik gets the certificate.
7. If `/var/run/reboot-required` exists, `reboot`; all containers restart on their own.

### Option B: a server WITHOUT Traefik
Comment out `COMPOSE_FILE` in the root `.env`, then use host Nginx + Certbot:
```bash
sudo apt install -y nginx certbot python3-certbot-nginx
sudo cp deploy/nginx-site.conf /etc/nginx/sites-available/APP_DOMAIN   # replace yourdomain.com inside
sudo ln -s /etc/nginx/sites-available/APP_DOMAIN /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default && sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d APP_DOMAIN
```

## Redeploy after changes
Laptop: commit + push → VPS:
```bash
cd ~/FusionRAG && bash deploy/redeploy.sh
```
Indexed documents live in the `fusionrag_rag-data` volume and survive redeploys (`docker compose down -v` deletes them).

## Configuration (`backend/.env`)

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | Required. console.anthropic.com → API Keys |
| `CLAUDE_MODEL` | `claude-sonnet-5-5` | `claude-haiku-5-5` cheaper/faster, `claude-opus-5-5` strongest |
| `ADMIN_TOKEN` | empty | When set, upload/delete need it (UI asks once). Chat stays open |
| `TOP_K` | 6 | Passages sent to Claude (adjustable in the UI) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 1000 / 150 | Characters |
| `MAX_UPLOAD_MB` | 25 | Also `client_max_body_size` in `frontend/nginx.conf` |

## API
| Method | Path (public: prefix `/api`) | Purpose |
|---|---|---|
| GET | `/health` | Status, doc/chunk counts |
| GET | `/config` | Model names, whether key/admin token are set |
| GET | `/documents` | List indexed docs |
| POST | `/documents` | Upload (multipart `files`, header `X-Admin-Token`) |
| DELETE | `/documents/{id}` | Remove a doc |
| POST | `/search` | Retrieval only `{query, mode, top_k}` |
| POST | `/chat` | `{question, history, mode, top_k}` → SSE: `sources`, `token`, `error`, `done` |

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Plain text `404 page not found` + "Not secure" | Traefik has no route. Check labels: `docker inspect rag-frontend --format '{{json .Config.Labels}}'`. Missing → root `.env` (`COMPOSE_FILE`, `APP_DOMAIN`) absent; `docker compose up -d` again |
| Traefik log: `Cannot connect to the Docker daemon at unix:///var/run/docker.sock` | Docker was upgraded/restarted; Traefik holds a dead socket → `docker restart traefik-traefik-1` |
| "Not secure" only in your normal browser window | Cached earlier failure. Close all tabs of the site or test in Incognito |
| `nginx: port 80 is already in use` during setup | Traefik owns 80/443; expected. Use Part 2 (Traefik), not Option B |
| Build fails: `Could not load model BAAI/bge-small-en-v1.5` | HuggingFace blocked on that network. Use another network, or `--build-arg HF_ENDPOINT=https://hf-mirror.com` |
| `/chat` logs `200 OK` but the UI shows an error | Streaming sends 200 first. Look for `ERROR Claude call failed` in `docker compose logs backend` (bad key/model/credits) |
| `401 Admin token required` | Paste `ADMIN_TOKEN` into the sidebar |
| "No readable text found" | Scanned PDF → OCR first (`ocrmypdf in.pdf out.pdf`) |
| Backend build `Killed` | No swap → `setup-vps.sh` adds 2 GB |
| n8n reachable on `http://VPS_IP:32768` | Hostinger template publishes it; restrict in hPanel → VPS → Firewall (allow 22, 80, 443) |
