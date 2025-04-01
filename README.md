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
git clone https://github.com/yourusername/miso-rag-tester.git
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

`.env` 파일을 생성하고 다음 정보를 입력하세요:

```
MISO_API_URL=your_api_url
MISO_API_KEY=your_api_key
GOOGLE_SHEET_ID=your_google_sheet_id
```

## Google 스프레드시트 설정

1. Google Cloud Platform에서 서비스 계정을 생성하고 JSON 키 파일을 다운로드합니다.
2. 다운로드한 JSON 키 파일의 이름을 `credentials.json`으로 변경하고 프로젝트 루트 디렉토리에 저장합니다.
3. 사용할 Google 스프레드시트를 생성하고 서비스 계정 이메일에 편집 권한을 부여합니다.

## 문의

최정규 주임 (Kyle) 