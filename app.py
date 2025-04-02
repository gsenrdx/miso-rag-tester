import streamlit as st
import requests
import json
import os
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time

# -------------------------------
# 1. 페이지 기본 설정
# -------------------------------
st.set_page_config(
    page_title="인사챗봇 RAG DATA 검색 평가",
    page_icon="🔍",
    layout="wide"
)

# -------------------------------
# 2. 환경 변수 로드
#    로컬(.env) / Streamlit Cloud(secrets) 분기
# -------------------------------
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
    API_URL = os.getenv("MISO_API_URL")
    API_KEY = os.getenv("MISO_API_KEY")
    GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
else:
    API_URL = st.secrets.get("MISO_API_URL")
    API_KEY = st.secrets.get("MISO_API_KEY")
    GOOGLE_SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID")

# -------------------------------
# 3. 구글 시트 연결 함수
# -------------------------------
def setup_google_sheets():
    """구글 시트 연결을 위한 자격 증명 설정"""
    try:
        scope = ['https://spreadsheets.google.com/feeds',
                 'https://www.googleapis.com/auth/drive']
        
        # 로컬 개발 환경에서 credentials.json 파일 사용
        if os.path.exists('credentials.json'):
            credentials = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        else:
            # Streamlit Cloud에서 secrets 사용
            gcp_creds = st.secrets.get("gcp_service_account", {})
            credentials = ServiceAccountCredentials.from_json_keyfile_dict(gcp_creds, scope)

        gc = gspread.authorize(credentials)
        return gc
    except Exception as e:
        st.error(f"구글 시트 설정 중 오류 발생: {str(e)}")
        return None

# -------------------------------
# 4. 질문 히스토리 로드 함수
# -------------------------------
def load_query_history(gc):
    """구글 시트에서 질문 히스토리를 로드"""
    try:
        spreadsheet_id = GOOGLE_SHEET_ID
        if not spreadsheet_id:
            st.error("구글 시트 ID가 설정되지 않았습니다.")
            return []
        
        sheet = gc.open_by_key(spreadsheet_id).sheet1
        all_values = sheet.get_all_values()

        # 첫 행(헤더) 제외한 데이터만 처리
        history = []
        for row in all_values[1:]:
            if len(row) >= 6:
                selected_docs = row[5].split(';') if row[5] else []
                history.append({
                    'timestamp': row[0],
                    'user_name': row[1],
                    'query': row[2],
                    'rating': row[3],
                    'comment': row[4],
                    'selected_documents': selected_docs
                })
        # 최신순 정렬
        history.sort(key=lambda x: x['timestamp'], reverse=True)
        return history
    except Exception as e:
        st.error(f"질문 히스토리 로드 중 오류 발생: {str(e)}")
        return []

# -------------------------------
# 5. 피드백을 구글 시트에 저장
# -------------------------------
def save_feedback_to_sheet(gc, feedback_data):
    """피드백(사용자 평가)을 구글 시트에 저장"""
    try:
        spreadsheet_id = GOOGLE_SHEET_ID
        if not spreadsheet_id:
            st.error("구글 시트 ID가 설정되지 않았습니다.")
            return False
        
        sheet = gc.open_by_key(spreadsheet_id).sheet1
        
        # 현재 시간
        feedback_data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 선택된 문서 정보 가공
        selected_docs_info = []
        for doc_id in feedback_data['selected_documents']:
            try:
                # doc_id 예: dataset_chapter_article
                parts = doc_id.split('_', 2)
                if len(parts) != 3:
                    continue
                dataset_name, chapter, article = parts
                
                # 전체 결과(all_outputs)에서 해당 문서 메타데이터 찾기
                for idx, output in enumerate(feedback_data['all_outputs'], 1):
                    content = output.get('content', '')
                    content_parts = content.split(';')
                    
                    # 장/조/제목 정보 추출
                    doc_chapter = next((p.split(':')[1].strip() for p in content_parts if '장번호' in p), '')
                    doc_article = next((p.split(':')[1].strip() for p in content_parts if '조번호' in p), '')
                    doc_title = next((p.split(':')[1].strip() for p in content_parts if '조제목' in p), '')
                    
                    if (
                        output.get('metadata', {}).get('dataset_name') == dataset_name and
                        doc_chapter == chapter and
                        doc_article == article
                    ):
                        score = output.get('metadata', {}).get('score', 0)
                        doc_info = f"{dataset_name} - {chapter} - {article}"
                        
                        if doc_title and doc_title.lower() != 'nan':
                            doc_info += f" ({doc_title})"
                        
                        doc_info += f" (관련도: {score:.4f}, 순위: {idx}/{len(feedback_data['all_outputs'])})"
                        selected_docs_info.append(doc_info)
                        break
            except Exception as e:
                st.error(f"문서 정보 처리 중 오류 발생: {str(e)}")
                continue
        
        # 행 단위로 시트에 추가할 데이터 구성
        row = [
            feedback_data['timestamp'],
            feedback_data['user_name'],
            feedback_data['query'],
            feedback_data['rating'],
            feedback_data['comment'],
            '; '.join(selected_docs_info)
        ]
        
        # 마지막 행 다음에 추가
        last_row = len(sheet.get_all_values()) + 1
        for col, value in enumerate(row, start=1):
            sheet.update_cell(last_row, col, value)
        
        return True
    except Exception as e:
        st.error(f"피드백 저장 중 오류 발생: {str(e)}")
        return False

