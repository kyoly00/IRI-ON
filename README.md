<img width="1002" height="8003" alt="ChefYam 패기5 우리" src="https://github.com/user-attachments/assets/cd5ebb1c-0a3d-4513-84cb-8954a0858a63" />

# 🚀 프로젝트 실행 가이드
이 문서는 로컬 환경에서 백엔드(FastAPI)와 프론트엔드(Vite) 프로젝트를 실행하는 방법을 단계별로 안내합니다.

---

## 1️⃣ 프로젝트 클론

```bash
git clone https://github.com/SKT-FLY-AI-team5/IRI-ON
cd IRI-ON
```

---

## 2️⃣ 백엔드 환경 설정

1. `.env` 파일을 `be/` 폴더에 넣습니다.

2. 터미널에서 로컬 IPv4 주소 확인:

```bash
# Windows
ipconfig
```

3. `be/main.py` 파일에서 허용할 주소를 추가:

```python
origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://192.168.0.11:8000",
    # 이 부분에 추가하세요. 예: "<IPv4주소>:5173"
]
```


4. fe/app/scr/config.js 파일에서 API_BASE 주소를 변경:

```javascript
const config = {
  API_BASE: "http://localhost:8000", // 이 부분을 변경
};
```
---

## 3️⃣ 백엔드 실행

```bash
cd be
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

> ⚡ `--reload` 옵션을 사용하면 코드 수정 시 서버가 자동 재시작됩니다.

---

## 4️⃣ 프론트엔드 실행

```bash
cd fe/app

# npm, vite 설치
pip install npm
pip install vite

# 패키지 설치
npm install

# 개발 서버 실행
npm run dev
```

---

## 5️⃣ 모바일 접속

1. 모바일 기기가 **같은 Wi-Fi**에 연결되어 있는지 확인합니다.
2. 브라우저에서 아래 주소로 접속:

```
http://<IPv4주소>:5173
```

> 예: `http://192.168.0.12:5173`

---

## 6️⃣ FAQ

**Q1. 포트 충돌이 발생하면?**
- 다른 프로세스가 8000번 또는 5173번 포트를 사용 중일 수 있습니다.
- 백엔드: `uvicorn main:app --host 0.0.0.0 --port <다른포트> --reload`
- 프론트엔드: `npm run dev -- --port <다른포트>`

**Q2. 모바일 접속이 안 될 때**
- PC와 모바일이 같은 Wi-Fi에 연결되어 있는지 확인하세요.
- 방화벽에서 해당 포트를 허용했는지도 확인합니다.

**Q3. 환경 변수를 잘못 넣으면?**
- 백엔드 연결 실패나 인증 오류가 발생할 수 있습니다. `.env` 파일의 값이 정확한지 다시 확인하세요.

---
