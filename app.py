import streamlit as st
import requests
import json
import os
from dotenv import load_dotenv
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time

# 페이지 설정 (반드시 첫 번째 Streamlit 명령어여야 함)
st.set_page_config(
    page_title="인사챗봇 RAG DATA 검색 평가",
    page_icon="🔍",
    layout="wide"
)

# .env 파일에서 환경 변수 로드
env_path = os.path.join(os.path.dirname(__file__), '.env')
# 로컬 개발 환경에서는 .env 파일 사용, 배포 환경에서는 Streamlit secrets 사용
if os.path.exists(env_path):
    load_dotenv(env_path)
    
    # API 정보
    API_URL = os.getenv("MISO_API_URL")
    API_KEY = os.getenv("MISO_API_KEY")
    GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
else:
    # Streamlit Cloud에서 실행 중인 경우 secrets 사용
    API_URL = st.secrets.get("MISO_API_URL")
    API_KEY = st.secrets.get("MISO_API_KEY")
    GOOGLE_SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID")

# 구글 시트 설정
def setup_google_sheets():
    try:
        scope = ['https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive']
        
        # 로컬 개발 환경에서는 credentials.json 파일 사용
        if os.path.exists('credentials.json'):
            credentials = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        else:
            # Streamlit Cloud에서는 secrets에서 자격 증명 정보 가져오기
            gcp_creds = st.secrets.get("gcp_service_account", {})
            credentials = ServiceAccountCredentials.from_json_keyfile_dict(gcp_creds, scope)
            
        gc = gspread.authorize(credentials)
        return gc
    except Exception as e:
        st.error(f"구글 시트 설정 중 오류 발생: {str(e)}")
        return None

def load_query_history(gc):
    """구글 시트에서 질문 히스토리를 로드하는 함수"""
    try:
        # 로컬 또는 Streamlit Cloud 환경에 맞게 Google Sheet ID 가져오기
        spreadsheet_id = GOOGLE_SHEET_ID
        if not spreadsheet_id:
            st.error("구글 시트 ID가 설정되지 않았습니다.")
            return []
            
        sheet = gc.open_by_key(spreadsheet_id).sheet1
        all_values = sheet.get_all_values()
        
        # 헤더 행 제외하고 데이터 처리
        history = []
        for row in all_values[1:]:  # 첫 번째 행은 헤더
            if len(row) >= 6:  # 필요한 모든 컬럼이 있는지 확인
                # 선택된 문서 정보 파싱 (세미콜론으로 구분된 문자열을 리스트로 변환)
                selected_docs = row[5].split(';') if len(row) > 5 and row[5] else []
                
                history.append({
                    'timestamp': row[0],
                    'user_name': row[1],
                    'query': row[2],
                    'rating': row[3],
                    'comment': row[4],
                    'selected_documents': selected_docs
                })
        
        # 타임스탬프 기준으로 최신순 정렬
        history.sort(key=lambda x: x['timestamp'], reverse=True)
        return history
    except Exception as e:
        st.error(f"질문 히스토리 로드 중 오류 발생: {str(e)}")
        return []

