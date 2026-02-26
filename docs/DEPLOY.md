# Claude Distill Relay — Single Deployment Guide

이 문서 하나로 배포/운영/검증/트러블슈팅을 모두 정리합니다.

---

## 1) 현재 서버 아키텍처 (권장)

현재 구성의 정답 경로:

1. `claude-distill-relay` (WebSocket relay) → `127.0.0.1:9784`
2. `nginx` → `relay.fireamulet.com` 요청을 `127.0.0.1:9784`로 프록시
3. `cloudflared tunnel` → `relay.fireamulet.com`을 `http://localhost:80`으로 publish
4. 클라이언트 → `wss://relay.fireamulet.com` 접속

즉, 외부는 WSS(443), 내부는 nginx와 relay로 연결.

---

## 2) 중요한 정정 사항 (혼동 방지)

- 이 프로젝트는 **raw TCP relay가 아니라 WebSocket relay** 입니다.
- Cloudflare Tunnel의 Published route에서 `tcp://` 타입이 보여도,
  일반 raw TCP 클라이언트가 인터넷에서 바로 `host:port`로 붙는 것과는 다릅니다.
- 일반 raw TCP 공개 모델이 필요하면 Cloudflare Spectrum 등 별도 방식이 필요합니다.
- 현재 프로젝트의 공용 접속 방식은 **`wss://...`** 입니다.

---

## 3) 서버 1회 배포

```bash
cd ~/.openclaw/workspace/claude-distill-relay
./scripts/deploy-oneclick.local.sh fireamulet.com 9784
```

이 스크립트가 수행:
- git pull
- `.venv` 생성 + `websockets` 설치
- `.env.relay` 생성/보정
- systemd unit 설치/재시작
- 리슨 체크
- (옵션) UFW 9784 오픈

---

## 4) nginx 프록시 설정

```bash
cd ~/.openclaw/workspace/claude-distill-relay
./scripts/setup-nginx-relay.sh relay.fireamulet.com 9784
```

완료 후 nginx가 `relay.fireamulet.com` 트래픽을 relay로 프록시함.

---

## 5) Cloudflare Zero Trust 대시보드 설정

경로:
- Zero Trust → Networks → Tunnels → (사용 중인 터널) → **Published application routes**

추가 값:
- Subdomain: `relay`
- Domain: `fireamulet.com`
- Path: 비움
- Service Type: `HTTP`
- URL: `localhost:80`

저장 후 최종 접속 주소:
- `wss://relay.fireamulet.com`

> `Hostname routes`의 private hostname (`www.example.local`) 화면은 본 케이스 대상이 아님.

---

## 6) 상태 확인

### relay
```bash
sudo systemctl status claude-distill-relay.service
ss -ltnp | grep 9784
```

### nginx
```bash
sudo nginx -t
sudo systemctl status nginx
```

### cloudflared
```bash
sudo systemctl status cloudflared
```

---

## 7) End-to-End 테스트

```bash
python3 - <<'PY'
import asyncio, websockets

async def main():
    async with websockets.connect("wss://relay.fireamulet.com") as ws:
        await ws.send('{"type":"CREATE_ROOM"}')
        print(await ws.recv())

asyncio.run(main())
PY
```

성공 기준:
- `{"type":"ROOM_CREATED", ...}` 응답

---

## 8) 운영 명령

```bash
# relay 로그
sudo journalctl -u claude-distill-relay.service -f

# relay 재시작
sudo systemctl restart claude-distill-relay.service

# nginx 리로드
sudo systemctl reload nginx

# cloudflared 재시작
sudo systemctl restart cloudflared
```

---

## 9) 장애 대응 빠른 체크

1. relay active인지 (`systemctl status`)
2. 9784 listening인지 (`ss -ltnp | grep 9784`)
3. nginx config 정상인지 (`nginx -t`)
4. tunnel connected인지 (`systemctl status cloudflared`)
5. dashboard published route가 `relay.fireamulet.com -> localhost:80`인지

---

## 10) 파일 기준점

- 앱: `relay.py`
- 환경값 예시: `.env.example`
- 실제 환경값: `.env.relay` (gitignore)
- 서비스 유닛 템플릿: `claude-distill-relay.service`
- 배포 스크립트:
  - `scripts/deploy-oneclick.local.sh` (원클릭)
  - `scripts/setup-nginx-relay.sh` (nginx 연결)

---

## 11) 보안 체크리스트

- relay를 직접 공인 노출하지 않고 WSS 경유 사용
- rate limit 유지 (`RELAY_RATE_LIMIT_MAX`, `RELAY_RATE_LIMIT_WINDOW`)
- 불필요 포트 미오픈
- `.env.relay` 절대 커밋 금지
