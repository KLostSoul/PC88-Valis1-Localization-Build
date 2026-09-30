# 분석 근거·직접 바이트·검증 대응표

| 근거 ID | 분석 자료 | 실제 대상 | 적용 기록기 | 검증 |
|---|---|---|---|---|
| D88-ORIGINAL-GEOMETRY | 원본 D88 구조·해시 기록 | D88 컨테이너와 섹터 payload | `D88Image.read` | 입력 SHA-256과 재파싱 |
| EVENTS-RAW-OLD-GUARDS | 이벤트 최종 검증·패치 표 | D88 payload 명시 오프셋 | `apply_raw_tables` | 행별 원본 바이트 대조 |
| GAMEOVER-STRUCTURE | 게임오버 token_pairs 표 | 명시된 SUB 영역 | `apply_gameover` | 범위·토큰 길이·최종 해시 |
| ENDING-24-SEGMENTS | 엔딩 배치·보정·토큰 표 | 24개 종결 스트림 | `apply_raw_tables` | 세그먼트·종결자 검사 |
| KANJI-476-TXT | KANJI1 글리프 자료 | 476개 32바이트 슬롯 | `build_rom` | 글리프·슬롯·해시 |
| LOGO-RAW-MAP | 로고 PNG·`source-map.csv`·RAM-to-raw 대응표 | D88 raw 바이트 구간 | `logo_png` / `apply_logo_build`; 기본값은 `apply_raw_tables` | 원본 바이트·source roundtrip·릴리스 해시 |
| ERROR07-FINAL-TABLE | ERROR 07 패치 표 | 명령 스트림 구간 | `apply_raw_tables` | 원본 바이트·릴리스 해시 |

일본어 원문과 한글 번역은 `source/text/`에 별도 원천으로 보존합니다. 빌드 도구는 번역문에서 토큰을 다시 만들지 않습니다.
