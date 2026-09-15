# 프로젝트 수치 근거

2026-09-15 공개 GitHub 소스 기준. README의 성과 문구를 그대로 옮기지 않고 코드·CSV·배열 헤더를 대조했다. 아래 값은 작업 규모와 테스트 정의 수이며, 별도 표시가 없는 한 성능 개선율이나 사용자 효과가 아니다.

재집계: `python3 scripts/audit_project_metrics.py` (Python 표준 라이브러리만 사용, 약 100 MB 다운로드). 원본 프로젝트 코드를 실행하거나 pickle 모델을 로드하지 않는다. 링크와 집계 스크립트는 조사 시점 커밋으로 고정했다.

## LXP

- AI 패키지의 테스트 정의 **41개 / 7개 파일**: 캐시 5, 과제 초안 6, 진단 비용 방어 5, Q&A 9, 상태 안내 9, 자료 추출 5, 사용량 로그 트랜잭션 2.
- [테스트 디렉터리](https://github.com/min03027/samsung_axi_2nd/tree/9c6b4003fc4e84bf58d3c23990cf4c4e2d26acfc/src/test/java/com/ssa/lms/ai): 주석을 제외한 `@Test`를 집계. `@TestConfiguration`은 제외. 해당 파일에 `@Disabled` 없음.
- [캐시 테스트](https://github.com/min03027/samsung_axi_2nd/blob/9c6b4003fc4e84bf58d3c23990cf4c4e2d26acfc/src/test/java/com/ssa/lms/ai/AiAdviceCacheTest.java#L24-L36): **같은 키 20회 순차 조회 → 생성 함수 호출 수 1회**를 검사하도록 작성되어 있다.
- [캐시 구현](https://github.com/min03027/samsung_axi_2nd/blob/9c6b4003fc4e84bf58d3c23990cf4c4e2d26acfc/src/main/java/com/ssa/lms/ai/service/AiAdviceCache.java#L60-L79): 유효 캐시가 있으면 생성 함수를 부르지 않고 반환한다.
- **한계**: 이번 조사는 정적 검사다. 로컬 Java 런타임이 없어 JUnit 테스트를 실행하지 않았고, 41개 통과·커버리지·운영 API 비용 95% 절감을 주장하지 않는다. 20회 시나리오는 실제 API가 아니라 카운터를 증가시키는 생성 함수를 사용하며, 동시 요청 테스트가 아니다.

## Jeju

- [가맹점 월별 원본 CSV](https://github.com/min03027/jeju_2024/blob/80a1dde19921a8f8671a0acd034e79b8bfb6cc2e/data/JEJU_DATA.csv): 헤더 제외 **67,575행**, **2023.08~2024.07의 12개월**.
- [앱 전처리](https://github.com/min03027/jeju_2024/blob/80a1dde19921a8f8671a0acd034e79b8bfb6cc2e/app.py#L20-L26): `가맹점명`별 `기준연월` 최댓값을 선택하면 **9,346행**. 가맹점명이 키이므로 실제 고유 사업장 수와 동일하다고 단정하지 않는다.
- [관광지 CSV](https://github.com/min03027/jeju_2024/blob/80a1dde19921a8f8671a0acd034e79b8bfb6cc2e/data/JEJU_TOUR.csv): 헤더 제외 **381행**.
- [가맹점 임베딩](https://github.com/min03027/jeju_2024/blob/80a1dde19921a8f8671a0acd034e79b8bfb6cc2e/modules/embeddings_array_file_1.npy) 배열 헤더는 **9,346 × 768**, [관광지 임베딩](https://github.com/min03027/jeju_2024/blob/80a1dde19921a8f8671a0acd034e79b8bfb6cc2e/modules/embeddings_tour_array_file_1.npy)은 **381 × 768**. 전처리된 데이터 수와 배열 행 수가 일치한다. 값별 정렬·매핑 정확도나 검색 품질을 검증했다는 뜻은 아니다.
- [검색 코드](https://github.com/min03027/jeju_2024/blob/80a1dde19921a8f8671a0acd034e79b8bfb6cc2e/app.py#L139-L174): 기본 `k=3`에서 가맹점 후보 `k*3=9`건과 관광지 1건을 검색한 뒤 가격대 필터 적용. README의 Top-10과 달라 코드 기준을 사용했다.
- **한계**: 조사한 공개 버전에는 Neo4j/그래프 재정렬 코드와 검색 성능 평가 로그가 없다. 가맹점 수·임베딩 차원·후보 수를 정확도나 개선율로 표현하지 않는다.

## Stayview

- [배포용 CSV](https://github.com/min03027/stayview/blob/5300c95c08ee5cf325935f7fa7f29f31727c3987/hotel_fin_0331_2.csv): **9개 지역·호텔 요약 데이터 394행**. 헤더 제외, `euc-kr` 디코딩 후 CSV 파서로 집계.
- `Hotel` 고유값은 **392개**이므로 394개 고유 호텔 또는 394개 리뷰라고 쓰지 않는다. 같은 이름이 실제 동일 숙소인지까지 검증하지 않았다.
- [화면 구현](https://github.com/min03027/stayview/blob/5300c95c08ee5cf325935f7fa7f29f31727c3987/streamlit_hotel_viewer_with_fonts.py#L72-L95): **6개 항목**(소음·가격·위치·서비스·청결·편의시설), 지역과 항목 선택 후 상품명 아닌 `Hotel` 기준 중복을 제외하고 **Top-5**를 표시.
- **한계**: 공개 저장소는 사전 분석 결과를 읽는 UI와 집계 CSV 중심이다. 원본 리뷰 11만 건, 모델 학습·요약 개선율은 여기서 독립적으로 검증할 수 없다. 394행은 원본 리뷰 수를 대체 측정한 값이 아니라 배포용 집계 데이터의 규모다.

## Nohuae

- [공시 데이터 저장소](https://github.com/min03027/senior_finance_recommender/tree/ab024e6a1ddd177e610aa181ddb05fd022dc1bb0): `금융상품_3개_통합본.csv` **1,122행**, `펀드_병합본.csv` **9,598행**, 합계 **10,720행**. 헤더 제외, `utf-8-sig`로 CSV 파싱. 파일 내 줄바꿈 때문에 단순 줄 수를 사용하지 않았다.
- **중복 제거 전 원본 행 수**다. 상품명·펀드명 비어 있지 않은 고유값은 각각 440개와 9,596개이며, 동일 이름의 다른 상품·클래스 여부는 별도 검증하지 않았다.
- [전처리·필터·벡터화 코드](https://github.com/min03027/senior_finance_recommender/blob/ab024e6a1ddd177e610aa181ddb05fd022dc1bb0/senior_survey_paged_app.py#L100-L210): 상품명을 기준으로 중복 제거, 투자금액·기간·위험성향 조건 필터, 금액·수익률·기간의 3차원 벡터 구성.
- [추천 코드](https://github.com/min03027/senior_finance_recommender/blob/ab024e6a1ddd177e610aa181ddb05fd022dc1bb0/senior_survey_paged_app.py#L236-L276): 유형별 필터 후 예·적금 최대 2개와 펀드 최대 1개를 검색해 최대 3개 표시. 적합 후보가 없으면 더 적게 반환할 수 있다.
- **한계**: 일부 상품 속성의 결측·부재를 난수로 보완하는 프로토타입이다. 원본 공시 기반이라고 해서 추천에 쓰는 모든 속성이 실제 공시값인 것은 아니다. 실제 가입 자격 검증·추천 정확도·실사용자 효과를 보장하지 않는다. README의 65%, +27%p, +23%p는 평가 코드·로그·분모가 없어 이번 반영 대상에서 제외했다.

## 추가 수치를 넣지 않은 프로젝트

- **또박톡**: `tobaktok`는 본체 코드가 없는 실행 보조 저장소, `tobaktok_live`에는 Whisper Small 설정·토크나이저 등이 있다. WER 21.2%의 계산 로그·평가 데이터·학습 전 비교값은 확인되지 않았다. 기존 본인 제시 수치는 유지하되, GitHub로 검증된 성능으로 격상하지 않는다.
- **FitBuddy**: 공개 학습 스크립트에 테스트 분할 20%, RandomForest 트리 200개 등 설정이 있지만 평가 출력이 없다. 설정값을 성과로 추가하지 않는다. 일부 베이스라인의 라벨은 자세 깊이 규칙으로 만든 임시 라벨이므로 의료적 안전성이나 전문가 판정 성능으로 해석하지 않는다.
