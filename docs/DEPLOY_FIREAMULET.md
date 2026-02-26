# Fireamulet 서버 배포 가이드 (Relay: 9784)

> 이 문서는 **환경별 예시 가이드**입니다.
> 일반 배포 절차는 `docs/DEPLOY.md`를 먼저 참고하세요.

이 문서는 `claude-distill-relay`를 `fireamulet.com:9784`로 운영하기 위한 실전 체크리스트입니다.

## 0) 전제

- 서버에 이 레포가 있음: `~/.openclaw/workspace/claude-distill-relay`
- systemd 사용 가능
- sudo 권한 있음

---

## 1) 코드 업데이트

```bash
cd ~/.openclaw/workspace/claude-distill-relay
git pull
```

---

## 2) 서비스 설치/기동

```bash
cd ~/.openclaw/workspace/claude-distill-relay
./scripts/install-systemd.sh
```

상태 확인:

```bash
sudo systemctl status claude-distill-relay.service
ss -ltnp | grep 9784
```

정상이라면 `0.0.0.0:9784` 또는 서버 IP:9784 리스닝이 보여야 합니다.

---

## 3) 방화벽 오픈 (9784/tcp)

### UFW 사용 시

```bash
sudo ufw allow 9784/tcp
sudo ufw status
```

### iptables 사용 시

```bash
sudo iptables -I INPUT -p tcp --dport 9784 -j ACCEPT
```

> iptables는 재부팅 후 유지 설정(iptables-persistent 등)을 별도로 해주세요.

---

## 4) DNS 확인

공인 IP 확인:

```bash
curl -4 ifconfig.me
```

도메인 확인:

```bash
dig +short fireamulet.com
```

두 값이 같아야 `fireamulet.com:9784` 접속이 가능합니다.

---

## 5) 외부 접속 테스트

다른 네트워크(예: 모바일 데이터)에서:

```bash
nc -vz fireamulet.com 9784
```

성공 시 TCP 접속 가능 상태입니다.

---

## 6) 클라이언트 접속값

- Relay endpoint: `fireamulet.com:9784`

예시(클라이언트 구현 후):

```bash
serve.py --relay fireamulet.com:9784 "passphrase"
receive.py --relay fireamulet.com:9784 --room <room_id> "passphrase"
```

---

## 7) 운영 추천

- 가능하면 `relay.fireamulet.com:9784` 서브도메인 분리
- `.env.relay`에서 rate-limit 기본값 유지 또는 강화
- 주기적으로 로그 확인

```bash
sudo journalctl -u claude-distill-relay.service -f
```

---

## 8) 트러블슈팅

### `Unit claude-distill-relay.service could not be found`
유닛 미설치 상태입니다.

```bash
./scripts/install-systemd.sh
```

### 서비스는 active인데 외부 접속 실패
- 방화벽 미오픈 (`ufw status` 확인)
- DNS가 다른 IP 가리킴 (`dig +short fireamulet.com`)
- 클라우드 보안그룹/라우터 포트포워딩 누락

### `rate_limited` 에러
동일 IP에서 CREATE/JOIN 요청이 너무 많습니다.
- 요청 간격 조절
- 필요 시 `.env.relay`의 `RELAY_RATE_LIMIT_MAX`, `RELAY_RATE_LIMIT_WINDOW` 조정 후 서비스 재시작

```bash
sudo systemctl restart claude-distill-relay.service
```
