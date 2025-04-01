# 인사챗봇 RAG DATA 검색 평가

인사 관련 데이터를 검색하고 평가할 수 있는 Streamlit 웹 애플리케이션입니다.

## 기능

- 질문 입력 및 인사 데이터 검색
- 관련 문서 선택 및 평가 기능
- 검색 결과 품질 평가 (A, B, C)
- 피드백 코멘트 제출
- 사용자별 질문 히스토리 확인

## 설치 및 실행

```bash
# 저장소 복제
git clone https://github.com/gsenrdx/miso-rag-tester.git
cd miso-rag-tester

# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 애플리케이션 실행
streamlit run app.py
```

## 환경 설정

### 로컬 개발 환경

#### 1. .env 파일 사용

`.env` 파일을 생성하고 다음 정보를 입력하세요:

```
MISO_API_URL=your_api_url
MISO_API_KEY=your_api_key
GOOGLE_SHEET_ID=your_google_sheet_id
```

#### 2. 터미널에서 환경변수 설정

터미널에서 직접 환경변수를 설정할 수도 있습니다:

```bash
# macOS/Linux
export MISO_API_URL="your_api_url"
export MISO_API_KEY="your_api_key"
export GOOGLE_SHEET_ID="your_google_sheet_id"

# Windows (cmd)
set MISO_API_URL=your_api_url
set MISO_API_KEY=your_api_key
set GOOGLE_SHEET_ID=your_google_sheet_id

# Windows (PowerShell)
$env:MISO_API_URL="your_api_url"
$env:MISO_API_KEY="your_api_key"
$env:GOOGLE_SHEET_ID="your_google_sheet_id"
```

환경변수 설정 후 애플리케이션 실행:
```bash
streamlit run app.py
```

### Streamlit Cloud 배포 환경

Streamlit Cloud에 배포할 경우, 다음과 같이 설정하세요:

#### 1. 웹 인터페이스에서 설정

1. [Streamlit Cloud](https://share.streamlit.io/)에 로그인
2. 새로운 앱 배포를 선택하고 GitHub 저장소 연결
3. 앱 설정에서 "Secrets" 섹션에 환경 변수 설정:

```toml
MISO_API_URL = "your_api_url"
MISO_API_KEY = "your_api_key"
GOOGLE_SHEET_ID = "your_google_sheet_id"

[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-private-key-id"
private_key = "your-private-key"
client_email = "your-service-account-email"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "your-cert-url"
```

#### 2. Streamlit CLI로 설정 (streamlit-cli 필요)

```bash
# streamlit-cli 설치
pip install streamlit-cli

# 로그인
streamlit login

# 환경변수 설정
streamlit secrets set MISO_API_URL="your_api_url"
streamlit secrets set MISO_API_KEY="your_api_key"
streamlit secrets set GOOGLE_SHEET_ID="your_google_sheet_id"

# GCP 서비스 계정 키 설정 (credentials.json 파일 경로 지정)
streamlit secrets import credentials.json --scope gcp_service_account
```

## Google 스프레드시트 설정

1. Google Cloud Platform에서 서비스 계정을 생성하고 JSON 키 파일을 다운로드합니다.
2. 다운로드한 JSON 키 파일의 이름을 `credentials.json`으로 변경하고 프로젝트 루트 디렉토리에 저장합니다.
3. 사용할 Google 스프레드시트를 생성하고 서비스 계정 이메일에 편집 권한을 부여합니다.

## 문의

최정규 주임 (Kyle)