def save_feedback_to_sheet(gc, feedback_data):
    try:
        # 스프레드시트 열기 (스프레드시트 ID를 환경 변수에서 가져옴)
        spreadsheet_id = GOOGLE_SHEET_ID
        if not spreadsheet_id:
            st.error("구글 시트 ID가 설정되지 않았습니다.")
            return False
            
        sheet = gc.open_by_key(spreadsheet_id).sheet1
        
        # 현재 시간 추가
        feedback_data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 선택된 문서 정보 처리
        selected_docs_info = []
        for doc_id in feedback_data['selected_documents']:
            try:
                # doc_id 형식: dataset_name_chapter_article
                parts = doc_id.split('_', 2)
                if len(parts) != 3:
                    continue
                    
                dataset_name, chapter, article = parts
                
                # 전체 결과에서 해당 문서 찾기
                for idx, output in enumerate(feedback_data['all_outputs'], 1):
                    content = output.get('content', '')
                    content_parts = content.split(';')
                    
                    # 문서 정보 추출
                    doc_chapter = next((part.split(':')[1].strip() for part in content_parts if '장번호' in part), '')
                    doc_article = next((part.split(':')[1].strip() for part in content_parts if '조번호' in part), '')
                    doc_title = next((part.split(':')[1].strip() for part in content_parts if '조제목' in part), '')
                    
                    # 문서 매칭 확인 (공백 제거 후 비교)
                    if (output.get('metadata', {}).get('dataset_name') == dataset_name and
                        doc_chapter.strip() == chapter.strip() and
                        doc_article.strip() == article.strip()):
                        
                        score = output.get('metadata', {}).get('score', 0)
                        
                        # 문서 정보 포맷팅
                        doc_info = f"{dataset_name} - {chapter} - {article}"
                        if doc_title and doc_title.lower() != 'nan':
                            doc_info += f" ({doc_title})"
                        doc_info += f" (관련도: {score:.4f}, 순위: {idx}/{len(feedback_data['all_outputs'])})"
                        
                        selected_docs_info.append(doc_info)
                        break
            except Exception as e:
                st.error(f"문서 정보 처리 중 오류 발생: {str(e)}")
                continue
        
        # 데이터를 행으로 추가
        row = [
            feedback_data['timestamp'],
            feedback_data['user_name'],
            feedback_data['query'],
            feedback_data['rating'],
            feedback_data['comment'],
            '; '.join(selected_docs_info)  # 선택된 문서 정보를 세미콜론으로 구분하여 저장
        ]
        
        # 마지막 행 찾기
        last_row = len(sheet.get_all_values()) + 1
        
        # 각 열에 데이터 추가
        for col, value in enumerate(row, 1):
            sheet.update_cell(last_row, col, value)
            
        return True
    except Exception as e:
        st.error(f"피드백 저장 중 오류 발생: {str(e)}")
        return False

