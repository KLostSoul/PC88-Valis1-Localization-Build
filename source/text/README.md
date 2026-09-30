# 원문·번역 원천표

이 디렉터리는 완료본 ZIP 내부 분석 문서의 원문/한글 번역 열을 그대로
행 단위로 전사한 source다. 주소나 토큰을 문장으로부터 추정하지 않는다.

- `event-block-1.jsonl`: 첫 이벤트 번역 입력용 대본 170행
- `event-block-2.jsonl`: 두 번째 이벤트 36개 원문/번역 문장
- `event-block-3.jsonl`: 세 번째 이벤트 23개 원문/번역 문장
- `event-block-4.jsonl`: 네 번째 이벤트 19개 원문/번역 문장
- `event-block-5.jsonl`: 다섯 번째 이벤트 39개 원문/번역 문장
- `event-block-6.jsonl`: 여섯 번째 이벤트 10개 원문/번역 문장
- `ending-24.jsonl`: 엔딩 24개 세그먼트의 일본어 원문/한글 번역표
- `gameover-fixed.jsonl`: 게임오버 고정 1~15, 문장·토큰쌍·주소표
- `gameover-scroll.jsonl`: 스크롤 1~35, 문장·토큰쌍·주소표

`event-block-1`~`event-block-6`과 `ending-24`가 원문/번역의 문장 단위
표다. `event-block-2-korean`~`event-block-6-korean`은 별도의 최종
검증표로 제어행·문자행·주소·literal byte를 보존한다. 두 층을 합쳐서
문장이나 토큰을 다시 추정하지 않는다.

각 레코드의 `provenance`는 원문 문서의 상대 경로, 표 번호, 행 번호를
가리킨다. `token_pairs`는 번역문에서 자동 생성한 값이 아니라 완료본 ZIP의
검증표에 명시된 최종 토큰 열을 전사한 것이다.