# -------------------------------
# 6. 피드백 제출 처리 함수
# -------------------------------
def submit_feedback(user_name, feedback_data):
    """
    사용자가 제출한 피드백을 처리:
    1) 유효성 검사
    2) 구글 시트 저장
    3) 내부 히스토리 갱신
    """
    # 유효성 검사
    errors = []
    if not user_name:
        errors.append("사용자 이름을 입력해주세요.")
    if not feedback_data['rating']:
        errors.append("검색 결과 품질 평가를 선택해주세요.")
    if not feedback_data['selected_documents']:
        errors.append("관련 문서를 하나 이상 선택해주세요.")
    
    if errors:
        for err in errors:
            st.error(err)
        return False
    
    st.session_state.is_submitting = True
    try:
        gc = setup_google_sheets()
        if gc:
            with st.spinner("피드백을 저장하는 중..."):
                success = save_feedback_to_sheet(gc, feedback_data)
                if success:
                    # 세션 히스토리도 즉시 반영
                    query_history_data = {
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'user_name': user_name,
                        'query': feedback_data['query'],
                        'rating': feedback_data['rating'],
                        'comment': feedback_data['comment'],
                        'selected_documents': feedback_data['selected_documents']
                    }
                    st.session_state.query_history.insert(0, query_history_data)
                    
                    # 저장 성공 메시지
                    st.success("피드백이 성공적으로 저장되었습니다. 감사합니다!")
                    st.markdown(
                        """
                        <div style='background-color: #e8f4ff; padding: 1rem; border-radius: 0.25rem; margin: 1rem 0;'>
                            <p style='margin: 0; color: #0066cc;'>📊 피드백 결과는 
                            <a href='https://docs.google.com/spreadsheets/d/1M264J2XJLEaYjZNZLEhvaBgA_TZtzabnnumw-8QbF_8/edit?usp=sharing' 
                            target='_blank'>구글 시트</a>에서 확인하실 수 있습니다.</p>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    
                    # 피드백 저장 후 상태 초기화
                    st.session_state.search_results = None
                    st.session_state.current_query = None
                    st.session_state.feedback_rating = None
                    st.session_state.feedback_comment = ""
                    st.session_state.checkbox_states = {}
                    st.session_state.last_search_time = None
                    
                    # 히스토리 최신화
                    st.session_state.query_history = load_query_history(gc)
                    
                    # 3초 대기 후 리프레시
                    st.info("피드백이 저장되었습니다. 3초 후 페이지가 초기화됩니다...")
                    time.sleep(3)
                    st.experimental_rerun()
                    return True
                else:
                    st.error("피드백 저장에 실패했습니다. 다시 시도해주세요.")
                    return False
    finally:
        st.session_state.is_submitting = False

# -------------------------------
# 7. 검색 결과 파싱 및 표시 함수
# -------------------------------
def parse_search_results(response_data):
    """
    API 응답에서 output1, output2, output3 모두 꺼내
    하나의 리스트로 모아서 반환
    """
    outputs = []
    data = response_data.get("data", {}).get("outputs", {})
    
    for key in ["output1", "output2", "output3"]:
        if key in data:
            val = data[key]
            if isinstance(val, list):
                outputs.extend(val)
            else:
                outputs.append(val)
    return outputs

def process_output(output):
    """단일 output 딕셔너리를 파싱하여 필요한 정보만 추출"""
    content = output.get('content', '')
    metadata = output.get('metadata', {})
    
    dataset_name = metadata.get('dataset_name', 'N/A')
    score = metadata.get('score', 0)
    
    # 문서 정보 파싱
    parts = content.split(';')
    chapter = next((p.split(':')[1].strip() for p in parts if '장번호' in p), 'N/A')
    article = next((p.split(':')[1].strip() for p in parts if '조번호' in p), 'N/A')
    title_part = next((p.split(':')[1].strip() for p in parts if '조제목' in p), '')
    if not title_part or title_part.lower() == 'nan':
        title_part = ''
    
    # FAQ 등 특수 케이스 처리
    row_id = next((p.split(':')[1].strip() for p in parts if 'row_id' in p), '')
    faq_question = next((p.split(':')[1].strip() for p in parts if '질문' in p), '')
    if dataset_name == 'FAQ.csv' and row_id and faq_question:
        return {
            'dataset_name': dataset_name,
            'chapter': row_id,
            'article': '',
            'title': '',
            'score': score,
            'content': content,
            'is_faq': True,
            'faq_display': f"{row_id} - {faq_question}"
        }
    
    # 일반 문서
    return {
        'dataset_name': dataset_name,
        'chapter': chapter,
        'article': article,
        'title': title_part,
        'score': score,
        'content': content,
        'is_faq': False
    }

def display_search_results(response_data):
    """
    검색 결과를 화면에 표시하고,
    체크박스로 문서를 선택할 수 있도록 구성.
    선택 상태는 st.session_state.checkbox_states에 저장.
    """
    tab1, tab2 = st.tabs(["응답 내용", "전체 응답 데이터"])
    
    with tab1:
        # 파싱
        outputs = parse_search_results(response_data)
        if not outputs:
            st.warning("응답에서 결과를 찾을 수 없습니다.")
            return
        
        # hyde_query(가상문서) 표시
        hyde_query = response_data.get("data", {}).get("outputs", {}).get("hyde_query")
        if hyde_query:
            with st.expander("🔍 변환된 검색 query (가상문서)", expanded=False):
                st.markdown(
                    """
                    <div style='background-color: #f8f9fa; padding: 1rem; border-radius: 0.25rem; margin-bottom: 1rem;'>
                        <p style='color: #666; margin: 0;'>이 쿼리는 답변과 상관없는 검색을 위한 가상문서입니다.</p>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                st.markdown(
                    f"""
                    <div style='background-color: #f0f0f0; padding: 1rem; border-radius: 0.25rem; 
                        white-space: pre-wrap; word-wrap: break-word; overflow-wrap: break-word; 
                        font-family: monospace;'>
                        {hyde_query}
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            st.divider()
        
        # 출력 데이터 가공
        results_data = [process_output(o) for o in outputs]
        
        # 점수 내림차순 정렬
        results_data.sort(key=lambda x: x['score'], reverse=True)
        
        # 문서 갯수 표시
        st.markdown(f"총 {len(results_data)}개의 관련 문서를 찾았습니다.")
        st.markdown(
            """
            <div style='background-color: #e8f4ff; padding: 1rem; border-radius: 0.25rem; margin-bottom: 1rem;'>
                <p style='margin: 0; color: #0066cc;'>2. 질문과 관련된 문서를 선택해주세요.</p>
            </div>
            """,
            unsafe_allow_html=True
        )
        
        # 데이터셋 이름별로 그룹화해서 표시
        from collections import defaultdict
        grouped = defaultdict(list)
        for idx, item in enumerate(results_data):
            grouped[item['dataset_name']].append((idx, item))
        
        for dataset_name, items in grouped.items():
            st.subheader(f"📚 {dataset_name}")
            
            for rank, (idx, item) in enumerate(items, start=1):
                # 체크박스 키(전역 인덱스 기반: "doc_checkbox_{idx}")
                checkbox_key = f"doc_checkbox_{idx}"
                
                # 체크박스 기본값 가져오기 (없으면 False)
                default_val = st.session_state.checkbox_states.get(checkbox_key, False)
                
                # 표시할 문서 제목 구성
                score_text = f"(관련도: {item['score']:.4f}, 순위: {rank}/{len(items)})"
                if item['is_faq']:
                    # FAQ 형식
                    display_title = f"📄 {item['faq_display']} {score_text}"
                else:
                    # 일반 문서
                    if item['title']:
                        short_title = (item['title'][:20] + "...") if len(item['title']) > 20 else item['title']
                        display_title = f"📄 {item['chapter']} - {item['article']} {short_title} {score_text}"
                    else:
                        display_title = f"📄 {item['chapter']} - {item['article']} {score_text}"
                
                # 체크박스
                user_checked = st.checkbox(display_title, value=default_val, key=checkbox_key)
                
                # 사용자가 체크/해제한 상태를 세션에 저장
                st.session_state.checkbox_states[checkbox_key] = user_checked
                
                # 문서 내용 보기
                with st.expander("문서 내용 보기", expanded=False):
                    st.markdown(
                        f"""
                        <div style='padding: 0.5rem; background-color: #f8f9fa; border-radius: 0.25rem;'>
                            <p style='margin: 0;'>{item['content']}</p>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
            
            st.divider()
        
        # -------------------------------
        # 피드백 섹션
        # -------------------------------
        st.markdown(
            """
            <div style='background-color: #e8f4ff; padding: 1rem; border-radius: 0.25rem; margin-bottom: 1rem;'>
                <p style='margin: 0; color: #0066cc;'>3. 평가 및 코멘트를 입력 후 피드백 제출 버튼을 눌러주세요.</p>
            </div>
            """,
            unsafe_allow_html=True
        )
        
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
            # 체크박스 중 True인 것만 선택
            selected_docs = []
            for idx, item in enumerate(results_data):
                ckey = f"doc_checkbox_{idx}"
                if st.session_state.checkbox_states.get(ckey, False):
                    # doc_id: dataset_chapter_article 형태
                    # FAQ는 article이 ''일 수 있음
                    doc_id = f"{item['dataset_name']}_{item['chapter']}_{item['article']}"
                    selected_docs.append(doc_id)
            
            feedback_data = {
                'user_name': st.session_state.user_name,
                'query': st.session_state.current_query,
                'rating': st.session_state.feedback_rating,
                'comment': st.session_state.feedback_comment,
                'selected_documents': selected_docs,
                'all_outputs': outputs  # 원본 API 결과
            }
            submit_feedback(st.session_state.user_name, feedback_data)
    
    # 전체 JSON 응답 표시
    with tab2:
        st.json(response_data)

# -------------------------------
# 8. 세션 상태 초기화
# -------------------------------
if 'query_history' not in st.session_state:
    st.session_state.query_history = []
if 'search_results' not in st.session_state:
    st.session_state.search_results = None
if 'current_query' not in st.session_state:
    st.session_state.current_query = None
if 'checkbox_states' not in st.session_state:
    st.session_state.checkbox_states = {}  # {checkbox_key: bool}
if 'feedback_rating' not in st.session_state:
    st.session_state.feedback_rating = None
if 'feedback_comment' not in st.session_state:
    st.session_state.feedback_comment = ""
if 'user_name' not in st.session_state:
    st.session_state.user_name = ""
if 'is_submitting' not in st.session_state:
    st.session_state.is_submitting = False
if 'last_search_time' not in st.session_state:
    st.session_state.last_search_time = None

# -------------------------------
# 9. 메인 페이지
# -------------------------------
st.title("인사챗봇 RAG DATA 검색 평가")
st.markdown(
    """
    <div style='background-color: #e8f4ff; padding: 1rem; border-radius: 0.25rem; margin-bottom: 1rem;'>
        <p style='margin: 0; color: #0066cc;'>1. 테스트할 질문을 입력해주세요.</p>
    </div>
    """,
    unsafe_allow_html=True
)

# 사이드바: 사용자 설정
with st.sidebar:
    st.header("사용자 설정")
    st.session_state.user_name = st.text_input("이름", value=st.session_state.user_name)
    user_position = "매니저"
    user_company = "GSPOGE"
    
    st.write("현재 사용자:", st.session_state.user_name)
    
    st.divider()
    st.subheader("📝 질문 히스토리")
    
    if not st.session_state.user_name:
        st.info("이름을 입력하면 질문 히스토리가 표시됩니다.")
    else:
        # 구글 시트에서 히스토리 로드
        gc = setup_google_sheets()
        if gc:
            st.session_state.query_history = load_query_history(gc)
        
        # 사용자 히스토리 필터링
        user_history = [q for q in st.session_state.query_history if q.get('user_name') == st.session_state.user_name]
        
        if not user_history:
            st.info(f"{st.session_state.user_name}님의 질문 히스토리가 없습니다.")
        else:
            for item in user_history:
                with st.expander(f"질문: {item['query']}", expanded=False):
                    st.markdown(
                        f"""
                        <div style='background-color: #f8f9fa; padding: 0.5rem; border-radius: 0.25rem; margin-bottom: 0.5rem;'>
                            <p style='margin: 0;'><strong>평가:</strong> {item['rating']}</p>
                            <p style='margin: 0;'><strong>시간:</strong> {item['timestamp']}</p>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    if item.get('comment'):
                        st.markdown(
                            f"""
                            <div style='background-color: #f8f9fa; padding: 0.5rem; border-radius: 0.25rem;'>
                                <p style='margin: 0;'><strong>코멘트:</strong> {item['comment']}</p>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    if 'selected_documents' in item:
                        st.markdown(
                            f"""
                            <div style='background-color: #f8f9fa; padding: 0.5rem; border-radius: 0.25rem;'>
                                <p style='margin: 0;'><strong>선택된 문서:</strong></p>
                                <ul style='margin: 0.5rem 0 0 1.5rem;'>
                                    {''.join([f"<li>{doc}</li>" for doc in item['selected_documents']])}
                                </ul>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )

# 질문 입력
query = st.text_area("질문 입력", height=100)

# -------------------------------
# 10. "Data 검색" 버튼
# -------------------------------
if st.button("Data 검색", type="primary"):
    if not query:
        st.error("질문을 입력해주세요.")
    else:
        # 새로운 검색 시 체크박스 상태 초기화
        st.session_state.checkbox_states = {}
        st.session_state.last_search_time = datetime.now().strftime('%Y%m%d%H%M%S')
        
        with st.spinner("검색 중..."):
            payload = {
                "user": {
                    "name": st.session_state.user_name,
                    "position": user_position,
                    "company": user_company
                },
                "inputs": {
                    "query": query
                },
                "query": query
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {API_KEY}"
            }
            try:
                response = requests.post(API_URL, headers=headers, json=payload)
                if response.status_code == 200 and response.text.strip():
                    try:
                        response_data = response.json()
                        st.session_state.search_results = response_data
                        st.session_state.current_query = query
                        
                        # 검색 결과 표시
                        st.subheader("검색 결과")
                        display_search_results(response_data)
                    except json.JSONDecodeError as e:
                        st.error(f"JSON 파싱 오류: {str(e)}, 응답 내용: {response.text[:200]}...")
                else:
                    st.error(f"API 오류 - 상태코드: {response.status_code}, 응답: {response.text}")
            except Exception as e:
                st.error(f"오류 발생: {str(e)}")

# -------------------------------
# 11. 기존 검색 결과 표시 (재실행 시)
# -------------------------------
elif st.session_state.search_results is not None:
    st.subheader("검색 결과")
    display_search_results(st.session_state.search_results)

# -------------------------------
# 12. 푸터
# -------------------------------
st.divider()
st.markdown("© 2024 인사챗봇 RAG DATA 검색 평가 | 문의 : 최정규 주임 (Kyle)")