def submit_feedback(user_name, feedback_data, response_data):
    """피드백 제출 처리 함수"""
    # 유효성 검사
    validation_errors = []
    
    if not user_name:
        validation_errors.append("사용자 이름을 입력해주세요.")
    
    if not feedback_data['rating']:
        validation_errors.append("검색 결과 품질 평가를 선택해주세요.")
    
    if not feedback_data['selected_documents']:
        validation_errors.append("관련 문서를 하나 이상 선택해주세요.")
    
    if validation_errors:
        for error in validation_errors:
            st.error(error)
        return False
    
    # 로딩 상태 설정
    st.session_state.is_submitting = True
    
    try:
        # 구글 시트 설정
        gc = setup_google_sheets()
        if gc:
            with st.spinner("피드백을 저장하는 중..."):
                # 피드백 저장
                if save_feedback_to_sheet(gc, feedback_data):
                    # 질문 히스토리에 추가 (최신순으로 정렬)
                    query_history_data = {
                        'query': feedback_data['query'],
                        'rating': feedback_data['rating'],
                        'comment': feedback_data['comment'],
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'user_name': user_name,
                        'selected_documents': feedback_data['selected_documents']
                    }
                    st.session_state.query_history.insert(0, query_history_data)
                    
                    st.success("피드백이 성공적으로 저장되었습니다. 감사합니다!")
                    st.markdown("""
                        <div style='background-color: #e8f4ff; padding: 1rem; border-radius: 0.25rem; margin: 1rem 0;'>
                            <p style='margin: 0; color: #0066cc;'>📊 피드백 결과는 <a href='https://docs.google.com/spreadsheets/d/1M264J2XJLEaYjZNZLEhvaBgA_TZtzabnnumw-8QbF_8/edit?usp=sharing' target='_blank'>구글 시트</a>에서 확인하실 수 있습니다.</p>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    # 피드백 저장 후 페이지 자동 초기화
                    st.session_state.search_results = None
                    st.session_state.current_query = None
                    st.session_state.selected_documents = set()
                    st.session_state.feedback_rating = None
                    st.session_state.feedback_comment = ""
                    
                    # 히스토리 최신화
                    gc = setup_google_sheets()
                    if gc:
                        st.session_state.query_history = load_query_history(gc)
                    
                    # 잠시 후 페이지 새로고침을 위한 메시지
                    st.info("피드백이 저장되었습니다. 3초 후 페이지가 초기화됩니다...")
                    time.sleep(3)  # 5초 대기
                    st.experimental_rerun()
                    
                    return True
                else:
                    st.error("피드백 저장에 실패했습니다. 다시 시도해주세요.")
                    return False
    finally:
        # 로딩 상태 해제
        st.session_state.is_submitting = False

# 세션 상태 초기화
if 'selected_documents' not in st.session_state:
    st.session_state.selected_documents = set()
if 'feedback_rating' not in st.session_state:
    st.session_state.feedback_rating = None
if 'feedback_comment' not in st.session_state:
    st.session_state.feedback_comment = ""
if 'search_results' not in st.session_state:
    st.session_state.search_results = None
if 'current_query' not in st.session_state:
    st.session_state.current_query = None
if 'is_submitting' not in st.session_state:
    st.session_state.is_submitting = False
if 'query_history' not in st.session_state:
    # 구글 시트에서 히스토리 로드
    gc = setup_google_sheets()
    if gc:
        st.session_state.query_history = load_query_history(gc)
    else:
        st.session_state.query_history = []

# 타이틀 및 설명
st.title("인사챗봇 RAG DATA 검색 평가")
st.markdown("""
    <div style='background-color: #e8f4ff; padding: 1rem; border-radius: 0.25rem; margin-bottom: 1rem;'>
        <p style='margin: 0; color: #0066cc;'>1. 테스트할 질문을 입력해주세요.</p>
    </div>
""", unsafe_allow_html=True)

# 사이드바 설정
with st.sidebar:
    st.header("사용자 설정")
    user_name = st.text_input("이름")
    user_position = "매니저"  # 기본값으로 설정
    user_company = "GSPOGE"  # 기본값으로 설정
    
    # 디버깅을 위한 출력
    st.write("현재 사용자:", user_name)
    st.write("질문 히스토리 개수:", len(st.session_state.query_history))
    
    # 질문 히스토리 표시 (사용자 이름이 있으면 항상 표시)
    st.divider()
    st.subheader("📝 질문 히스토리")
    
    if not user_name:
        st.info("이름을 입력하면 질문 히스토리가 표시됩니다.")
    elif not st.session_state.query_history:
        st.info("아직 질문 히스토리가 없습니다.")
    else:
        # 현재 사용자의 질문만 필터링
        user_history = [q for q in st.session_state.query_history if q.get('user_name') == user_name]
        
        if not user_history:
            st.info(f"{user_name}님의 질문 히스토리가 없습니다.")
        else:
            for query_data in user_history:
                with st.expander(f"질문: {query_data['query']}", expanded=False):
                    st.markdown(f"""
                        <div style='background-color: #f8f9fa; padding: 0.5rem; border-radius: 0.25rem; margin-bottom: 0.5rem;'>
                            <p style='margin: 0;'><strong>평가:</strong> {query_data['rating']}</p>
                            <p style='margin: 0;'><strong>시간:</strong> {query_data['timestamp']}</p>
                        </div>
                    """, unsafe_allow_html=True)
                    if query_data['comment']:
                        st.markdown(f"""
                            <div style='background-color: #f8f9fa; padding: 0.5rem; border-radius: 0.25rem;'>
                                <p style='margin: 0;'><strong>코멘트:</strong> {query_data['comment']}</p>
                            </div>
                        """, unsafe_allow_html=True)
                    # 선택된 문서 정보 표시
                    if 'selected_documents' in query_data:
                        st.markdown(f"""
                            <div style='background-color: #f8f9fa; padding: 0.5rem; border-radius: 0.25rem;'>
                                <p style='margin: 0;'><strong>선택된 문서:</strong></p>
                                <ul style='margin: 0.5rem 0 0 1.5rem;'>
                                    {''.join([f"<li>{doc}</li>" for doc in query_data['selected_documents']])}
                                </ul>
                            </div>
                        """, unsafe_allow_html=True)

# 메인 영역
query = st.text_area("질문 입력", height=100)

# 검색 버튼
if st.button("Data 검색", type="primary", key="search_button"):
    if not query:
        st.error("질문을 입력해주세요.")
    else:
        with st.spinner("검색 중..."):
            # API 요청 준비
            payload = {
                "user": {
                    "name": user_name,
                    "position": user_position,
                    "company": user_company
                },
                "inputs": {
                    "query": query,
                },
                "query": query
            }
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {API_KEY}"
            }
            
            try:
                # API 호출
                response = requests.post(API_URL, headers=headers, json=payload)
                response_data = response.json()
                
                # 검색 결과 저장
                st.session_state.search_results = response_data
                st.session_state.current_query = query
                
                # 결과 표시
                st.subheader("검색 결과")
                
                # 탭 생성
                tab1, tab2 = st.tabs(["응답 내용", "전체 응답 데이터"])
                
                with tab1:
                    if response_data.get("data", {}).get("outputs", {}).get("output"):
                        outputs = response_data["data"]["outputs"]["output"]
                        
                        # hyde_query 표시 추가
                        hyde_query = response_data.get("data", {}).get("outputs", {}).get("hyde_query")
                        if hyde_query:
                            with st.expander("🔍 변환된 검색 query (가상문서)", expanded=False):
                                st.markdown("""
                                    <div style='background-color: #f8f9fa; padding: 1rem; border-radius: 0.25rem; margin-bottom: 1rem;'>
                                        <p style='color: #666; margin: 0;'>이 쿼리는 답변과 상관없는 검색을 위한 가상문서입니다.</p>
                                    </div>
                                """, unsafe_allow_html=True)
                                st.markdown(f"""
                                    <div style='background-color: #f0f0f0; padding: 1rem; border-radius: 0.25rem; 
                                        white-space: pre-wrap; word-wrap: break-word; overflow-wrap: break-word; 
                                        font-family: monospace;'>
                                        {hyde_query}
                                    </div>
                                """, unsafe_allow_html=True)
                            st.divider()
                        
                        # 결과 요약
                        st.markdown(f"총 {len(outputs)}개의 관련 문서를 찾았습니다.")
                        st.markdown("""
                            <div style='background-color: #e8f4ff; padding: 1rem; border-radius: 0.25rem; margin-bottom: 1rem;'>
                                <p style='margin: 0; color: #0066cc;'>2. 질문과 관련된 문서를 선택해주세요.</p>
                            </div>
                        """, unsafe_allow_html=True)
                        
                        # 결과 데이터 준비
                        results_data = []
                        for output in outputs:
                            content = output.get('content', '')
                            metadata = output.get('metadata', {})
                            score = metadata.get('score', 0)
                            dataset_name = metadata.get('dataset_name', 'N/A')
                            
                            content_parts = content.split(';')
                            chapter = next((part.split(':')[1] for part in content_parts if '장번호' in part), 'N/A')
                            article = next((part.split(':')[1] for part in content_parts if '조번호' in part), 'N/A')
                            title_part = next((part.split(':')[1] for part in content_parts if '조제목' in part), '')
                            title = 'null' if not title_part or title_part.strip().lower() == 'nan' else title_part.strip()
                            
                            # 내용에서 장제목 부분 제거
                            content_without_title = ';'.join([part for part in content_parts if '조제목' not in part])
                            
                            # 특수 케이스 처리 - 복잡한 데이터 패턴 감지
                            is_complex_format = False
                            chapter_title = next((part.split(':')[1] for part in content_parts if '장제목' in part), '')
                            
                            # 복잡한 데이터 구조 감지 조건들
                            if any(pattern in article for pattern in ['|', '---------', '표']) or len(article) > 30:
                                is_complex_format = True
                            if article and article[0] == '|':  # 표 형식으로 시작하는 조번호
                                is_complex_format = True
                            
                            if is_complex_format:
                                # 간략한 제목으로 대체
                                display_chapter = f"{chapter}"
                                if chapter_title:
                                    display_chapter = f"{chapter} - {chapter_title}"
                                if len(display_chapter) > 25:
                                    display_chapter = display_chapter[:22] + "..."
                                article = ''  # 조번호 비우기
                            else:
                                display_chapter = chapter
                            
                            results_data.append({
                                'dataset_name': dataset_name,
                                'chapter': chapter,
                                'display_chapter': display_chapter,
                                'article': article,
                                'title': title,
                                'score': score,
                                'content': content_without_title,
                                'is_complex_format': is_complex_format
                            })
                        
                        # 점수 기준으로 정렬 (높은 순)
                        results_data.sort(key=lambda x: x['score'], reverse=True)
                        
                        # 데이터셋별로 결과 그룹화
                        for dataset_name in set(item['dataset_name'] for item in results_data):
                            st.subheader(f"📚 {dataset_name}")
                            
                            # 해당 데이터셋의 결과만 필터링
                            dataset_results = [item for item in results_data if item['dataset_name'] == dataset_name]
                            
                            # 결과 표시
                            for idx, result in enumerate(dataset_results, 1):
                                # rank와 total_docs 추가
                                result['rank'] = idx
                                result['total_docs'] = len(dataset_results)
                                
                                # 문서 선택 체크박스
                                doc_id = f"{dataset_name}_{result['chapter']}_{result['article']}"
                                
                                # 제목 형식 설정
                                if result.get('is_complex_format', False):
                                    display_title = f"📄 {result['display_chapter']} (관련도: {result['score']:.4f}, 순위: {idx}/{len(dataset_results)})"
                                elif result['title'] == 'null':
                                    display_title = f"📄 {result['chapter']} - {result['article']} (관련도: {result['score']:.4f}, 순위: {idx}/{len(dataset_results)})"
                                else:
                                    # 제목 길이 제한
                                    title = result['title']
                                    if len(title) > 20:
                                        title = title[:17] + "..."
                                    display_title = f"📄 {result['chapter']} - {result['article']} {title} (관련도: {result['score']:.4f}, 순위: {idx}/{len(dataset_results)})"
                                
                                is_selected = st.checkbox(
                                    display_title,
                                    key=f"doc_{doc_id}",
                                    value=doc_id in st.session_state.selected_documents
                                )
                                
                                if is_selected:
                                    st.session_state.selected_documents.add(doc_id)
                                else:
                                    st.session_state.selected_documents.discard(doc_id)
                                
                                # 아코디언 생성
                                with st.expander("문서 내용 보기", expanded=False):
                                    st.markdown(f"""
                                        <div style='padding: 0.5rem; background-color: #f8f9fa; border-radius: 0.25rem;'>
                                            <p style='margin: 0;'>{result['content']}</p>
                                        </div>
                                    """, unsafe_allow_html=True)
                            
                            st.divider()
                        
                        # 피드백 섹션
                        st.markdown("""
                            <div style='background-color: #e8f4ff; padding: 1rem; border-radius: 0.25rem; margin-bottom: 1rem;'>
                                <p style='margin: 0; color: #0066cc;'>3. 평가 및 코멘트를 입력 후 피드백 제출 버튼을 눌러주세요.</p>
                            </div>
                        """, unsafe_allow_html=True)
                        col1, col2 = st.columns([1, 2])
                        
                        with col1:
                            st.session_state.feedback_rating = st.radio(
                                "검색 결과 품질 평가",
                                ["A", "B", "C"],
                                index=None,
                                horizontal=True
                            )
                        
                        with col2:
                            st.session_state.feedback_comment = st.text_area(
                                "추가 코멘트 (선택사항)",
                                value=st.session_state.feedback_comment,
                                height=100
                            )
                        
                        if st.button("피드백 제출", type="secondary"):
                            feedback_data = {
                                'user_name': user_name,
                                'query': st.session_state.current_query,
                                'rating': st.session_state.feedback_rating,
                                'comment': st.session_state.feedback_comment,
                                'selected_documents': list(st.session_state.selected_documents),
                                'all_outputs': response_data["data"]["outputs"]["output"]
                            }
                            
                            if submit_feedback(user_name, feedback_data, response_data):
                                # 성공적으로 저장된 경우 세션 상태 초기화
                                st.session_state.feedback_rating = None
                                st.session_state.feedback_comment = ""
                                st.session_state.selected_documents = set()
                                
                                # 다음 질문하기 버튼 대신 즉시 초기화
                                st.session_state.search_results = None
                                st.session_state.current_query = None
                                
                                # 히스토리 최신화
                                gc = setup_google_sheets()
                                if gc:
                                    st.session_state.query_history = load_query_history(gc)
                                
                                # 페이지 상단으로 이동 및 새로고침 효과
                                st.experimental_rerun()
                    else:
                        st.warning("응답에서 결과를 찾을 수 없습니다.")
                
                with tab2:
                    st.json(response_data)
                    
            except Exception as e:
                st.error(f"오류 발생: {str(e)}")
else:
    # 이전 검색 결과가 있으면 표시
    if st.session_state.search_results is not None:
        response_data = st.session_state.search_results
        
        # 결과 표시
        st.subheader("검색 결과")
        
        # 탭 생성
        tab1, tab2 = st.tabs(["응답 내용", "전체 응답 데이터"])
        
        with tab1:
            if response_data.get("data", {}).get("outputs", {}).get("output"):
                outputs = response_data["data"]["outputs"]["output"]
                
                # hyde_query 표시 추가
                hyde_query = response_data.get("data", {}).get("outputs", {}).get("hyde_query")
                if hyde_query:
                    with st.expander("🔍 변환된 검색 query (가상문서)", expanded=False):
                        st.markdown("""
                            <div style='background-color: #f8f9fa; padding: 1rem; border-radius: 0.25rem; margin-bottom: 1rem;'>
                                <p style='color: #666; margin: 0;'>이 쿼리는 답변과 상관없는 검색을 위한 가상문서입니다.</p>
                            </div>
                        """, unsafe_allow_html=True)
                        st.markdown(f"""
                            <div style='background-color: #f0f0f0; padding: 1rem; border-radius: 0.25rem; 
                                white-space: pre-wrap; word-wrap: break-word; overflow-wrap: break-word; 
                                font-family: monospace;'>
                                {hyde_query}
                            </div>
                        """, unsafe_allow_html=True)
                    st.divider()
                
                # 결과 요약
                st.markdown(f"총 {len(outputs)}개의 관련 문서를 찾았습니다.")
                st.markdown("""
                    <div style='background-color: #e8f4ff; padding: 1rem; border-radius: 0.25rem; margin-bottom: 1rem;'>
                        <p style='margin: 0; color: #0066cc;'>📌 질문과 관련된 문서를 선택해주세요.</p>
                    </div>
                """, unsafe_allow_html=True)
                
                # 결과 데이터 준비
                results_data = []
                for output in outputs:
                    content = output.get('content', '')
                    metadata = output.get('metadata', {})
                    score = metadata.get('score', 0)
                    dataset_name = metadata.get('dataset_name', 'N/A')
                    
                    content_parts = content.split(';')
                    chapter = next((part.split(':')[1] for part in content_parts if '장번호' in part), 'N/A')
                    article = next((part.split(':')[1] for part in content_parts if '조번호' in part), 'N/A')
                    title_part = next((part.split(':')[1] for part in content_parts if '조제목' in part), '')
                    title = 'null' if not title_part or title_part.strip().lower() == 'nan' else title_part.strip()
                    
                    # 내용에서 장제목 부분 제거
                    content_without_title = ';'.join([part for part in content_parts if '조제목' not in part])
                    
                    # 특수 케이스 처리 - 복잡한 데이터 패턴 감지
                    is_complex_format = False
                    chapter_title = next((part.split(':')[1] for part in content_parts if '장제목' in part), '')
                    
                    # 복잡한 데이터 구조 감지 조건들
                    if any(pattern in article for pattern in ['|', '---------', '표']) or len(article) > 30:
                        is_complex_format = True
                    if article and article[0] == '|':  # 표 형식으로 시작하는 조번호
                        is_complex_format = True
                    
                    if is_complex_format:
                        # 간략한 제목으로 대체
                        display_chapter = f"{chapter}"
                        if chapter_title:
                            display_chapter = f"{chapter} - {chapter_title}"
                        if len(display_chapter) > 25:
                            display_chapter = display_chapter[:22] + "..."
                        article = ''  # 조번호 비우기
                    else:
                        display_chapter = chapter
                    
                    results_data.append({
                        'dataset_name': dataset_name,
                        'chapter': chapter,
                        'display_chapter': display_chapter,
                        'article': article,
                        'title': title,
                        'score': score,
                        'content': content_without_title,
                        'is_complex_format': is_complex_format
                    })
                
                # 점수 기준으로 정렬 (높은 순)
                results_data.sort(key=lambda x: x['score'], reverse=True)
                
                # 데이터셋별로 결과 그룹화
                for dataset_name in set(item['dataset_name'] for item in results_data):
                    st.subheader(f"📚 {dataset_name}")
                    
                    # 해당 데이터셋의 결과만 필터링
                    dataset_results = [item for item in results_data if item['dataset_name'] == dataset_name]
                    
                    # 결과 표시
                    for idx, result in enumerate(dataset_results, 1):
                        # rank와 total_docs 추가
                        result['rank'] = idx
                        result['total_docs'] = len(dataset_results)
                        
                        # 문서 선택 체크박스
                        doc_id = f"{dataset_name}_{result['chapter']}_{result['article']}"
                        
                        # 제목 형식 설정
                        if result.get('is_complex_format', False):
                            display_title = f"📄 {result['display_chapter']} (관련도: {result['score']:.4f}, 순위: {idx}/{len(dataset_results)})"
                        elif result['title'] == 'null':
                            display_title = f"📄 {result['chapter']} - {result['article']} (관련도: {result['score']:.4f}, 순위: {idx}/{len(dataset_results)})"
                        else:
                            # 제목 길이 제한
                            title = result['title']
                            if len(title) > 20:
                                title = title[:17] + "..."
                            display_title = f"📄 {result['chapter']} - {result['article']} {title} (관련도: {result['score']:.4f}, 순위: {idx}/{len(dataset_results)})"
                        
                        is_selected = st.checkbox(
                            display_title,
                            key=f"doc_{doc_id}",
                            value=doc_id in st.session_state.selected_documents
                        )
                        
                        if is_selected:
                            st.session_state.selected_documents.add(doc_id)
                        else:
                            st.session_state.selected_documents.discard(doc_id)
                        
                        # 아코디언 생성
                        with st.expander("문서 내용 보기", expanded=False):
                            st.markdown(f"""
                                <div style='padding: 0.5rem; background-color: #f8f9fa; border-radius: 0.25rem;'>
                                    <p style='margin: 0;'>{result['content']}</p>
                                </div>
                            """, unsafe_allow_html=True)
                    
                    st.divider()
                
                # 피드백 섹션
                st.markdown("""
                    <div style='background-color: #e8f4ff; padding: 1rem; border-radius: 0.25rem; margin-bottom: 1rem;'>
                        <p style='margin: 0; color: #0066cc;'>3. 평가 및 코멘트를 입력 후 피드백 제출 버튼을 눌러주세요.</p>
                    </div>
                """, unsafe_allow_html=True)
                col1, col2 = st.columns([1, 2])
                
                with col1:
                    st.session_state.feedback_rating = st.radio(
                        "검색 결과 품질 평가",
                        ["A", "B", "C"],
                        index=None,
                        horizontal=True
                    )
                
                with col2:
                    st.session_state.feedback_comment = st.text_area(
                        "추가 코멘트 (선택사항)",
                        value=st.session_state.feedback_comment,
                        height=100
                    )
                
                if st.button("피드백 제출", type="secondary"):
                    feedback_data = {
                        'user_name': user_name,
                        'query': st.session_state.current_query,
                        'rating': st.session_state.feedback_rating,
                        'comment': st.session_state.feedback_comment,
                        'selected_documents': list(st.session_state.selected_documents),
                        'all_outputs': response_data["data"]["outputs"]["output"]
                    }
                    
                    if submit_feedback(user_name, feedback_data, response_data):
                        # 성공적으로 저장된 경우 세션 상태 초기화
                        st.session_state.feedback_rating = None
                        st.session_state.feedback_comment = ""
                        st.session_state.selected_documents = set()
                        
                        # 다음 질문하기 버튼 대신 즉시 초기화
                        st.session_state.search_results = None
                        st.session_state.current_query = None
                        
                        # 히스토리 최신화
                        gc = setup_google_sheets()
                        if gc:
                            st.session_state.query_history = load_query_history(gc)
                        
                        # 페이지 상단으로 이동 및 새로고침 효과
                        st.experimental_rerun()
            else:
                st.warning("응답에서 결과를 찾을 수 없습니다.")
        
        with tab2:
            st.json(response_data)

# 푸터
st.divider()
st.markdown("© 2024 인사챗봇 RAG DATA 검색 평가 | 문의 : 최정규 주임 (Kyle)") 