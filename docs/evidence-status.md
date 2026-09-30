# 분석 근거 상태

재현 빌드는 v1.02 직접 바이너리 재현 기준으로 구성되어 있습니다.

- 원본 D88의 크기·섹터 구조와 KANJI1 ROM의 크기·해시를 빌드 시 확인합니다.
- 이벤트 1~6은 일본어 원문, 한글 번역, 토큰, raw 바이트를 보존합니다.
- 게임오버는 고정·스크롤·marker·hold 자료를 보존합니다.
- 엔딩은 24개 세그먼트와 종결자를 보존합니다.
- 로고·ERROR 07·문자 토큰 소비 루틴·KANJI1 근거는 직접 기록표와 관찰 자료로 보존합니다.
- 최종 바이트는 컴포넌트의 검토된 표에서 생성합니다. 로고는 `source/GFX/` PNG를 실제 입력으로 읽고 `source/tables/logo/source-map.csv`에 정의된 그룹·plane·주소·길이·크기·인코더에 따라 편집 그룹을 061F/05CE로 재인코딩합니다.
- 기본 로고 출력은 `source/tables/logo/raw-changes.csv`에서 재현하며, PNG를 편집한 그룹에는 `ram-to-raw-map.csv`의 payload 대응을 사용합니다. D88·ROM 매체와 산출물은 로컬에만 둡니다.
- 완료본과 IPS는 결과 대조에 사용합니다.

`source-lint`, `text-lint`, 테스트, 원본 검사, 결과 해시 검사, 선택적 `compare --fail-on-diff`가 검증 문턱입니다.
